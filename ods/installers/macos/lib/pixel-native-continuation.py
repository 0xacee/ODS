"""Validate retained installer inputs without changing the active installation."""
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from urllib.parse import unquote, urlsplit


HERE = Path(__file__).resolve().parent
MODEL_KEYS = frozenset((
    'ODS_MODE', 'GPU_BACKEND', 'LLM_BACKEND', 'EXTERNAL_LLM_URL', 'LEMONADE_EXTERNAL',
    'ODS_ACTIVE_MODEL_STORE', 'MODEL_SELECTION_SOURCE',
    'GGUF_FILE', 'LLM_MODEL', 'MAX_CONTEXT', 'CTX_SIZE',
    'MODEL_RECOMMENDED_MODEL', 'MODEL_RECOMMENDED_GGUF', 'MODEL_RECOMMENDED_CONTEXT',
))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def saved_model_environment(install_dir):
    environment = load('continuation_env', HERE / 'pixel-native-env.py')
    snapshot = environment.snapshot(Path(install_dir) / '.env')
    selected = {}
    for line in snapshot[0].decode('utf-8').splitlines():
        match = environment.ASSIGNMENT.fullmatch(line)
        if match and match[1] in MODEL_KEYS:
            key, value = match.groups()
            if key in selected:
                raise ValueError('duplicate-retained-model-setting')
            selected[key] = environment.values.parse_env_value(value)
    return selected, snapshot


def model_upgrade_plan(saved, catalog, *, bootstrap_file, bootstrap_model, bootstrap_context):
    """Recover the saved recommendation, never run hardware-based selection.

    The returned arguments are for the existing bootstrap-upgrade.sh protocol.
    Planning is not proof of the live model, download completion or install health.
    """
    mode = saved.get('ODS_MODE', '')
    if mode == 'cloud':
        return {'status': 'cloud-model', 'arguments': []}
    if (mode != 'local' or saved.get('GPU_BACKEND') != 'apple'
            or saved.get('LLM_BACKEND') != 'llama-server'
            or saved.get('EXTERNAL_LLM_URL') or saved.get('LEMONADE_EXTERNAL', 'false') != 'false'
            or saved.get('ODS_ACTIVE_MODEL_STORE', 'default') != 'default'):
        raise ValueError('retained-local-model-route-required')
    filename = saved.get('MODEL_RECOMMENDED_GGUF', '')
    model_name = saved.get('MODEL_RECOMMENDED_MODEL', '')
    context = saved.get('MODEL_RECOMMENDED_CONTEXT', '')
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*\.gguf', filename)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', model_name)
            or not re.fullmatch(r'[1-9][0-9]{0,8}', context)):
        raise ValueError('saved-model-recommendation-required')
    records = catalog.get('models') if type(catalog) is dict else None
    if type(records) is not list or any(type(record) is not dict for record in records):
        raise ValueError('installed-model-catalog-required')
    # A filename must have exactly one meaning in this installed catalog.
    matches = [record for record in records if record.get('gguf_file') == filename]
    if len(matches) != 1 or matches[0].get('llm_model_name') != model_name:
        raise ValueError('saved-model-recommendation-mismatch')
    model = matches[0]
    limit = model.get('max_context_length', model.get('context_length'))
    if type(limit) is not int or not 1024 <= int(context) <= limit:
        raise ValueError('saved-model-context-invalid')
    active = (saved.get('GGUF_FILE'), saved.get('LLM_MODEL'),
              saved.get('MAX_CONTEXT'), saved.get('CTX_SIZE'))
    target = (filename, model_name, context, context)
    if active == target:
        return {'status': 'selected-model', 'modelId': model.get('id'), 'arguments': []}
    if (active != (bootstrap_file, bootstrap_model, str(bootstrap_context), str(bootstrap_context))
            or saved.get('MODEL_SELECTION_SOURCE', 'installer') != 'installer'):
        raise ValueError('retained-bootstrap-model-required')
    # Reuse artifact validation, but require a checksum and a pinned revision for
    # a new automatic download. The existing upgrader accepts one GGUF only.
    contracts = load('continuation_model_contracts', HERE.parents[2] / 'scripts/preserve-active-model.py')
    artifacts = contracts.manifest_for(model)
    if not artifacts or len(artifacts) != 1 or artifacts[0]['file'] != filename:
        raise ValueError('single-file-bootstrap-model-required')
    artifact = artifacts[0]
    url = urlsplit(artifact['url'])
    if (url.scheme != 'https' or url.netloc != 'huggingface.co'
            or url.query or url.fragment
            or not re.fullmatch(r'/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/resolve/[a-f0-9]{40}/[^/]+', url.path)
            or unquote(url.path.rsplit('/', 1)[1]) != filename
            or not re.fullmatch(r'[a-f0-9]{64}', artifact['sha256'])):
        raise ValueError('pinned-bootstrap-model-required')
    return {'status': 'upgrade-required', 'modelId': model.get('id'),
            'arguments': [filename, artifact['url'], artifact['sha256'],
                          model_name, context, bootstrap_file]}


def inspect_model_upgrade(install_dir, **bootstrap):
    install_dir = Path(install_dir).resolve(strict=True)
    saved, snapshot = saved_model_environment(install_dir)
    catalog = json.loads((install_dir / 'config/model-library.json').read_text(encoding='utf-8'))
    return model_upgrade_plan(saved, catalog, **bootstrap), snapshot


def restore_host_agent(install_dir, process_env):
    """Run shared owner-level setup only after the caller's protected readback.

    Keep subprocess diagnostics in the private preparation directory, not in
    the shareable CLI output. The caller rechecks protected state afterwards.
    """
    install_dir = Path(install_dir).resolve(strict=True)
    preparation = install_dir / 'data/pixel-native/preparation'
    info = preparation.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or preparation.resolve(strict=True) != preparation):
        raise ValueError('private-native-preparation-required')
    log = preparation / 'continuation-host-agent.log'
    fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, 'ab', buffering=0) as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise ValueError('private-native-continuation-log-required')
        environment = {key: process_env[key] for key in ('HOME', 'PATH', 'DOCKER_HOST', 'DOCKER_CONFIG')}
        environment['ODS_CONTINUATION_LOG_FD'] = str(stream.fileno())
        result = subprocess.run(['/bin/bash', '-c', """
set -euo pipefail
LIB_DIR="$1"
INSTALL_DIR="$2"
export ODS_HOME="$INSTALL_DIR"
ai() { printf '%s\\n' "$*"; }
ai_ok() { ai "[OK] $*"; }
ai_warn() { ai "[WARN] $*"; }
ai_err() { ai "[ERROR] $*"; }
for library in constants env-generator bridge-manager host-agent-listener host-agent-install; do
    source "$LIB_DIR/$library.sh"
done
ODS_LOG_FILE="/dev/fd/$ODS_CONTINUATION_LOG_FD"
ods_macos_install_host_agent
""", 'ods-recovery-host-agent', str(HERE), str(install_dir)],
            cwd=install_dir, env=environment, stdin=subprocess.DEVNULL,
            stdout=stream, stderr=subprocess.STDOUT, close_fds=True,
            pass_fds=(stream.fileno(),), timeout=600, check=False)
        if result.returncode:
            raise ValueError('native-recovery-host-agent-failed')
