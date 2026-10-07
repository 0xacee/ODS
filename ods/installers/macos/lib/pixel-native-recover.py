"""Finish a retained initial Pixel installation after final Docker health failure.

This verifies the completed protected activation twice; it never repeats it.
The original preparation and activation receipts remain untouched. A successful
readback publishes the existing atomic owner-selection format, after consumers
have been checked against the native stack.
"""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
GUIDANCE = {
    'native-macos-owner-required': 'Run as the signed-in macOS owner; the proof requests sudo itself.',
    'retained-final-health-failure-required': 'Only an initial installation stopped after protected activation can use this recovery.',
    'retained-native-selection-mismatch': 'The preparation and activation identities disagree.',
    'native-recovery-selection-changed': 'The retained selection changed or a different update was published.',
    'native-initial-recovery-proof-failed': 'Protected activation could not be verified. The failed attempt remains intact.',
    'native-recovery-client-routing-failed': 'The native Dashboard/Portal route is not ready.',
    'native-client-has-legacy-edge-route': 'The selected client configuration still routes to a legacy Pixel Edge.',
    'native-recovery-host-agent-failed': 'Host-agent setup did not pass. Inspect the private continuation-host-agent.log; do not reinstall.',
}


def helper(name):
    spec = importlib.util.spec_from_file_location('native_recover_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def selection(receipt, activation):
    if (type(receipt) is not dict or type(activation) is not dict
            or receipt.get('kind') == 'legacy-native'
            or receipt.get('status') != 'prepared' or receipt.get('requiresActivation') is not True
            or receipt.get('phase') != 'awaiting-protected-activation'
            or activation.get('status') != 'error' or activation.get('requiresRecovery') is not True
            or activation.get('phase') not in ('final-health', 'webui-routing')
            or type(activation.get('schemaVersion')) is not int or activation['schemaVersion'] != 1
            or not re.fullmatch('[a-f0-9]{40}', str(receipt.get('pixelSourceRef', '')))):
        raise ValueError('retained-final-health-failure-required')
    for key in ('runtimeDigest', 'serviceDigest'):
        if (not re.fullmatch('[a-f0-9]{64}', str(receipt.get(key, '')))
                or activation.get(key) != receipt[key]):
            raise ValueError('retained-native-selection-mismatch')
    return {'schemaVersion': 1, 'preparation': receipt,
            'activation': dict(activation, status='ready', phase='services-ready', requiresRecovery=False)}


def finish(*, preparation, receipt, run, verify, compose, selected_services, restore_host_agent=None):
    if sys.platform != 'darwin' or os.geteuid() == 0:
        raise ValueError('native-macos-owner-required')
    config = helper('pixel-native-config')
    preparation = Path(preparation)
    info = preparation.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
            or preparation.resolve(strict=True) != preparation):
        raise ValueError('private-native-preparation-required')
    lock = os.open(preparation / '.selection.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(lock)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise ValueError('private-native-selection-lock-required')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original = config.private_json(preparation / 'activation.json')
        document = selection(receipt, original)
        body = (json.dumps(document, sort_keys=True) + '\n').encode()
        if len(body) > 2 * 1024 * 1024:
            raise ValueError('native-recovery-selection-too-large')
        destination = preparation / 'selection-update.json'
        def unchanged():
            if (config.private_json(preparation / 'preparation.json') != receipt
                    or config.private_json(preparation / 'activation.json') != original
                    or os.path.lexists(destination) and config.private_json(destination) != document):
                raise ValueError('native-recovery-selection-changed')
        def prove():
            unchanged()
            expected = {'status': 'active', **{key: receipt[key] for key in ('runtimeDigest', 'serviceDigest')}}
            if verify() != expected:
                raise ValueError('native-initial-recovery-proof-failed')
            unchanged()
        prove()
        compose.wait_ready(run)
        clients = ['dashboard-api']
        if 'open-webui' in selected_services:
            clients.append('open-webui')
        # A stale override can leave healthy clients talking to a legacy Edge.
        for name in clients:
            definition = selected_services.get(name)
            if type(definition) is not dict:
                raise ValueError('native-client-service-missing')
            hosts = definition.get('extra_hosts', {})
            if type(hosts) not in (dict, list) or any(
                    str(host).split('=', 1)[0].split(':', 1)[0].lower().rstrip('.') == 'pixel-edge'
                    for host in hosts):
                raise ValueError('native-client-has-legacy-edge-route')
        if run('up', '-d', '--no-deps', '--wait', '--wait-timeout', '120', *clients, timeout=180).returncode:
            raise ValueError('native-recovery-client-routing-failed')
        probe = ('import urllib.request; '
            'r=urllib.request.build_opener(urllib.request.ProxyHandler({})).open('
            '"http://pixel-edge:9595/health",timeout=15); '
            'raise SystemExit(0 if r.status==200 else 1)')
        if run('exec', '-T', 'dashboard-api', 'python3', '-c', probe, timeout=30).returncode:
            raise ValueError('native-recovery-client-routing-failed')
        compose.wait_ready(run)
        if restore_host_agent is not None:
            unchanged()
            restore_host_agent()
        prove()
        # Publish only after routing and protected readback succeed. An earlier
        # interruption retains the error receipt and is safe to retry explicitly.
        with tempfile.TemporaryDirectory(prefix='.recovery-', dir=preparation) as temporary:
            staged = Path(temporary) / 'selection.json'
            with staged.open('xb') as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            unchanged()
            os.replace(staged, destination)
            directory_fd = os.open(preparation, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return destination
    finally:
        os.close(lock)


def recover(install_dir, ods_source, *, restore_host_agent=False):
    if sys.platform != 'darwin' or os.geteuid() == 0:
        raise ValueError('native-macos-owner-required')
    install_dir = Path(install_dir).expanduser().resolve(strict=True)
    preparation = install_dir / 'data/pixel-native/preparation'
    config = helper('pixel-native-config')
    selection(config.private_json(preparation / 'preparation.json'),
              config.private_json(preparation / 'activation.json'))
    tokens = helper('pixel-native-finalize').compose_flags(install_dir, dict(os.environ))
    fragments = [install_dir / path for path in helper('pixel-native-install').FRAGMENTS]
    files = []
    for value in tokens[1::2]:
        path = (install_dir / value).resolve(strict=True)
        if install_dir not in path.parents:
            raise ValueError('installed-compose-file-required')
        if path not in fragments:
            files.append(path)
    return helper('pixel-native-activate').activate(preparation=preparation, install_dir=install_dir,
        ods_source=Path(ods_source).resolve(strict=True), compose_files=[*files, *fragments],
        resume_final_health=True, **({'restore_host_agent': True} if restore_host_agent else {}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-dir', required=True)
    parser.add_argument('--ods-source', default=str(HERE.parents[2]))
    parser.add_argument('--restore-host-agent', action='store_true',
        help='Also install the login host agent and verify its authenticated Dashboard route; not a full installer continuation')
    args = parser.parse_args()
    try:
        path = recover(args.install_dir, args.ods_source,
            **({'restore_host_agent': True} if args.restore_host_agent else {}))
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        detail = helper('pixel-native-compose').health_diagnostic(error)
        code = str(error) if isinstance(error, ValueError) else None
        if code in GUIDANCE:
            detail = '[' + code + '] ' + GUIDANCE[code]
        print('Native Pixel recovery stopped. Keep the original receipts and services intact.'
              + (' ' + detail if detail else ''), file=sys.stderr)
        return 1
    result = {'status': 'native-pixel-ready', 'selection': str(path), 'installerComplete': False}
    if args.restore_host_agent:
        result['hostAgentReady'] = True
    print(json.dumps(result))
    remaining = 'optional tools and full-model download' if args.restore_host_agent else 'host agent, optional tools and full-model download'
    print('Pixel recovery completed. Remaining installer steps (' + remaining
          + ') still need verification before declaring ODS installed.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
