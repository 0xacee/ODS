"""Real Compose hashing of the actual previous-main definition; no daemon calls."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get('ODS_INGRESS_BASELINE_ROOT')


@pytest.mark.skipif(not BASE, reason='requires the separately pinned previous-main source archive')
def test_actual_previous_main_ingress_recipe_survives_secure_refresh_snapshot(tmp_path):
    baseline = Path(BASE)
    spec = importlib.util.spec_from_file_location('recipe_refresh', ROOT / 'installers/macos/lib/pixel-native-ingress-refresh.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    base = tmp_path / 'base.json'
    base.write_text(json.dumps({'services': {name: {'image': 'busybox:1.36.1'} for name in ('dashboard-api', 'open-webui')}}))
    env = {key: value for key, value in os.environ.items() if not key.startswith(('PIXEL_', 'COMPOSE_'))}
    env.update(PIXEL_NATIVE_UID=str(os.getuid()), PIXEL_INGRESS_GID=str(os.getgid()),
        PIXEL_NATIVE_INGRESS_IMAGE='sha256:' + 'a' * 64, PIXEL_NATIVE_CONFIG_PATH=str(tmp_path / 'gateway.json'),
        PIXEL_NATIVE_WORKSPACE=str(tmp_path / 'workspace'), PIXEL_INGRESS_RUNTIME_DIR=str(tmp_path / 'runtime'),
        PIXEL_PREVIEW_RUNTIME_DIR=str(tmp_path / 'preview'), PIXEL_OPENWEBUI_KEY='b' * 64, DASHBOARD_API_KEY='c' * 64)
    # Same install-directory resolution for old/new source; only the overlay's
    # exact source bytes change. The definitions are rendered, never started.
    def command(root):
        return ['docker', 'compose', '--profile', 'native-config-maintenance', '--project-name', 'ods',
            '--project-directory', str(ROOT), '--env-file', '/dev/null', '-f', str(base),
            '-f', str(ROOT / 'extensions/services/pixel-edge/compose.yaml.disabled'),
            '-f', str(root / 'installers/macos/pixel-native.compose.yaml.disabled')]
    def execute(args): return subprocess.run(args, env=env, capture_output=True, text=True, check=True, timeout=30)
    old = json.loads(execute([*command(baseline), 'config', '--format', 'json']).stdout)
    current = json.loads(execute([*command(ROOT), 'config', '--format', 'json']).stdout)
    expected = execute([*command(baseline), 'config', '--hash', module.SERVICE]).stdout.strip().split()[1]
    service = old['services'][module.SERVICE]
    observed = {'Id': 'd' * 64, 'Name': '/ods-pixel-native-ingress-1', 'Image': service['image'],
        'Config': {'User': service['user'], 'Env': [key + '=' + str(value) for key, value in service['environment'].items()],
            'Labels': {'com.docker.compose.project': 'ods', 'com.docker.compose.service': module.SERVICE,
                'com.docker.compose.config-hash': expected}},
        'Mounts': [{'Destination': value['target'], 'Type': value['type'], 'RW': not value.get('read_only', False),
            **({'Source': value['source']} if value['type'] == 'bind' else {'Name': old['volumes'][value['source']]['name']})}
            for value in service['volumes']], 'NetworkSettings': {'Networks': {
                old['networks'][name]['name']: {} for name in service['networks']}}}
    def docker(*args, **kwargs):
        if args[0] == 'inspect': return SimpleNamespace(returncode=0, stdout=json.dumps([observed]))
        assert args[0] == 'compose' and args[-3:] == ('config', '--hash', module.SERVICE)
        return execute(['docker', *args])
    receipt = module.snapshot_previous(None, docker, tmp_path, install_dir=ROOT, project='ods',
        document=current, observed=observed, source=Path(env['PIXEL_NATIVE_CONFIG_PATH']))
    restored = json.loads(Path(receipt['path']).read_text())
    assert restored['services'][module.SERVICE]['environment']['PIXEL_GATEWAY_TOKEN_FILE'] == '/run/gateway.json'
    assert set(restored['services']) == {module.SERVICE}
    assert receipt['configHash'] == expected
