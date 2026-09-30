#!/usr/bin/env python3
"""Fail-closed, cross-process selection guard for ``ods disable``.

The Dashboard and this command lock the same file in the installed data bind
mount.  This helper owns the final dependency check and Compose-file rename;
the CLI may perform a preliminary check and stop Docker outside that lock.
"""

from __future__ import annotations

import argparse
import contextlib
import os
from pathlib import Path
import re
import stat
import sys
import time

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised by Windows CI
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - exercised by POSIX CI
    msvcrt = None

MAX_YAML_BYTES = 1024 * 1024
SERVICE_ID = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")


class SelectionError(Exception):
    """A selection cannot be committed without risking the installed stack."""


def _read_yaml(path: Path) -> object:
    """Read a bounded regular YAML file without following its final symlink."""
    try:
        import yaml
    except ImportError as exc:
        raise SelectionError("PyYAML is required to inspect extension dependencies") from exc
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            selected = os.fstat(stream.fileno())
            if not stat.S_ISREG(selected.st_mode) or selected.st_size > MAX_YAML_BYTES:
                raise SelectionError(f"Invalid selected file: {path}")
            raw = stream.read(MAX_YAML_BYTES + 1)
        if len(raw) > MAX_YAML_BYTES:
            raise SelectionError(f"Selected file is too large: {path}")
        return yaml.safe_load(raw.decode("utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise SelectionError(f"Cannot inspect selected file: {path}") from exc


def _manifest_dependencies(directory: Path) -> set[str]:
    for name in ("manifest.yaml", "manifest.yml"):
        manifest = directory / name
        try:
            selected = manifest.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise SelectionError(f"Cannot inspect dependency manifest: {manifest}") from exc
        if not stat.S_ISREG(selected.st_mode):
            raise SelectionError(f"Invalid dependency manifest: {manifest}")
        document = _read_yaml(manifest)
        if not isinstance(document, dict) or not isinstance(document.get("service"), dict):
            raise SelectionError(f"Invalid dependency manifest: {manifest}")
        dependencies = document["service"].get("depends_on", [])
        if not isinstance(dependencies, list) or any(
            not isinstance(dep, str) or SERVICE_ID.fullmatch(dep) is None
            for dep in dependencies
        ):
            raise SelectionError(f"Invalid dependencies in manifest: {manifest}")
        return set(dependencies)
    return set()


def _compose_dependencies(path: Path) -> set[str]:
    document = _read_yaml(path)
    services = document.get("services") if isinstance(document, dict) else None
    if not isinstance(services, dict):
        raise SelectionError(f"Invalid selected Compose services: {path}")
    dependencies: set[str] = set()
    for definition in services.values():
        if not isinstance(definition, dict):
            raise SelectionError(f"Invalid selected Compose service: {path}")
        declared = definition.get("depends_on", [])
        if isinstance(declared, list):
            names = declared
        elif isinstance(declared, dict) and all(isinstance(value, dict) for value in declared.values()):
            names = declared.keys()
        else:
            raise SelectionError(f"Invalid selected Compose dependencies: {path}")
        for name in names:
            if not isinstance(name, str) or not name or "$" in name:
                raise SelectionError(f"Invalid selected Compose dependency: {path}")
            dependencies.add(name)
    return dependencies


def _enabled_dependents(install_dir: Path, service_id: str) -> list[str]:
    """Match Dashboard's user-first shadowing and selected-Compose scan."""
    dependents: list[str] = []
    seen: set[str] = set()
    roots = (
        install_dir / "data" / "user-extensions",
        install_dir / "extensions" / "services",
    )
    for root in roots:
        try:
            root_stat = root.lstat()
            if not stat.S_ISDIR(root_stat.st_mode):
                raise SelectionError(f"Invalid extension root: {root}")
            peers = sorted(root.iterdir())
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise SelectionError(f"Cannot inspect extension root: {root}") from exc
        for peer in peers:
            if peer.name == service_id or peer.name in seen:
                continue
            try:
                peer_stat = peer.lstat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise SelectionError(f"Cannot inspect extension peer: {peer}") from exc
            if stat.S_ISLNK(peer_stat.st_mode):
                raise SelectionError(f"Invalid extension peer: {peer}")
            if not stat.S_ISDIR(peer_stat.st_mode):
                continue
            seen.add(peer.name)
            compose = peer / "compose.yaml"
            try:
                compose_stat = compose.lstat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise SelectionError(f"Cannot inspect selected Compose file: {compose}") from exc
            if not stat.S_ISREG(compose_stat.st_mode):
                raise SelectionError(f"Invalid selected Compose file: {compose}")
            dependencies = _manifest_dependencies(peer)
            dependencies.update(_compose_dependencies(compose))
            if service_id in dependencies:
                dependents.append(peer.name)
    return dependents


def _target_dir(install_dir: Path, service_id: str) -> Path:
    for root in (install_dir / "data" / "user-extensions", install_dir / "extensions" / "services"):
        directory = root / service_id
        try:
            selected = directory.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise SelectionError(f"Cannot inspect extension: {service_id}") from exc
        if not stat.S_ISDIR(selected.st_mode):
            raise SelectionError(f"Invalid extension directory: {service_id}")
        return directory
    raise SelectionError(f"Unknown extension: {service_id}")


@contextlib.contextmanager
def _selection_lock(install_dir: Path, timeout: float):
    if fcntl is None and msvcrt is None:
        raise SelectionError("Extension selection requires a file-lock runtime")
    lock_path = install_dir / "data" / ".extensions-lock"
    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
            0o600,
        )
    except OSError as exc:
        raise SelectionError(f"Cannot open shared extensions lock: {lock_path}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise SelectionError(f"Invalid shared extensions lock: {lock_path}")
        if msvcrt is not None:
            # Match Dashboard's one-byte Windows lock for local processes.
            # Docker Desktop bind-mount interoperability needs live acceptance.
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
        deadline = time.monotonic() + timeout
        while True:
            try:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                break
            except (BlockingIOError, PermissionError) as exc:
                if time.monotonic() >= deadline:
                    raise SelectionError(f"Timed out waiting for extensions lock: {lock_path}") from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            else:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(descriptor)


def _assert_no_dependents(install_dir: Path, service_id: str) -> None:
    dependents = _enabled_dependents(install_dir, service_id)
    if dependents:
        raise SelectionError(
            f"These enabled extensions depend on {service_id}: {', '.join(dependents)}. "
            "Disable them first."
        )


def run(action: str, install_dir: Path, service_id: str, timeout: float = 15.0) -> str:
    if SERVICE_ID.fullmatch(service_id) is None:
        raise SelectionError("Invalid service id")
    if timeout <= 0 or timeout > 120:
        raise SelectionError("Invalid lock timeout")
    with _selection_lock(install_dir, timeout):
        directory = _target_dir(install_dir, service_id)
        _assert_no_dependents(install_dir, service_id)
        enabled = directory / "compose.yaml"
        disabled = directory / "compose.yaml.disabled"
        try:
            enabled_stat = enabled.lstat()
        except FileNotFoundError:
            enabled_stat = None
        try:
            disabled_stat = disabled.lstat()
        except FileNotFoundError:
            disabled_stat = None
        if enabled_stat is not None and not stat.S_ISREG(enabled_stat.st_mode):
            raise SelectionError(f"Invalid selected Compose file: {enabled}")
        if disabled_stat is not None and not stat.S_ISREG(disabled_stat.st_mode):
            raise SelectionError(f"Invalid disabled Compose file: {disabled}")
        if enabled_stat is not None and disabled_stat is not None:
            raise SelectionError(f"Conflicting Compose selection files for {service_id}")
        if enabled_stat is None:
            if disabled_stat is not None:
                return "already-disabled"
            raise SelectionError(f"No Compose selection file for {service_id}")
        if action == "check-disable":
            return "ready"
        cache = install_dir / ".compose-flags"
        try:
            cache.unlink(missing_ok=True)
            os.replace(enabled, disabled)
        except OSError as exc:
            raise SelectionError(f"Could not disable {service_id}; selected file remains recoverable") from exc
        return "disabled"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check-disable", "disable"))
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--service-id", required=True)
    parser.add_argument("--lock-timeout", type=float, default=15.0)
    args = parser.parse_args()
    try:
        print(run(args.action, args.install_dir, args.service_id, args.lock_timeout))
    except SelectionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
