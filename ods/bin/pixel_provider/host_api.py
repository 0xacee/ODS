"""Host-owned provider Settings. Saving is not runtime activation."""

import os

from .config import default_config, public_config
from .store import StoreError
from .vault import validate_edit
from .store_factory import (
    credential_store,
    existing_directory,
    prepare_directory,
    provider_directory,
    provider_store,
)


def _directory(data_dir):
    """Compatibility boundary for existing, still-POSIX scope storage callers.

    Settings uses provider_directory directly. Keeping this guard prevents the
    separate ScopeStore from silently claiming native Windows qualification.
    """
    if os.name != "posix":
        raise StoreError("unsupported-platform")
    return provider_directory(data_dir)


def get_configuration(data_dir):
    directory = provider_directory(data_dir)
    with existing_directory(directory) as exists:
        if not exists:
            # A pristine install has no feature state and requires no migration.
            return public_config(default_config())
        return public_config(provider_store(directory).load())


def save_configuration(data_dir, body):
    body = validate_edit(body)
    directory = provider_directory(data_dir)
    # No recursive mkdir/chmod or silent repair of existing state. The install's
    # data directory must already exist. Store checks custody before any write.
    prepare_directory(directory)
    return credential_store(directory).save_public(body)
