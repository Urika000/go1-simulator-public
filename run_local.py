#!/usr/bin/env python3
"""Host-only LOCAL launcher. Simulator Compose, optionally with Participant Docker CLI."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time
import uuid

from participant_runtime import ContainerSpec, ParticipantRuntime, docker

ROOT = Path(__file__).resolve().parent

READINESS = r"""
import sys
import rclpy
from rosgraph_msgs.msg import Clock
from rclpy.qos import qos_profile_sensor_data, QoSProfile, DurabilityPolicy
rclpy.init()
n = rclpy.create_node('local_launch_readiness')
received = []
s = n.create_subscription(Clock, '/clock', lambda msg: received.append(msg), qos_profile_sensor_data)
ready = []
if sys.argv[1] == 'lowlevel':
    from unitree_go.msg import LowState
    state = n.create_subscription(LowState, '/lowstate', lambda msg: ready.append(True), qos_profile_sensor_data)
else:
    from std_msgs.msg import Bool
    state = n.create_subscription(Bool, '/go1_ready', lambda msg: ready.append(msg.data) if msg.data else None,
        QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
while not (received and ready):
    rclpy.spin_once(n, timeout_sec=0.2)
print('Simulator ready: clock + state/ready payloads', flush=True)
n.destroy_node()
rclpy.shutdown()
"""


class StopRequested(Exception):
    pass


class LocalRun:
    def __init__(self, args):
        self.args = args
        self.token = 'go1-local-' + uuid.uuid4().hex[:16]
        self.sim = self.token + '-sim'
        self.part = self.token + '-participant'
        self.runtime = None
        self.domain_lock = None
        self.logs = []
        self.signal = None
        self.env = os.environ.copy()
        self.compose = ['docker', 'compose', '-p', self.token, '-f', str(ROOT/'docker-compose.yml')]
        if not args.gui:
            self.compose += ['-f', str(ROOT/'docker-compose.headless.yml')]

    def check_stop(self):
        if self.signal:
            raise StopRequested()

    def reserve_domain(self):
        directory = Path('/tmp/go1-local-domains')
        directory.mkdir(exist_ok=True)
        candidates = [self.args.domain] if self.args.domain else random.sample(range(100, 230), 130)
        for domain in candidates:
            lock = (directory/f'{domain}.lock').open('w')
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lock.close()
                continue
            self.domain_lock = lock
            return domain
        raise RuntimeError('ROS domain already reserved by launcher')

    def sim_inspect(self):
        data = json.loads(docker('inspect', self.sim, capture_output=True).stdout)[0]
        if data['Config']['Labels'].get('com.docker.compose.project') != self.token:
            raise RuntimeError('Simulator ownership label mismatch')
        return data

    def wait_ready(self, mode):
        child = subprocess.Popen(['docker', 'exec', '-i', self.sim, 'bash', '-c',
                                  'source /etc/go1_sim_env.sh; exec python3 - "$1"', '_', mode],
                                 stdin=subprocess.PIPE, text=True)
        deadline = time.monotonic() + self.args.timeout
        try:
            child.stdin.write(READINESS)
            child.stdin.close()
            while child.poll() is None:
                self.check_stop()
                if time.monotonic() >= deadline:
                    raise RuntimeError(f'Simulator readiness timeout ({self.args.timeout}s)')
                if not self.sim_inspect()['State']['Running']:
                    raise RuntimeError('Simulator exited before readiness')
                time.sleep(.2)
            self.check_stop()
            if child.returncode:
                raise RuntimeError(f'Simulator readiness probe failed ({child.returncode})')
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()

    def start(self):
        docker('info', stdout=subprocess.DEVNULL)
        images = [self.args.sim_image] if self.args.sim_only else [self.args.sim_image, self.args.participant_image]
        for image in images:
            data = json.loads(docker('image', 'inspect', image, capture_output=True).stdout)[0]
            if data['Os'] != 'linux' or data['Architecture'] != 'amd64':
                raise RuntimeError(f'{image}: requires linux/amd64')
        self.check_stop()
        domain = self.reserve_domain()
        mode = {'T2': 'lowlevel', 'T3': 'lowlevel', 'T4': 'highlevel', 'T5': 'course'}[self.args.task]
        self.env.update(SIM_IMAGE=self.args.sim_image, ROS_DOMAIN_ID=str(domain), GO1_DDS_LOCAL='1',
                        GO1_SIM_CYCLONEDDS_URI='file:///home/ros/ros2_custom_config_setup/cyclonedds_local.xml',
                        GO1_GAZEBO_LOCKSTEP='true', GO1_CAMERAS='true' if self.args.task == 'T5' else 'false',
                        COURSE_WIDTH=self.args.course_width, GUI=str(self.args.gui).lower())
        subprocess.run(self.compose + ['config', '--quiet'], env=self.env, check=True, timeout=30)
        print(f'Run={self.token} domain={domain} task={self.args.task}\nSimulator={self.sim}', flush=True)
        if not self.args.sim_only:
            print(f'Participant={self.part}', flush=True)
        self.check_stop()
        subprocess.run(self.compose + ['run', '--no-deps', '--pull', 'never', '-d', '--name', self.sim, mode],
                       env=self.env, check=True, timeout=30, stdout=subprocess.DEVNULL)
        self.wait_ready(mode)
        self.check_stop()
        if not self.args.sim_only:
            # Inline XML: arbitrary participant images need no project-specific files.
            xml = (ROOT/'user_data/ros2_custom_config_setup/cyclonedds_local.xml').read_text()
            environment = {'ROS_DOMAIN_ID': str(domain), 'RMW_IMPLEMENTATION': 'rmw_cyclonedds_cpp',
                           'CYCLONEDDS_URI': xml, 'ROS_LOCALHOST_ONLY': '0', 'GO1_DDS_LOCAL': '0',
                           'GUI': 'false'}
            for key in ('ODOM_SOURCE', 'NAV_MODE'):
                if key in os.environ:
                    environment[key] = os.environ[key]
            options = ['--network', 'host']
            if self.args.gpus:
                options += ['--gpus', self.args.gpus]
            for mount in self.args.mount:
                options += ['--mount', mount]
            self.runtime = ParticipantRuntime(ContainerSpec(self.args.participant_image, self.part,
                                               (self.args.task,), environment=environment, docker_args=tuple(options)))
            try:
                self.runtime.create()
                self.check_stop()
                self.runtime.start()
            except subprocess.CalledProcessError as error:
                detail = error.stderr or error.stdout or str(error)
                hint = ' Check NVIDIA driver and Docker GPU runtime (--gpus was requested).' if self.args.gpus else ''
                raise RuntimeError(f'Participant create/start failed: {detail}{hint}') from error
        self.check_stop()
        if self.args.logs:
            for name in ([self.sim] if self.args.sim_only else [self.sim, self.part]):
                self.logs.append(subprocess.Popen(['docker', 'logs', '-f', name]))
        print(('Simulator started' if self.args.sim_only else 'Pair started') + '; Ctrl+C to stop. Logs: docker logs -f CONTAINER', flush=True)
        while True:
            self.check_stop()
            states = [(self.sim, self.sim_inspect()['State'])]
            if self.runtime:
                states.append((self.part, self.runtime.state()))
            for name, state in states:
                if not state['Running']:
                    docker('logs', '--tail', '40', name)
                    raise RuntimeError(f'{name} exited unexpectedly (exit {state["ExitCode"]})')
            time.sleep(.3)

    def cleanup(self):
        errors = []
        for child in self.logs:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        # Names alone are insufficient: both paths verify run ownership first.
        if self.runtime:
            try:
                self.runtime.inspect()
            except subprocess.CalledProcessError:
                pass  # docker create failed before a container existed
            except Exception as error:
                errors.append(str(error))
            else:
                try:
                    self.runtime.stop()
                except Exception as error:
                    errors.append(str(error))
                try:
                    self.runtime.remove()
                except Exception as error:
                    errors.append(str(error))
        try:
            data = self.sim_inspect()
        except subprocess.CalledProcessError:
            data = None
        except Exception as error:
            data = None
            errors.append(str(error))
        if data:
            try:
                if data['State']['Running']:
                    docker('stop', '--time', '5', data['Id'], capture_output=True)
            except Exception as error:
                errors.append(str(error))
            finally:
                try:
                    docker('rm', '-f', data['Id'], capture_output=True)
                except Exception as error:
                    errors.append(str(error))
        if self.domain_lock:
            self.domain_lock.close()
        if errors:
            raise RuntimeError('Cleanup errors: ' + '; '.join(errors))


def positive(value):
    number = float(value)
    if not 0 < number < float('inf'):
        raise argparse.ArgumentTypeError('must be a positive finite number')
    return number


def bind_mount(value):
    fields = dict(item.split('=', 1) if '=' in item else (item, '') for item in value.split(','))
    if fields.get('type') != 'bind' or not (fields.get('src') or fields.get('source')) or not (fields.get('dst') or fields.get('target') or fields.get('destination')):
        raise argparse.ArgumentTypeError('use --mount type=bind,src=/host/path,dst=/container/path[,readonly]')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', choices=['T2', 'T3', 'T4', 'T5'], required=True)
    parser.add_argument('--sim-only', action='store_true', help='run only Simulator; Participant options are ignored')
    parser.add_argument('--participant-image', default=os.getenv('PARTICIPANT_IMAGE', 'go1-participant:example'))
    parser.add_argument('--sim-image', default=os.getenv('SIM_IMAGE', 'go1-sim:public'))
    gui = parser.add_mutually_exclusive_group()
    gui.add_argument('--headless', action='store_true', help='default; no Simulator display/devices')
    gui.add_argument('--gui', action='store_true', help='Simulator GUI; needs X11/DRI')
    parser.add_argument('--course-width', choices=['1.0', '2.0'], default='1.0')
    parser.add_argument('--domain', type=int, choices=range(1, 233), metavar='1..232')
    parser.add_argument('--timeout', type=positive, default=90, help='Simulator readiness seconds')
    parser.add_argument('--logs', action='store_true')
    parser.add_argument('--gpus', help='Participant Docker GPU request, e.g. all; opt-in only')
    parser.add_argument('--mount', action='append', type=bind_mount, default=[], help='explicit Participant bind mount (repeatable)')
    run = LocalRun(parser.parse_args())
    previous = {}
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        previous[signum] = signal.signal(signum, lambda sig, frame: setattr(run, 'signal', sig))
    code = 0
    try:
        run.start()
    except StopRequested:
        code = 128 + run.signal
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        if run.signal:
            code = 128 + run.signal
        else:
            print(f'LOCAL error: {error}', file=sys.stderr, flush=True)
            code = 1
    finally:
        try:
            run.cleanup()
        except Exception as error:
            print(f'LOCAL cleanup error: {error}', file=sys.stderr)
            code = 1
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        print(f'Cleaned {run.token} (exit {code})', flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
