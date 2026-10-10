"""Run the shipped CLI with controlled process boundaries, including failure ordering."""
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(os.environ.get('ODS_INGRESS_CLI_SOURCE_ROOT', Path(__file__).resolve().parents[1]))


@pytest.mark.parametrize('command', ['start pixel-native-ingress', 'restart pixel-native-ingress', 'update'])
@pytest.mark.parametrize('failure', [False, True])
def test_native_cli_provisions_before_recreate_and_stops_on_failure(tmp_path, command, failure):
    install = tmp_path / 'install'; install.mkdir()
    (install / '.env').write_text('SHIELD_API_KEY=fixture\n')
    log = tmp_path / 'commands'
    python = tmp_path / 'private-python'
    python.write_text('#!/bin/bash\nprintf "refresh\\n" >> "$EVENT_LOG"\nexit ' + ('19' if failure else '0') + '\n')
    python.chmod(0o700)
    script = '''
source "$CLI_SOURCE" help >/dev/null
test_install() { :; }
ensure_llama_cpu_budget() { :; }
get_compose_flags() { printf '%s\n' '-f installers/macos/pixel-native.compose.yaml.disabled'; }
network_access_is_enabled() { return 1; }
macos_wait_for_bootstrap_compose_safe() { :; }
macos_maybe_resume_bootstrap_upgrade() { :; }
start_native_llama() { :; }
compose_pull_with_retry() { :; }
cmd_status() { :; }
sleep() { :; }
docker() { printf 'docker:%s\n' "$*" >> "$EVENT_LOG"; }
'''
    result = subprocess.run(['/bin/bash', '-c', script + '\ncmd_' + command],
        env={**os.environ, 'ODS_INSTALL_DIR': str(install), 'ODS_PYTHON_CMD': str(python),
            'EVENT_LOG': str(log), 'CLI_SOURCE': str(ROOT / 'installers/macos/ods-macos.sh')},
        text=True, capture_output=True, timeout=15)
    events = log.read_text().splitlines() if log.exists() else []
    assert events and events[0] == 'refresh', (result.returncode, events, result.stderr[-500:])
    if failure:
        assert result.returncode != 0 and events == ['refresh']
    else:
        assert result.returncode == 0, result.stderr[-500:]
        assert len(events) == 2 and ' up -d' in events[1]


def test_unrelated_service_needs_no_native_refresh(tmp_path):
    install = tmp_path / 'install'; install.mkdir()
    log = tmp_path / 'commands'
    script = '''source "$CLI_SOURCE" help >/dev/null
test_install() { :; }; ensure_llama_cpu_budget() { :; }
get_compose_flags() { printf '%s\n' '-f installers/macos/pixel-native.compose.yaml.disabled'; }
network_access_is_enabled() { return 1; }
docker() { printf 'docker:%s\n' "$*" >> "$EVENT_LOG"; }
cmd_start dashboard-api
'''
    result = subprocess.run(['/bin/bash', '-c', script], env={**os.environ,
        'ODS_INSTALL_DIR': str(install), 'ODS_PYTHON_CMD': '/deliberately-absent-python',
        'EVENT_LOG': str(log), 'CLI_SOURCE': str(ROOT / 'installers/macos/ods-macos.sh')},
        text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr[-500:]
    assert log.read_text().splitlines() == ['docker:compose -f installers/macos/pixel-native.compose.yaml.disabled up -d dashboard-api']
