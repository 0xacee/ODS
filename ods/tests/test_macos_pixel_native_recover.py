"""Recovery publishes readiness only after protected and consumer readback."""
import importlib.util
import json
import os
import plistlib
from pathlib import Path
import subprocess
import shlex
import sys
from types import SimpleNamespace
import urllib.request  # noqa: F401 - initialize before emulating Darwin

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('native_recover',
    ROOT / 'installers/macos/lib/pixel-native-recover.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
continuation = module.helper('pixel-native-continuation')


@pytest.fixture
def recommended_model():
    bootstrap = dict(bootstrap_file='starter.gguf', bootstrap_model='starter', bootstrap_context=65536)
    saved = dict(ODS_MODE='local', GPU_BACKEND='apple', LLM_BACKEND='llama-server',
        GGUF_FILE='starter.gguf', LLM_MODEL='starter', MAX_CONTEXT='65536', CTX_SIZE='65536',
        MODEL_RECOMMENDED_GGUF='chosen.gguf', MODEL_RECOMMENDED_MODEL='chosen',
        MODEL_RECOMMENDED_CONTEXT='32768')
    record = dict(id='chosen-q4', llm_model_name='chosen', gguf_file='chosen.gguf',
        gguf_url='https://huggingface.co/org/model/resolve/' + 'a' * 40 + '/chosen.gguf',
        gguf_sha256='b' * 64, size_bytes=1000, context_length=32768, max_context_length=65536)
    return saved, dict(models=[record]), bootstrap


def test_continuation_reuses_recommendation_not_hardware(recommended_model):
    saved, catalog, bootstrap = recommended_model
    before = json.dumps([saved, catalog, bootstrap], sort_keys=True)
    plan = continuation.model_upgrade_plan(saved, catalog, **bootstrap)
    assert plan == dict(status='upgrade-required', modelId='chosen-q4',
        arguments=['chosen.gguf', catalog['models'][0]['gguf_url'], 'b' * 64,
                   'chosen', '32768', 'starter.gguf'])
    assert json.dumps([saved, catalog, bootstrap], sort_keys=True) == before
    # No memory/tier input participates; a later hardware policy cannot repick.
    assert continuation.model_upgrade_plan(dict(saved, HOST_RAM_GB='128', TIER='4'),
        catalog, **bootstrap) == plan


@pytest.mark.parametrize('change', [
    {'ODS_MODE': 'hybrid'}, {'GPU_BACKEND': 'nvidia'}, {'LLM_BACKEND': 'external'},
    {'EXTERNAL_LLM_URL': 'http://another-model'}, {'LEMONADE_EXTERNAL': 'true'},
    {'ODS_ACTIVE_MODEL_STORE': 'external-drive'}, {'MODEL_RECOMMENDED_GGUF': '../chosen.gguf'},
    {'MODEL_RECOMMENDED_GGUF': ''}, {'MODEL_RECOMMENDED_MODEL': 'different'},
    {'MODEL_RECOMMENDED_CONTEXT': '0'}, {'MODEL_RECOMMENDED_CONTEXT': '65537'},
    {'MODEL_RECOMMENDED_CONTEXT': '32768\nextra'}, {'MODEL_RECOMMENDED_CONTEXT': 'True'},
    {'GGUF_FILE': 'operator-choice.gguf'}, {'LLM_MODEL': 'operator-choice'},
    {'CTX_SIZE': '8192'}, {'MAX_CONTEXT': '8192'}, {'MODEL_SELECTION_SOURCE': 'dashboard'},
])
def test_continuation_refuses_changed_model_or_route(recommended_model, change):
    saved, catalog, bootstrap = recommended_model
    with pytest.raises(ValueError):
        continuation.model_upgrade_plan(dict(saved, **change), catalog, **bootstrap)


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'parts', 'digest', 'floating-url',
    'host', 'file', 'query', 'context-bool', 'context-missing'])
def test_continuation_requires_unambiguous_pinned_catalog(recommended_model, fault):
    saved, catalog, bootstrap = recommended_model
    record = catalog['models'][0]
    if fault == 'missing': catalog['models'] = []
    if fault == 'duplicate': catalog['models'].append(dict(record))
    if fault == 'parts':
        record['gguf_parts'] = [
            dict(file=name, url=record['gguf_url'], sha256='b' * 64)
            for name in ('chosen.gguf', 'part2.gguf')]
    if fault == 'digest': record['gguf_sha256'] = ''
    if fault == 'floating-url': record['gguf_url'] = record['gguf_url'].replace('a' * 40, 'main')
    if fault == 'host': record['gguf_url'] = record['gguf_url'].replace('huggingface.co', 'huggingface.co.invalid')
    if fault == 'file': record['gguf_url'] = record['gguf_url'].replace('/chosen.gguf', '/different.gguf')
    if fault == 'query': record['gguf_url'] += '?token=do-not-publish'
    if fault == 'context-bool': record['max_context_length'] = True
    if fault == 'context-missing':
        del record['max_context_length']
        del record['context_length']
    with pytest.raises(ValueError):
        continuation.model_upgrade_plan(saved, catalog, **bootstrap)


