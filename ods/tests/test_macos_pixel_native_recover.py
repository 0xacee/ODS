"""Recovery publishes readiness only after protected and consumer readback."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.request  # noqa: F401 - initialize before emulating Darwin

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('native_recover',
    ROOT / 'installers/macos/lib/pixel-native-recover.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.fixture
def retained(tmp_path, monkeypatch):
    monkeypatch.setattr(module.sys, 'platform', 'darwin')
    monkeypatch.setattr(module.os, 'geteuid', lambda: 501)
    preparation = tmp_path / 'data/pixel-native/preparation'
    preparation.mkdir(mode=0o700, parents=True)
    receipt = dict(schemaVersion=1, status='prepared', phase='awaiting-protected-activation',
        requiresActivation=True, runtimeDigest='a' * 64, serviceDigest='b' * 64, pixelSourceRef='c' * 40,
        home=str(tmp_path / 'data/pixel-native/home'))
    activation = dict(schemaVersion=1, status='error', phase='final-health', requiresRecovery=True,
        runtimeDigest=receipt['runtimeDigest'], serviceDigest=receipt['serviceDigest'])
    for name, value in (('preparation.json', receipt), ('activation.json', activation)):
        path = preparation / name
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    # Use the real bounded owner/private-file reader while exercising real
    # flock, fsync and atomic publication on the platform running this test.
    config = module.helper('pixel-native-config')
    monkeypatch.setattr(module, 'helper', lambda name: config)
    return preparation, receipt, activation


@pytest.mark.parametrize('fault', [None, 'proof', 'reproof', 'health', 'client', 'route',
    'changed', 'foreign-selection', 'legacy-host', 'lock-link'])
def test_recovery_preserves_failed_attempt_and_never_reactivates(retained, monkeypatch, tmp_path, fault):
    preparation, receipt, activation = retained
    originals = {name: (preparation / name).read_bytes() for name in ('preparation.json', 'activation.json')}
    destination = preparation / 'selection-update.json'
    if fault == 'foreign-selection':
        destination.write_text(json.dumps({'another': 'transaction'}))
        destination.chmod(0o600)
    if fault == 'lock-link':
        target = tmp_path / 'unchanged-lock-target'
        target.write_text('private')
        (preparation / '.selection.lock').symlink_to(target)
    events = []
    proof_count = 0
    def prove():
        nonlocal proof_count
        events.append('proof')
        proof_count += 1
        if fault == 'changed':
            (preparation / 'activation.json').write_text(json.dumps(dict(activation, phase='protected-activation')))
        return dict(status='unknown' if fault == 'proof' or fault == 'reproof' and proof_count == 2 else 'active',
                    runtimeDigest=receipt['runtimeDigest'], serviceDigest=receipt['serviceDigest'])
    def health(run):
        events.append('health')
        if fault == 'health': raise ValueError('native-compose-health-timeout')
    def run(*args, **kwargs):
        events.append(args[0])
        if args[0] == 'up':
            assert args == ('up', '-d', '--no-deps', '--wait', '--wait-timeout', '120', 'dashboard-api', 'open-webui')
            return SimpleNamespace(returncode=int(fault == 'client'))
        assert args[:5] == ('exec', '-T', 'dashboard-api', 'python3', '-c')
        assert 'http://pixel-edge:9595/health' in args[5]
        return SimpleNamespace(returncode=int(fault == 'route'))
    services = {'dashboard-api': {}, 'open-webui': {}}
    if fault == 'legacy-host': services['dashboard-api']['extra_hosts'] = {'pixel-edge': 'host-gateway'}
    def finish():
        return module.finish(preparation=preparation, receipt=receipt, run=run, verify=prove,
            compose=SimpleNamespace(wait_ready=health), selected_services=services)
    if fault:
        with pytest.raises((ValueError, OSError)):
            finish()
        if fault == 'foreign-selection':
            assert json.loads(destination.read_text()) == {'another': 'transaction'}
        else:
            assert not destination.exists()
        if fault in ('proof', 'foreign-selection', 'lock-link'):
            assert 'up' not in events
    else:
        assert finish() == destination
        assert events == ['proof', 'health', 'up', 'exec', 'health', 'proof']
        selected = json.loads(destination.read_text())
        assert selected['activation'] == dict(activation, status='ready', phase='services-ready', requiresRecovery=False)
        assert selected['preparation'] == receipt
        assert destination.stat().st_mode & 0o777 == 0o600
        stack_spec = importlib.util.spec_from_file_location('recovered_stack',
            ROOT / 'installers/macos/lib/pixel-native-stack.py')
        stack = importlib.util.module_from_spec(stack_spec)
        stack_spec.loader.exec_module(stack)
        for relative in stack.installer.FRAGMENTS:
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        assert stack.read_selection(preparation) == (receipt, selected['activation'])
        assert stack.resolve_files(tmp_path, ['docker-compose.yml']) == [
            'docker-compose.yml', *stack.installer.FRAGMENTS]
        # An interrupted caller can explicitly replay; no gateway or protected
        # service start/stop/install operation is available to this coordinator.
        assert finish() == destination
    for name, value in originals.items():
        if fault == 'changed' and name == 'activation.json': continue
        assert (preparation / name).read_bytes() == value


@pytest.mark.parametrize('field,value', [('phase', 'protected-activation'), ('phase', 'infrastructure'),
    ('status', 'activating'), ('requiresRecovery', False), ('runtimeDigest', 'd' * 64), ('schemaVersion', True)])
def test_only_matching_late_initial_failures_can_resume(retained, field, value):
    _, receipt, activation = retained
    with pytest.raises(ValueError):
        module.selection(receipt, dict(activation, **{field: value}))
    with pytest.raises(ValueError):
        module.selection(dict(receipt, kind='legacy-native'), activation)


def test_recovery_rejects_root_before_reading_or_running(monkeypatch):
    monkeypatch.setattr(module.sys, 'platform', 'darwin')
    monkeypatch.setattr(module.os, 'geteuid', lambda: 0)
    with pytest.raises(ValueError, match='owner-required'):
        module.recover('/does-not-exist', '/does-not-exist')


def test_recovery_refuses_concurrent_publication(retained):
    preparation, receipt, _ = retained
    import fcntl
    with (preparation / '.selection.lock').open('w') as lock:
        (preparation / '.selection.lock').chmod(0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            module.finish(preparation=preparation, receipt=receipt, run=None,
                verify=None, compose=None, selected_services={})
    assert not (preparation / 'selection-update.json').exists()
