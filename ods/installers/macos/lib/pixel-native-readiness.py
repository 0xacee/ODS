"""Bounded, observational API checks after native macOS installer continuation.

This does not activate services or certify protected recovery, chat/tool delivery
or release identity. Credentials and upstream response bodies are never printed.
"""
import argparse
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys


HERE = Path(__file__).resolve().parent
MAX_RESPONSE = 1024 * 1024


def load(name):
    spec = importlib.util.spec_from_file_location('readiness_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _http_worker():
    # A separate process gives the parent a wall-clock deadline even when a
    # listener trickles headers/body bytes often enough to avoid socket timeout.
    request = json.loads(sys.stdin.buffer.read(16385))
    port, path, key = request['port'], request['path'], request.get('key', '')
    if (type(port) is not int or not 1 <= port <= 65535 or type(path) is not str
            or not path.startswith('/') or len(path) > 2048
            or any(ord(c) < 33 or ord(c) > 126 for c in path)
            or type(key) is not str or len(key) > 4096
            or any(ord(c) < 33 or ord(c) > 126 for c in key)):
        raise ValueError('invalid-probe')
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    try:
        headers = {'Authorization': 'Bearer ' + key} if key else {}
        connection.request('GET', path, headers=headers)
        response = connection.getresponse()
        # No redirects and no proxy environment: a local credential must stay
        # on the exact loopback endpoint selected by this installation.
        if response.status != 200:
            raise ValueError('http-status')
        body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            raise ValueError('response-too-large')
        value = json.loads(body) if request.get('json', True) else {'httpStatus': 200}
        if type(value) not in (dict, list):
            raise ValueError('invalid-response')
        print(json.dumps(value))
    finally:
        connection.close()


def probe(port, path, *, key='', json_response=True, timeout=30):
    payload = json.dumps({'port': port, 'path': path, 'key': key, 'json': json_response})
    if len(payload.encode()) > 16384:
        raise ValueError('native-readiness-request-invalid')
    try:
        result = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve()), '--http-probe'],
            input=payload, capture_output=True, text=True, cwd='/', timeout=timeout, check=False)
        if result.returncode or len(result.stdout) > 6 * MAX_RESPONSE:
            raise ValueError('native-readiness-http-failed')
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise ValueError('native-readiness-http-failed') from None


def port(values, name, default):
    value = values.get(name, str(default))
    if not re.fullmatch(r'[1-9][0-9]{0,4}', value) or int(value) > 65535:
        raise ValueError('native-readiness-port-invalid')
    return int(value)


