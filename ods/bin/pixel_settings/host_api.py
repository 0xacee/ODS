"""Owner-facing persistence; runtime activation is a separate lifecycle."""
from pixel_provider.store import StoreError
from pixel_provider.store_factory import existing_directory, prepare_directory, provider_directory
from .contract import SettingsError, validate_preferences
from .store import MAX_REVISION, create_settings_store, default_document, normalize_document


def _response(document):
    return {"configuration": normalize_document(document),
            "runtime": {"status": "not-applied", "reason": "settings-runtime-not-integrated"}}


def get_settings(data_dir):
    directory = provider_directory(data_dir)
    with existing_directory(directory) as exists:
        document = create_settings_store(directory).load() if exists else default_document()
    return _response(document)


def save_settings(data_dir, body):
    if (type(body) is not dict or set(body) != {"expectedRevision", "changes"}
            or type(body["expectedRevision"]) is not int
            or not 0 <= body["expectedRevision"] < MAX_REVISION):
        raise StoreError("invalid-request")
    try:
        changes = validate_preferences(body["changes"])
    except SettingsError:
        raise StoreError("invalid-request") from None
    directory = provider_directory(data_dir)
    prepare_directory(directory)
    document = create_settings_store(directory).save_changes(changes, expected_revision=body["expectedRevision"])
    return _response(document)
