#!/usr/bin/env python3
"""Bounded real two-container smoke. Run from repository root; existing images only."""
import concurrent.futures
import json
import pathlib
import signal
import subprocess
import time
import sys
import os

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROBE = (ROOT / 'tests/local_launch/probe.py').read_text()
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/go1-local-verification')
OUT.mkdir(exist_ok=False)

def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()

def probe(name, participant, args):
    setup = ('source /opt/ros/humble/setup.bash; if [ -f /etc/go1_sim_env.sh ]; then source /etc/go1_sim_env.sh; else source /opt/go1_participant/ros2_ws/install/setup.bash; fi'
             if participant else 'source /etc/go1_sim_env.sh')
    r = subprocess.run(['docker', 'exec', '-i', name, 'bash', '-c', setup + '; exec python3 - ' + args],
                       input=PROBE, capture_output=True, text=True, timeout=45)
    assert r.returncode == 0, (name, r.stdout, r.stderr)
    return json.loads(r.stdout)

results = []
cases = [('T2','1.0','interrupt'), ('T3','1.0','participant'),
                           ('T4','1.0','simulator'), ('T5','1.0','terminate'),
                           ('T5','2.0','interrupt'), ('T2','1.0','interrupt')]
if os.environ.get('SMOKE_CASE'):
    cases = [case for case in cases if f'{case[0]}-{case[1]}'.startswith(os.environ['SMOKE_CASE'])]
    assert cases, 'Unknown SMOKE_CASE'
for task, width, stop in cases:
    label = f'{task}-{width}-{len(results)}'
    path = OUT / (label + '.log')
    with path.open('w') as log:
        p = subprocess.Popen([sys.executable, str(ROOT/'run_local.py'), '--sim-image', os.environ.get('SIM_IMAGE', 'go1-sim:public'), '--task', task, '--headless', '--course-width', width, '--participant-image', os.environ.get('PARTICIPANT_IMAGE', 'go1-participant:example')],
                             stdout=log, stderr=subprocess.STDOUT, cwd=OUT)
        names = []
        try:
            deadline = time.monotonic() + 110
            while 'Pair started' not in path.read_text():
                assert p.poll() is None, path.read_text()
                assert time.monotonic() < deadline, path.read_text()
                time.sleep(0.3)
            lines = path.read_text().splitlines()
            sim = next(l.split('=',1)[1] for l in lines if l.startswith('Simulator='))
            part = next(l.split('=',1)[1] for l in lines if l.startswith('Participant='))
            names = [sim, part]
            running = docker('ps','--format','{{.Names}}').splitlines()
            own = [n for n in running if n.startswith(sim[:-3])]
            assert sorted(own) == sorted(names), running
            sim_inspection = json.loads(docker('inspect', sim))[0]
            sim_host = sim_inspection['HostConfig']
            assert sim_host['NanoCpus'] == sim_host['CpuQuota'] == sim_host['Memory'] == 0
            assert sim_host['PidsLimit'] in (0, None)
            assert sim_inspection['Config']['User'] == json.loads(docker('image', 'inspect', sim_inspection['Image']))[0]['Config']['User']
            assert not sim_inspection['Mounts'], sim_inspection['Mounts']
            (OUT/(label+'-sim-inspect.json')).write_text(json.dumps(sim_inspection, indent=2))
            inspection = json.loads(docker('inspect', part))[0]
            image = json.loads(docker('image', 'inspect', inspection['Image']))[0]
            host = inspection['HostConfig']
            assert host['NanoCpus'] == host['CpuQuota'] == host['Memory'] == 0, host
            assert host['PidsLimit'] in (0, None), host
            assert not host['ReadonlyRootfs'] and not host['Privileged'], host
            assert not host['CapAdd'] and not host['CapDrop'] and not host['SecurityOpt'], host
            assert not host['DeviceRequests'] and not inspection['Mounts'], host
            assert inspection['Config']['User'] == image['Config']['User']
            assert inspection['Path'] == '/entrypoint.sh' and inspection['Args'] == [task]
            (OUT/(label+'-inspect.json')).write_text(json.dumps(inspection, indent=2))
            if task in ('T4', 'T5'):
                processes = docker('exec', sim, 'pgrep', '-af', 'gzserver')
                assert '--lockstep' in processes, processes
                (OUT/(label+'-gazebo.txt')).write_text(processes)
            time.sleep(5)
            low = task in ('T2','T3')
            forward = ('--topics /lowstate=unitree_go/msg/LowState' if low else
                       '--topics /scan=sensor_msgs/msg/LaserScan /imu/data=sensor_msgs/msg/Imu')
            # T2 has no Judge source: zero LowCmd fixture feeds the unchanged Safety.
            if os.environ.get('INTERFACE_ONLY', '1') == '1':
                if low: forward += ' --publish /lowcmd=unitree_go/msg/LowCmd'
            elif task == 'T2':
                forward += ' --publish /lowcmd_bare=unitree_go/msg/LowCmd'
            reverse = ('--topics /lowcmd=unitree_go/msg/LowCmd' if low else
                       ('--topics /cmd_vel=geometry_msgs/msg/Twist' if os.environ.get('INTERFACE_ONLY', '1') == '1' else '--topics /odom=nav_msgs/msg/Odometry /cmd_vel=geometry_msgs/msg/Twist'))
            if not low:
                forward += ' --publish /cmd_vel=geometry_msgs/msg/Twist'
                cameras = ['camera'] if task == 'T4' else ['camera', 'camera_chin', 'camera_left', 'camera_right', 'camera_rearDown']
                # Insert camera topics before --publish.
                forward = forward.replace(' --publish', ''.join(' /'+c+'/image_raw=sensor_msgs/msg/Image /'+c+'/depth/image_raw=sensor_msgs/msg/Image' for c in cameras)+' --publish')
            with concurrent.futures.ThreadPoolExecutor() as pool:
                a = pool.submit(probe, part, True, forward + ' --seconds 20')
                b = pool.submit(probe, sim, False, reverse + ' --seconds 20')
                counts = {'participant': a.result(), 'simulator': b.result()}
            (OUT/(label+'-sim.log')).write_text(docker('logs',sim))
            (OUT/(label+'-participant.log')).write_text(docker('logs',part))
            if stop in ('simulator','participant'):
                docker('kill', sim if stop == 'simulator' else part)
                expected = 1
            else:
                p.send_signal(signal.SIGINT if stop == 'interrupt' else signal.SIGTERM)
                expected = 130 if stop == 'interrupt' else 143
            rc = p.wait(timeout=25)
            assert rc == expected, (rc, path.read_text())
            remaining = docker('ps','-a','--format','{{.Names}}').splitlines()
            assert not set(names) & set(remaining), remaining
            assert not any(sim[:-3] in n for n in docker('network','ls','--format','{{.Name}}').splitlines())
            result = dict(task=task, width=width, stop=stop, exit=rc, containers=2, payloads=counts, cleanup=True)
            results.append(result)
            (OUT/'results.json').write_text(json.dumps(results, indent=2))
            print(json.dumps(result), flush=True)
        finally:
            if p.poll() is None:
                for name in names:
                    saved = subprocess.run(['docker', 'logs', name], text=True, capture_output=True)
                    (OUT/(label+'-'+name.rsplit('-',1)[-1]+'-cleanup.log')).write_text(saved.stdout+saved.stderr)
            if p.poll() is None:
                p.terminate()
                try: p.wait(timeout=25)
                except subprocess.TimeoutExpired: p.kill(); p.wait()
