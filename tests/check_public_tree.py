#!/usr/bin/env python3
"""Check the public Git index/history and Docker COPY inputs; no external repo."""
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]

def git(*args):
    return subprocess.check_output(['git', '-C', str(root), *args])

git('rev-parse', '--verify', 'HEAD')
paths = git('ls-files', '-z').decode().split('\0')
for name in filter(None, paths):
    assert not any(part.startswith('judge') for part in Path(name).parts), name
    assert not name.startswith(('reports/', 't3_existing/', '.dependency-cache/')), name
    assert not (root/name).is_symlink(), name
# Every reachable blob is checked, including deleted files in future history.
count = 0
for line in git('rev-list', '--objects', '--all').decode().splitlines():
    oid, _, name = line.partition(' ')
    assert not any(part.startswith('judge') for part in Path(name).parts), name
    if git('cat-file', '-t', oid).strip() != b'blob':
        continue
    data = git('cat-file', 'blob', oid)
    for forbidden in (b'GO1_PRIVATE_GT_SOCKET', b'GO1_GAZEBO_PRIVATE_GT_SOCKET',
                      b'go1-private-gt-v1', b'/home/go1dev/', b'BEGIN PRIVATE KEY',
                      b'ghp_', b'github_pat_'):
        # This scanner contains the signatures, not a secret or implementation.
        if line.endswith(' tests/check_public_tree.py'):
            continue
        assert forbidden not in data, (line, forbidden)
    count += 1
for line in (root/'Dockerfile').read_text().splitlines():
    if not line.startswith('COPY '):
        continue
    parts = [p for p in line.split()[1:] if not p.startswith('--')]
    for source in parts[:-1]:
        assert (root/source).exists(), source
print(f'PASS: public index, {count} history blobs, Docker COPY inputs')