def test_continuation_does_not_download_for_selected_or_cloud_model(recommended_model):
    saved, catalog, bootstrap = recommended_model
    saved.update(GGUF_FILE='chosen.gguf', LLM_MODEL='chosen', MAX_CONTEXT='32768', CTX_SIZE='32768')
    assert continuation.model_upgrade_plan(saved, catalog, **bootstrap) == dict(
        status='selected-model', modelId='chosen-q4', arguments=[])
    assert continuation.model_upgrade_plan({'ODS_MODE': 'cloud'}, {}, **bootstrap) == dict(
        status='cloud-model', arguments=[])


def test_model_continuation_reads_private_inputs_without_mutation(tmp_path, recommended_model):
    saved, catalog, bootstrap = recommended_model
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/model-library.json').write_text(json.dumps(catalog))
    env = tmp_path / '.env'
    env.write_text('\n'.join(key + '=' + json.dumps(value) for key, value in saved.items())
        + '\nDASHBOARD_API_KEY=do-not-publish\n')
    env.chmod(0o600)
    before = env.read_bytes()
    plan, snapshot = continuation.inspect_model_upgrade(tmp_path, **bootstrap)
    assert snapshot[0] == before == env.read_bytes()
    assert 'do-not-publish' not in json.dumps(plan)
    assert plan['status'] == 'upgrade-required'
    env.write_text(env.read_text() + 'GGUF_FILE=other.gguf\n')
    with pytest.raises(ValueError, match='duplicate-retained-model-setting'):
        continuation.inspect_model_upgrade(tmp_path, **bootstrap)
    env.chmod(0o644)
    with pytest.raises(ValueError, match='private-owner-environment-required'):
        continuation.inspect_model_upgrade(tmp_path, **bootstrap)


@pytest.mark.parametrize('profile', ['qwen', 'gemma4'])
@pytest.mark.parametrize('tier', ['1', '2', '3', '4'])
def test_continuation_accepts_real_mac_tier_recommendations(profile, tier):
    # Exercise installed-format recommendations, including the reporter's high
    # memory tiers, without running hardware detection or starting any service.
    output = subprocess.run(['/bin/bash', '-c',
        'source "$1"; "set_${2}_tier_config" "$3"; '
        'printf "%s\\n" "$BOOTSTRAP_GGUF_FILE" "$BOOTSTRAP_LLM_MODEL" "$BOOTSTRAP_MAX_CONTEXT" '
        '"$GGUF_FILE" "$LLM_MODEL" "$MAX_CONTEXT"',
        'test-tier', str(ROOT / 'installers/macos/lib/tier-map.sh'), profile, tier],
        check=True, capture_output=True, text=True, timeout=10).stdout.splitlines()
    starter_file, starter_model, starter_context, filename, model_name, context = output
    saved = dict(ODS_MODE='local', GPU_BACKEND='apple', LLM_BACKEND='llama-server',
        GGUF_FILE=starter_file, LLM_MODEL=starter_model, MAX_CONTEXT=starter_context, CTX_SIZE=starter_context,
        MODEL_RECOMMENDED_GGUF=filename, MODEL_RECOMMENDED_MODEL=model_name, MODEL_RECOMMENDED_CONTEXT=context)
    catalog = json.loads((ROOT / 'config/model-library.json').read_text())
    plan = continuation.model_upgrade_plan(saved, catalog,
        bootstrap_file=starter_file, bootstrap_model=starter_model, bootstrap_context=starter_context)
    assert plan['status'] == 'upgrade-required'
    assert plan['arguments'][0] == filename
    assert plan['arguments'][3:] == [model_name, context, starter_file]


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


