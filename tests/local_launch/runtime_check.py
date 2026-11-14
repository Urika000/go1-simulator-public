#!/usr/bin/env python3
"""Exercise separate create/start and LOCAL bind mounts on the real Docker Engine."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from participant_runtime import ContainerSpec, ParticipantRuntime, docker

with tempfile.TemporaryDirectory(prefix='go1 explicit mount $() ') as directory:
    Path(directory, 'marker').write_text('explicit mount verified')
    runtime = ParticipantRuntime(ContainerSpec(
        os.environ.get('PARTICIPANT_IMAGE', 'go1-participant:example'), 'go1-local-runtime-'+uuid.uuid4().hex[:10], ('ping',),
        docker_args=('--network', 'none', '--mount', f'type=bind,src={directory},dst=/local-input,readonly')))
    try:
        cid = runtime.create()
        assert runtime.state()['Status'] == 'created'
        config = runtime.inspect()
        assert config['Mounts'][0]['Source'] == directory and not config['Mounts'][0]['RW']
        runtime.start()
        end = time.monotonic()+10
        while runtime.state()['Running']:
            assert time.monotonic() < end
            time.sleep(.1)
        assert runtime.state()['ExitCode'] == 0
        response = json.loads(docker('logs', cid, capture_output=True).stdout)
        assert set(response['supported_tasks']) == {'T2','T3','T4','T5'}
        print('create -> created -> start -> ping exit 0; explicit bind inspect PASS')
    finally:
        runtime.stop()
        runtime.remove()