def observe_apis(install_dir, *, opencode_choice=None, request=probe):
    continuation = load('pixel-native-continuation')
    values, snapshot = continuation._saved_environment(install_dir, continuation.MODEL_KEYS | {
        'DASHBOARD_API_KEY', 'DASHBOARD_API_PORT', 'DASHBOARD_PORT', 'ODS_NATIVE_LLAMA_PORT',
        'LITELLM_PORT', 'LITELLM_KEY', 'ODS_MODEL_SWITCHBOARD', 'ENABLE_OPENCODE'},
        'duplicate-retained-readiness-setting')
    key = values.get('DASHBOARD_API_KEY', '')
    if not re.fullmatch('[a-f0-9]{64}', key):
        raise ValueError('native-readiness-dashboard-key-required')
    api_port = port(values, 'DASHBOARD_API_PORT', 3002)
    dashboard_port = port(values, 'DASHBOARD_PORT', 3001)
    optional, optional_snapshot = continuation.optional_setup_selection(
        install_dir, {'dashboard-api': {}}, opencode_choice=opencode_choice)
    plan, model_snapshot = continuation.inspect_model_upgrade(
        install_dir, **continuation.bootstrap_settings(install_dir))
    if snapshot != optional_snapshot or snapshot != model_snapshot:
        raise ValueError('native-readiness-environment-changed')
    checks = []

    def check(name, operation):
        try:
            passed = operation() is True
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, OSError):
            passed = False
        checks.append({'name': name, 'passed': passed})

    def api(path):
        return request(api_port, path, key=key)

    check('dashboard', lambda: request(dashboard_port, '/', json_response=False).get('httpStatus') == 200)
    check('dashboard-api', lambda: api('/health').get('status') == 'ok')
    application = None

    def host_agent():
        nonlocal application
        # This Dashboard endpoint uses the authenticated host-agent client;
        # failures are 503/502, not a cached or synthetic success response.
        application = api('/api/apps/opencode')
        return (application.get('id') == 'opencode' and application.get('platform') == 'darwin'
                and application.get('state') in ('running', 'starting', 'installing', 'stopped', 'not_installed'))
    check('authenticated-host-agent', host_agent)
    selected = optional['opencode']['selected']
    if selected is None:
        checks.append({'name': 'opencode-choice', 'passed': False})
    elif selected:
        check('selected-opencode', lambda: application.get('state') == 'running'
              and application.get('installed') is True and application.get('running') is True)

    if values.get('ODS_MODE') == 'local':
        runtime_port = port(values, 'ODS_NATIVE_LLAMA_PORT', 8080)
        filename = values['MODEL_RECOMMENDED_GGUF']
        aliases = {filename, values['MODEL_RECOMMENDED_MODEL'], plan.get('modelId')}
        context = int(values['MODEL_RECOMMENDED_CONTEXT'])

        def native_model():
            if plan['status'] != 'selected-model':
                return False
            if request(runtime_port, '/health').get('status') != 'ok':
                return False
            models = request(runtime_port, '/v1/models').get('data')
            if not isinstance(models, list) or not any(
                    isinstance(item, dict) and item.get('id') in aliases for item in models):
                return False
            props = request(runtime_port, '/props')
            actual = props.get('default_generation_settings', {}).get('n_ctx')
            file = props.get('model_path')
            return (type(file) is str and Path(file).name == filename
                    and type(actual) is int and context <= actual <= ((context + 255) // 256) * 256)
        check('selected-native-model', native_model)
        check('dashboard-model-selection', lambda: api('/api/models').get('currentModel') == plan['modelId'])
    else:
        cloud_key = values.get('LITELLM_KEY', '')
        alias = 'ods/current' if values.get('ODS_MODEL_SWITCHBOARD', 'enabled') == 'enabled' else 'default'
        check('cloud-model-route', lambda: bool(cloud_key) and any(
            isinstance(item, dict) and item.get('id') == alias for item in request(
                port(values, 'LITELLM_PORT', 4000), '/v1/models', key=cloud_key).get('data', [])))

    def extensions():
        result = api('/api/extensions/catalog')
        return (result.get('agent_available') is True and result.get('library_available') is True
                and isinstance(result.get('extensions'), list) and bool(result['extensions']))
    check('extensions-catalog', extensions)
    release_state = 'unverified'

    def portal():
        nonlocal release_state
        result = api('/api/pixel/status')
        readiness = result.get('readiness', {})
        release_state = 'mismatch' if readiness.get('releaseState') == 'mismatch' else 'unverified'
        return (result.get('available') is True and readiness.get('routeAvailable') is True
                and readiness.get('accessState') == 'verified'
                and readiness.get('effectiveMode') in ('sandboxed', 'full-access')
                and release_state != 'mismatch')
    check('portal-access', portal)
    if continuation.saved_model_environment(install_dir)[1] != snapshot:
        raise ValueError('native-readiness-environment-changed')
    return {'status': 'api-checks-passed' if all(c['passed'] for c in checks) else 'needs-attention',
        'checks': checks, 'installerComplete': False, 'releaseState': release_state,
        'pendingVerification': ['protected-recovery', 'selected-service-health',
                                'selected-optional-state', 'model-completion', 'portal-chat-and-preview']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--http-probe', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--install-dir')
    parser.add_argument('--opencode-choice', choices=('enabled', 'disabled'))
    args = parser.parse_args()
    if args.http_probe:
        try:
            _http_worker()
            return 0
        except Exception:
            print('http-probe-failed', file=sys.stderr)
            return 1
    if not args.install_dir:
        parser.error('--install-dir is required')
    if sys.platform != 'darwin' or os.geteuid() == 0:
        parser.error('run as the signed-in macOS owner')
    try:
        result = observe_apis(Path(args.install_dir).expanduser().resolve(strict=True),
                              opencode_choice=args.opencode_choice)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError):
        print(json.dumps({'status': 'inspection-unavailable', 'installerComplete': False}))
        return 1
    print(json.dumps(result))
    return 0 if result['status'] == 'api-checks-passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
