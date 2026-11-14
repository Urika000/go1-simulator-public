#!/usr/bin/env python3
"""Startup error, signal and log-stream checks; run after smoke.py, not concurrently."""
import os
import pathlib
import signal
import subprocess
import sys
import time

root = pathlib.Path(__file__).resolve().parents[2]
out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/go1-local-lifecycle')
out.mkdir(exist_ok=False)

def resources():
    return {kind: subprocess.check_output(['docker', *args], text=True).splitlines()
            for kind, args in [('containers', ['ps', '-aq']), ('networks', ['network', 'ls', '-q'])]}

before = resources()
for label, args, expected, interrupt, env in [
    ('invalid-cli', ['--task', 'T0'], 2, False, {}),
    ('missing-image', ['--task', 'T2'], 1, False, {'SIM_IMAGE': 'go1-local-missing-image:nonexistent'}),
    ('bad-participant', ['--task', 'T2', '--participant-image', os.environ.get('SIM_IMAGE', 'go1-sim:public')], 1, False, {}),
    ('timeout', ['--task', 'T4', '--headless', '--timeout', '1'], 1, False, {}),
    ('startup-interrupt', ['--task', 'T4', '--headless'], 130, True, {}),
    ('logs', ['--task', 'T2', '--headless', '--logs'], 130, True, {}),
]:
    path = out / (label+'.log')
    with path.open('w') as log:
        start = time.monotonic()
        p = subprocess.Popen([sys.executable, str(root/'run_local.py'), *args], cwd=root, stdout=log,
                             stderr=subprocess.STDOUT, start_new_session=True, env={**os.environ, **env})
        try:
            if interrupt:
                needle = 'Pair started' if label == 'logs' else ' Created '
                while needle not in path.read_text():
                    assert p.poll() is None, path.read_text()
                    assert time.monotonic()-start < 40, path.read_text()
                    time.sleep(.1)
                if label == 'logs':
                    time.sleep(2)
                    assert '[go1_mujoco.py' in path.read_text(), path.read_text()
                os.killpg(p.pid, signal.SIGINT)
            rc = p.wait(timeout=30)
            assert rc == expected, (label, rc, path.read_text())
            assert resources() == before, (label, resources(), before)
            print(label, 'PASS', 'exit', rc, 'elapsed', round(time.monotonic()-start,1), flush=True)
        finally:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=25)
# Reservation must refuse a second launcher without starting a container.
import fcntl
lock = pathlib.Path('/tmp/go1-local-domains/151.lock')
with lock.open('w') as f:
    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    r = subprocess.run([sys.executable, str(root/'run_local.py'), '--task', 'T2', '--domain', '151'],
                       cwd=root, capture_output=True, text=True, timeout=15)
    assert r.returncode == 1 and 'reserved' in r.stderr, (r.returncode, r.stderr)
    assert resources() == before
    (out/'domain-lock.log').write_text(r.stdout+r.stderr)
    print('domain-lock PASS', flush=True)
# No GPU is required for any default launch. On a CPU-only host verify that an
# explicit unsupported request fails clearly and cleans the already-started sim.
if not pathlib.Path('/dev/nvidiactl').exists():
    r = subprocess.run([sys.executable, str(root/'run_local.py'), '--task', 'T2', '--gpus', 'all'],
                       cwd=root, capture_output=True, text=True, timeout=40)
    assert r.returncode == 1 and 'NVIDIA' in r.stderr, (r.returncode, r.stderr)
    assert resources() == before
    (out/'gpu-unavailable.log').write_text(r.stdout+r.stderr)
    print('gpu-unavailable error/cleanup PASS; real GPU NOT VERIFIED', flush=True)