@pytest.mark.parametrize('fault', [None, 'proof', 'host', 'reproof', 'changed'])
def test_host_agent_continuation_is_between_proofs_and_before_publication(retained, fault):
    preparation, receipt, activation = retained
    calls = []
    def verify():
        calls.append('proof')
        failed = fault == 'proof' or fault == 'reproof' and calls.count('proof') == 2
        return dict(status='unknown' if failed else 'active',
            runtimeDigest=receipt['runtimeDigest'], serviceDigest=receipt['serviceDigest'])
    def run(*args, **kwargs):
        calls.append(args[0])
        return SimpleNamespace(returncode=0)
    def restore():
        calls.append('host')
        assert calls[:4] == ['proof', 'up', 'exec', 'host']
        assert not (preparation / 'selection-update.json').exists()
        assert json.loads((preparation / 'activation.json').read_text()) == activation
        if fault == 'host': raise ValueError('native-recovery-host-agent-failed')
        if fault == 'changed':
            (preparation / 'activation.json').write_text(json.dumps(dict(activation, phase='changed')))
    def finish():
        return module.finish(preparation=preparation, receipt=receipt, run=run, verify=verify,
            compose=SimpleNamespace(wait_ready=lambda run: None),
            selected_services={'dashboard-api': {}}, restore_host_agent=restore)
    if fault:
        with pytest.raises(ValueError): finish()
        assert not (preparation / 'selection-update.json').exists()
        if fault == 'proof': assert calls == ['proof']
    else:
        assert finish() == preparation / 'selection-update.json'
        assert calls == ['proof', 'up', 'exec', 'host', 'proof']
    if fault != 'changed':
        assert json.loads((preparation / 'activation.json').read_text()) == activation


@pytest.mark.parametrize('fault', [None, 'process', 'symlink', 'hardlink', 'public-log'])
def test_host_setup_uses_bound_transport_and_private_logs(tmp_path, monkeypatch, fault):
    preparation = tmp_path / 'data/pixel-native/preparation'
    preparation.mkdir(parents=True, mode=0o700)
    log = preparation / 'continuation-host-agent.log'
    other = tmp_path / 'untouched'
    other.write_text('untouched')
    other.chmod(0o600)
    if fault == 'symlink': log.symlink_to(other)
    if fault == 'hardlink': os.link(other, log)
    if fault == 'public-log':
        log.write_text('untouched')
        log.chmod(0o644)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert command[:2] == ['/bin/bash', '-c']
        assert 'ods_macos_install_host_agent' in command[2]
        assert kwargs['env']['DOCKER_HOST'] == 'unix:///verified.sock'
        assert set(kwargs['env']) == {'HOME', 'PATH', 'DOCKER_HOST', 'DOCKER_CONFIG', 'ODS_CONTINUATION_LOG_FD'}
        assert kwargs['cwd'] == tmp_path and kwargs['close_fds'] is True
        assert kwargs['stdin'] == subprocess.DEVNULL and kwargs['stderr'] == subprocess.STDOUT
        fd = kwargs['stdout'].fileno()
        assert kwargs['pass_fds'] == (fd,)
        assert os.fstat(fd).st_mode & 0o777 == 0o600
        os.write(fd, b'private diagnostic that must not be printed')
        return SimpleNamespace(returncode=int(fault == 'process'))
    monkeypatch.setattr(continuation.subprocess, 'run', run)
    environment = dict(HOME=str(tmp_path), PATH='/usr/bin:/bin', DOCKER_HOST='unix:///verified.sock',
        DOCKER_CONFIG=str(tmp_path / 'docker'), BASH_ENV='must-not-run', ODS_AGENT_KEY='must-not-forward')
    if fault:
        with pytest.raises((ValueError, OSError)) as error:
            continuation.restore_host_agent(tmp_path, environment)
        assert 'private diagnostic' not in str(error.value)
        if fault != 'process': assert not calls
    else:
        continuation.restore_host_agent(tmp_path, environment)
        assert len(calls) == 1
    assert other.read_text() == 'untouched'


@pytest.mark.parametrize('requested', [False, True])
def test_cli_host_agent_success_does_not_claim_complete_install(monkeypatch, capsys, requested):
    def recover(install_dir, ods_source, **kwargs):
        assert kwargs == ({'restore_host_agent': True} if requested else {})
        return Path('/fixture/selection-update.json')
    monkeypatch.setattr(module, 'recover', recover)
    monkeypatch.setattr(module.sys, 'argv', ['recover', '--install-dir', '/fixture',
        *(['--restore-host-agent'] if requested else [])])
    assert module.main() == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result['installerComplete'] is False
    assert result.get('hostAgentReady') is (True if requested else None)
    assert 'full-model download' in output.err


