"""Service-manager operations used by the shared Pixel access transactions.

Platform adapters must prove stopped state independently of HTTP reachability.
Installation custody and access-mode isolation remain separate prerequisites.
"""
from pathlib import Path
import re


class SystemdGatewayService:
    def __init__(self, command, error, unit):
        self.command, self.error, self.unit = command, error, unit

    def pid(self, *, timeout=20, require_running=False):
        raw = self.command(['systemctl', 'show', self.unit, '--property=MainPID', '--value'], timeout=timeout)
        if not raw.isdecimal() or require_running and int(raw) <= 0:
            raise self.error('runtime-unavailable-or-busy')
        return int(raw)

    def assert_stopped(self):
        raw = self.command(['systemctl', 'show', self.unit, '--property=MainPID,ActiveState,ControlGroup'])
        fields = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
        if fields.get('MainPID') != '0' or fields.get('ActiveState') not in ('inactive', 'failed'):
            raise self.error('native-idle-unconfirmed')
        group = fields.get('ControlGroup', '')
        if group:
            root = Path('/sys/fs/cgroup')
            path = (root / group.lstrip('/')).resolve()
            if root not in path.parents:
                raise self.error('native-idle-unconfirmed')
            if path.exists() and (path / 'cgroup.procs').read_text().strip():
                raise self.error('native-idle-unconfirmed')

    def boundary(self):
        return self.command(['systemctl', 'show', self.unit,
            '--property=ProtectSystem,ProtectHome,NoNewPrivileges,CapabilityBoundingSet,BindReadOnlyPaths,ReadOnlyPaths,PrivateTmp'])

    def reload(self):
        self.command(['systemctl', 'daemon-reload'])

    def restart(self, *, timeout=60):
        self.command(['systemctl', 'restart', self.unit], timeout=timeout)


class LaunchdGatewayService:
    """Native lifecycle only; not authorization to enable host access modes.

    verify is a trusted deployment-custody check, called before every operation.
    Production uses a system job; GUI domains support isolated qualification.
    No request may supply target or the verifier.
    """
    def __init__(self, command, error, target, verify):
        if (not isinstance(target, str) or not re.fullmatch(
                r'(?:system|gui/[0-9]+)/[A-Za-z0-9][A-Za-z0-9.-]{0,127}', target)
                or not callable(verify)):
            raise error('invalid-launchd-service')
        self.command, self.error, self.target, self.verify = command, error, target, verify

    def installation_binding(self, filename, expected):
        """Require both protected plist bytes and the matching loaded job.

        expected is supplied by trusted installation metadata, never inferred
        from the user's current plist. This is not a process isolation proof.
        """
        from pixel_macos_custody import (CustodyError, launchd_document_binding,
                                         verify_loaded_launchd_definition)
        self.verify()
        try:
            binding = launchd_document_binding(filename, expected)
            raw = self.command(['/bin/launchctl', 'print', self.target])
            verify_loaded_launchd_definition(raw, self.target, filename, expected)
            if launchd_document_binding(filename, expected) != binding:
                raise CustodyError('launchd-document-changed')
        except CustodyError as exc:
            raise self.error(str(exc)) from None
        return binding

    def pid(self, *, timeout=20, require_running=False):
        self.verify()
        raw = self.command(['/bin/launchctl', 'print', self.target], timeout=timeout)
        # launchctl has no JSON status API. Match only its top-level fields;
        # nested resource groups also have a state and are not the gateway.
        lines = raw.splitlines()
        if not lines or not lines[0].startswith(self.target + ' = {'):
            raise self.error('gateway-process-mismatch')
        states = re.findall(r'^\tstate = ([^\n]+)$', raw, re.MULTILINE)
        pids = re.findall(r'^\tpid = ([^\n]+)$', raw, re.MULTILINE)
        if len(states) != 1 or len(pids) > 1 or pids and not pids[0].isdecimal():
            raise self.error('gateway-process-mismatch')
        pid = int(pids[0]) if pids else 0
        if states[0] == 'running' and pid > 0:
            return pid
        if not require_running and states[0] in ('not running', 'waiting', 'spawn scheduled') and pid == 0:
            return 0
        raise self.error('runtime-unavailable-or-busy')

    def restart(self, *, timeout=60):
        self.verify()
        self.command(['/bin/launchctl', 'kickstart', '-k', self.target], timeout=timeout)

    def assert_stopped(self):
        # Unlike a cgroup, a launchd PID alone cannot prove no descendants live.
        raise self.error('native-idle-unconfirmed')

    def boundary(self):
        raise self.error('macos-isolation-adapter-missing')

    def reload(self):
        # A changed plist needs an explicit bootout/bootstrap transaction,
        # not kickstart, which retains the already-loaded service definition.
        raise self.error('launchd-reload-requires-bootstrap')
