"""Validate retained installer inputs without changing the active installation."""
import importlib.util
import json
from pathlib import Path
import re
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