@pytest.mark.parametrize('authenticated', [True, False])
def test_real_host_setup_subprocess_uses_shared_library_in_isolated_home(tmp_path, monkeypatch, authenticated):
    installed = tmp_path / 'retained ods'
    preparation = installed / 'data/pixel-native/preparation'
    preparation.mkdir(parents=True, mode=0o700)
    home, library, binaries = (tmp_path / name for name in ('home', 'lib', 'bin'))
    for path in (home, library, binaries, installed / 'bin', installed / '.venv/host-agent/bin'):
        path.mkdir(parents=True, exist_ok=True)
    (installed / 'bin/ods-host-agent.py').touch()
    runtime = installed / '.venv/host-agent/bin/python'
    runtime.write_text('#!/bin/sh\nif [ "$1" = "-c" ]; then exit 0; fi\nexec '
        + shlex.quote(sys.executable) + ' "$@"\n')
    runtime.chmod(0o700)
    (library / 'host-agent-install.sh').write_bytes((ROOT / 'installers/macos/lib/host-agent-install.sh').read_bytes())
    (library / 'constants.sh').write_text("""
ODS_AGENT_PLIST_LABEL=com.ods.host-agent
ODS_AGENT_PLIST="$HOME/Library/LaunchAgents/$ODS_AGENT_PLIST_LABEL.plist"
HOST_AGENT_BRIDGE_PLIST_LABEL=com.ods.host-agent-bridge
HOST_AGENT_BRIDGE_PLIST="$HOME/bridge.plist"
HOST_AGENT_BRIDGE_LOG="$HOME/bridge.log"
macos_normalize_agent_bind() { printf '%s\\n' "$1"; }
macos_bind_probe_host() { printf '%s\\n' "$1"; }
macos_bind_uses_direct_gateway() { return 1; }
""")
    (library / 'env-generator.sh').write_text("""
read_env_value() {
    case "$2" in
        ODS_AGENT_BIND) printf '127.0.0.1\\n' ;;
        ODS_AGENT_PORT) printf '7710\\n' ;;
        ODS_AGENT_KEY) printf 'fixture-private-key\\n' ;;
        ODS_AGENT_HOST) printf 'host.docker.internal\\n' ;;
        ODS_MACOS_HOST_AGENT_BRIDGE_ENABLED) printf 'false\\n' ;;
        *) printf '\\n' ;;
    esac
}
""")
    (library / 'bridge-manager.sh').write_text('macos_configure_port_bridge() { test "$1" = false; }\n')
    (library / 'host-agent-listener.sh').write_text('macos_retire_owned_host_agent_listener() { return 0; }\n')
    scripts = {
        'launchctl': 'printf "%s\\n" "$*" >> "$HOME/launchctl.calls"\n',
        'curl': 'exit 0\n',
        'sleep': 'exit 0\n',
        'docker': """
case "$1" in
    inspect) printf 'running\\n' ;;
    exec)
        IFS= read -r header
        test "$header" = 'Authorization: Bearer fixture-private-key' || exit 2
        printf '%s\\n' "$*" >> "$HOME/docker.calls"
        test "$DOCKER_HOST" = 'unix:///verified.sock' || exit 3
        """ + ('exit 0' if authenticated else 'exit 1') + """
        ;;
    *) exit 4 ;;
esac
""",
    }
    for name, body in scripts.items():
        path = binaries / name
        path.write_text('#!/bin/sh\n' + body)
        path.chmod(0o700)
    monkeypatch.setattr(continuation, 'HERE', library)
    environment = dict(HOME=str(home), PATH=str(binaries) + ':/usr/bin:/bin',
        DOCKER_HOST='unix:///verified.sock', DOCKER_CONFIG=str(home / 'docker-config'))
    if authenticated:
        continuation.restore_host_agent(installed, environment)
    else:
        with pytest.raises(ValueError, match='native-recovery-host-agent-failed'):
            continuation.restore_host_agent(installed, environment)
    plist_path = home / 'Library/LaunchAgents/com.ods.host-agent.plist'
    plist = plistlib.loads(plist_path.read_bytes())
    assert plist['ProgramArguments'][-2:] == ['--install-dir', str(installed)]
    assert plist['ProgramArguments'][0] == str(runtime)
    assert plist['EnvironmentVariables']['DOCKER_HOST'] == 'unix:///verified.sock'
    assert plist['EnvironmentVariables']['DOCKER_CONFIG'] == str(home / 'docker-config')
    assert plist['EnvironmentVariables']['DOCKER_CONTEXT'] == ''
    calls = (home / 'docker.calls').read_text()
    assert 'fixture-private-key' not in calls
    assert len(calls.splitlines()) == (1 if authenticated else 20)
    diagnostic = (preparation / 'continuation-host-agent.log').read_text()
    assert 'fixture-private-key' not in diagnostic
    assert ('Dashboard container reached the authenticated host agent' in diagnostic) is authenticated
