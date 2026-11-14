"""Small Docker CLI container primitive. No Simulator or LOCAL/OFFICIAL policy.

Call create(), apply any caller-owned policy, then start(). docker_args are an
argv sequence for trusted callers, never a shell command. Cleanup verifies an
ownership label, including recovery after an interrupted docker create.
"""
from dataclasses import dataclass, field
import json
import subprocess
import uuid


def docker(*args, timeout=30, **kwargs):
    return subprocess.run(['docker', *args], check=True, text=True, timeout=timeout, **kwargs)


@dataclass
class ContainerSpec:
    image: str
    name: str
    command: tuple[str, ...]
    entrypoint: str = '/entrypoint.sh'
    environment: dict[str, str] = field(default_factory=dict)
    docker_args: tuple[str, ...] = ()
    platform: str = 'linux/amd64'


class ParticipantRuntime:
    def __init__(self, spec: ContainerSpec):
        self.spec = spec
        self.container_id = None
        self.token = uuid.uuid4().hex

    def create(self):
        if self.container_id:
            raise RuntimeError('Container already created')
        args = ['create', '--name', self.spec.name, '--platform', self.spec.platform,
                '--pull', 'never', '--label', 'go1.participant.owner=' + self.token]
        args.extend(self.spec.docker_args)
        for key, value in self.spec.environment.items():
            args.extend(['--env', f'{key}={value}'])
        args.extend(['--entrypoint', self.spec.entrypoint, self.spec.image, *self.spec.command])
        self.container_id = docker(*args, capture_output=True).stdout.strip()
        return self.container_id

    def inspect(self):
        data = json.loads(docker('inspect', self.container_id or self.spec.name,
                                 capture_output=True).stdout)[0]
        if (data['Config'].get('Labels') or {}).get('go1.participant.owner') != self.token:
            raise RuntimeError('Refusing to operate on a container owned by another run')
        return data

    def state(self):
        """Docker State includes Running, Status, ExitCode and Error."""
        return self.inspect()['State']

    def start(self):
        self.inspect()
        docker('start', self.container_id, capture_output=True)

    def stop(self, seconds=5):
        data = self.inspect()
        if data['State']['Running']:
            docker('stop', '--time', str(seconds), data['Id'], capture_output=True)

    def remove(self):
        data = self.inspect()
        docker('rm', '-f', data['Id'], capture_output=True)
        self.container_id = None
