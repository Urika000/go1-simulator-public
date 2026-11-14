#!/usr/bin/env python3
"""Run image-only T4 from a minimal launcher bundle without Participant sources."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='go1-portable-') as directory:
    bundle = Path(directory)
    for filename in ('run_local.py', 'participant_runtime.py', 'docker-compose.yml', 'docker-compose.headless.yml'):
        shutil.copy2(root/filename, bundle/filename)
    xml = Path('user_data/ros2_custom_config_setup/cyclonedds_local.xml')
    (bundle/xml).parent.mkdir(parents=True)
    shutil.copy2(root/xml, bundle/xml)
    assert not (bundle/'t3_existing').exists()
    data = bundle/'explicit input $()'
    data.mkdir()
    (data/'marker').write_text('image-only Participant')
    with (bundle/'launch.log').open('w') as log:
        process = subprocess.Popen([sys.executable, str(bundle/'run_local.py'), '--sim-image', os.environ.get('SIM_IMAGE', 'go1-sim:public'), '--task', 'T4',
                                    '--participant-image', os.environ.get('PARTICIPANT_IMAGE', 'go1-participant:example'), '--headless',
                                    '--mount', f'type=bind,src={data},dst=/local-input,readonly'],
                                   cwd=bundle, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+100
            while 'Pair started' not in (bundle/'launch.log').read_text():
                assert process.poll() is None, (bundle/'launch.log').read_text()
                assert time.monotonic()<deadline
                time.sleep(.2)
            lines = (bundle/'launch.log').read_text().splitlines()
            sim = next(l.split('=',1)[1] for l in lines if l.startswith('Simulator='))
            part = next(l.split('=',1)[1] for l in lines if l.startswith('Participant='))
            marker = subprocess.check_output(['docker', 'exec', part, 'cat', '/local-input/marker'], text=True)
            assert marker == 'image-only Participant'
            inspect = json.loads(subprocess.check_output(['docker','inspect',part]))[0]
            assert len(inspect['Mounts']) == 1 and not inspect['Mounts'][0]['RW']
            probe = (root/'tests/local_launch/probe.py').read_text()
            r = subprocess.run(['docker','exec','-i',sim,'bash','-c',
                                'source /etc/go1_sim_env.sh; exec python3 - --topics /cmd_vel=geometry_msgs/msg/Twist --seconds 4'],
                               input=probe, text=True, capture_output=True, timeout=15)
            assert r.returncode == 0, (r.stdout,r.stderr)
            print('Portable T4, explicit image, no Participant sources/Compose, explicit bind, reverse DDS PASS', r.stdout.strip(), flush=True)
            process.send_signal(signal.SIGTERM)
            assert process.wait(timeout=25) == 143
            remaining = subprocess.check_output(['docker','ps','-a','--format','{{.Names}}'], text=True).splitlines()
            assert sim not in remaining and part not in remaining
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=25)
