#!/usr/bin/env python3
"""Fail-closed, cross-process selection guard for ``ods enable/disable``.

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
import shutil
import stat
import subprocess
import sys
import tempfile
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


def _read_bounded_file(path: Path) -> bytes:
    """Read a bounded regular file without following its final symlink."""
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
        return raw
    except OSError as exc:
        raise SelectionError(f"Cannot inspect selected file: {path}") from exc


def _read_yaml(path: Path) -> object:
    try:
        import yaml
    except ImportError as exc:
        raise SelectionError("PyYAML is required to inspect extension dependencies") from exc
    try:
        return yaml.safe_load(_read_bounded_file(path).decode("utf-8"))
    except (UnicodeError, yaml.YAMLError) as exc:
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


def _compose_details(path: Path) -> tuple[set[str], set[str]]:
    document = _read_yaml(path)
    services = document.get("services") if isinstance(document, dict) else None
    if not isinstance(services, dict):
        raise SelectionError(f"Invalid selected Compose services: {path}")
    service_names = set(services)
    if any(not isinstance(name, str) or not name for name in service_names):
        raise SelectionError(f"Invalid selected Compose service name: {path}")
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
    return service_names, dependencies


def _compose_dependencies(path: Path) -> set[str]:
    return _compose_details(path)[1]


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


def _find_target_dir(install_dir: Path, service_id: str) -> Path | None:
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
    return None


def _target_dir(install_dir: Path, service_id: str) -> Path:
    directory = _find_target_dir(install_dir, service_id)
    if directory is not None:
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


def _selection_enabled(directory: Path) -> bool:
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
        raise SelectionError(f"Conflicting Compose selection files: {directory.name}")
    return enabled_stat is not None


def _assert_prerequisites_enabled(
    install_dir: Path, service_id: str, directory: Path, compose_path: Path,
    core_services: set[str],
) -> None:
    manifest_deps = _manifest_dependencies(directory)
    fragment_services, compose_deps = _compose_details(compose_path)
    missing: list[str] = []
    for dep in sorted(manifest_deps | (compose_deps - fragment_services)):
        if dep == service_id:
            raise SelectionError(f"Circular dependency for {service_id}")
        if dep in fragment_services:
            continue
        # Core services can be profiled out in gateway-only mode; their
        # manifest category is a CLI policy. A user shadow must not inherit it.
        if dep in core_services:
            try:
                (install_dir / "data" / "user-extensions" / dep).lstat()
            except FileNotFoundError:
                continue
        dep_dir = _find_target_dir(install_dir, dep)
        if dep_dir is None:
            # Compose can refer to a base service outside the extension tree;
            # the Compose resolver validates that graph. Manifest deps name
            # extensions and must resolve here.
            if dep in manifest_deps:
                missing.append(dep)
            continue
        if not _selection_enabled(dep_dir):
            missing.append(dep)
    if missing:
        raise SelectionError(
            f"Cannot enable {service_id}; disabled prerequisites: {', '.join(missing)}"
        )


def _refresh_compose_flags(
    install_dir: Path, tier: str, gpu_backend: str, gpu_count: str, ods_mode: str,
) -> None:
    """Rebuild the persisted stack while the shared selection lock is held."""
    cache = install_dir / ".compose-flags"
    try:
        cache.unlink(missing_ok=True)
    except OSError as exc:
        raise SelectionError(f"Cannot invalidate Compose cache: {cache}") from exc
    resolver = install_dir / "scripts" / "resolve-compose-stack.sh"
    if not resolver.is_file() or not os.access(resolver, os.X_OK):
        return
    bash = shutil.which("bash")
    if bash is None:
        print("WARNING: Could not regenerate the compose stack cache: bash is missing", file=sys.stderr)
        return
    try:
        result = subprocess.run(
            [bash, str(resolver), "--script-dir", str(install_dir),
             "--tier", tier, "--gpu-backend", gpu_backend,
             "--gpu-count", gpu_count, "--ods-mode", ods_mode],
            cwd=install_dir, capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"WARNING: Could not regenerate the compose stack cache: {exc}", file=sys.stderr)
        return
    if result.returncode != 0 or not result.stdout.strip().startswith("-f "):
        print("WARNING: Could not regenerate the compose stack cache; 'ods start' may fail until this is resolved.", file=sys.stderr)
        if result.stderr.strip():
            print(result.stderr.rstrip(), file=sys.stderr)
        return
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", prefix=".compose-flags-",
            dir=install_dir, delete=False,
        ) as stream:
            temporary = stream.name
            stream.write(result.stdout)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, cache)
    except OSError as exc:
        raise SelectionError(f"Cannot save Compose cache: {cache}") from exc
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    for line in result.stderr.splitlines():
        if line.startswith("WARNING:"):
            print(line, file=sys.stderr)


def run(
    action: str, install_dir: Path, service_id: str, timeout: float = 15.0,
    core_services: set[str] | None = None,
    tier: str = "1", gpu_backend: str = "nvidia", gpu_count: str = "1",
    ods_mode: str = "local",
) -> str:
    if action not in ("check-disable", "disable", "enable"):
        raise SelectionError("Invalid selection action")
    if SERVICE_ID.fullmatch(service_id) is None:
        raise SelectionError("Invalid service id")
    if timeout <= 0 or timeout > 120:
        raise SelectionError("Invalid lock timeout")
    core_services = set(core_services or ())
    if any(SERVICE_ID.fullmatch(core) is None for core in core_services):
        raise SelectionError("Invalid core service id")
    with _selection_lock(install_dir, timeout):
        directory = _target_dir(install_dir, service_id)
        if action != "enable":
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
            if action != "enable" or _read_bounded_file(enabled) != _read_bounded_file(disabled):
                raise SelectionError(f"Conflicting Compose selection files for {service_id}")
            _assert_prerequisites_enabled(install_dir, service_id, directory, enabled,
                                          core_services)
            try:
                disabled.unlink()
            except OSError as exc:
                raise SelectionError(f"Could not remove stale disabled marker for {service_id}") from exc
            disabled_stat = None
        cache = install_dir / ".compose-flags"
        if action == "enable":
            if enabled_stat is not None:
                _assert_prerequisites_enabled(install_dir, service_id, directory, enabled,
                                              core_services)
                _refresh_compose_flags(install_dir, tier, gpu_backend, gpu_count, ods_mode)
                return "already-enabled"
            if disabled_stat is None:
                raise SelectionError(f"No Compose selection file for {service_id}")
            _assert_prerequisites_enabled(install_dir, service_id, directory, disabled,
                                          core_services)
            try:
                cache.unlink(missing_ok=True)
                os.replace(disabled, enabled)
            except OSError as exc:
                raise SelectionError(f"Could not enable {service_id}; disabled file remains recoverable") from exc
            _refresh_compose_flags(install_dir, tier, gpu_backend, gpu_count, ods_mode)
            return "enabled"
        if enabled_stat is None:
            if disabled_stat is not None:
                return "already-disabled"
            raise SelectionError(f"No Compose selection file for {service_id}")
        if action == "check-disable":
            return "ready"
        try:
            cache.unlink(missing_ok=True)
            os.replace(enabled, disabled)
        except OSError as exc:
            raise SelectionError(f"Could not disable {service_id}; selected file remains recoverable") from exc
        return "disabled"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check-disable", "disable", "enable"))
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--service-id", required=True)
    parser.add_argument("--lock-timeout", type=float, default=15.0)
    parser.add_argument("--core-service", action="append", default=[])
    parser.add_argument("--tier", default="1")
    parser.add_argument("--gpu-backend", default="nvidia")
    parser.add_argument("--gpu-count", default="1")
    parser.add_argument("--ods-mode", default="local")
    args = parser.parse_args()
    try:
        print(run(args.action, args.install_dir, args.service_id, args.lock_timeout,
                  set(args.core_service), args.tier, args.gpu_backend,
                  args.gpu_count, args.ods_mode))
    except SelectionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
