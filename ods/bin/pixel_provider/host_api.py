"""Host-owned provider Settings. Saving is not runtime activation."""

from .config import default_config, public_config
from .vault import validate_edit
from .store_factory import (
    credential_store,
    existing_directory,
    prepare_directory,
    provider_directory,
    provider_store,
)


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
