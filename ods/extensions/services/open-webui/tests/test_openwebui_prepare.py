"""Contracts for openwebui-prepare.py, the start-up step that backs up Open
WebUI's database before an upgrade and refuses upgrades that would leave it
half-migrated, and for its wiring into the Open WebUI service."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

SERVICE = Path(__file__).resolve().parents[1]
ODS = SERVICE.parents[2]
SCRIPT = SERVICE / "openwebui-prepare.py"
WRAPPER = SERVICE / "openwebui-entrypoint.sh"
PIN = ("ghcr.io/open-webui/open-webui:v0.11.4"
       "@sha256:9591b13f13843c7721c2b8eaf7382846c81b3ffe126526d1888d1fed50c6a33f")

SPEC = importlib.util.spec_from_file_location("openwebui_prepare", SCRIPT)
assert SPEC and SPEC.loader
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)

V072_HEAD = "c440947495f3"
V0114_HEAD = "d4c1a8e37b62"
NOW = datetime(2026, 10, 4, 17, 15, 0, 123000, tzinfo=timezone.utc)


def make_image(root: Path, version: str, revisions: list[str]) -> Path:
    """An /app tree with the files the step reads: package.json and migrations."""
    app = root / "app"
    migrations = app / "backend/open_webui/migrations/versions"
    migrations.mkdir(parents=True)
    (app / "package.json").write_text(json.dumps({"name": "open-webui", "version": version}))
    for index, revision in enumerate(revisions):
        # Both spellings Open WebUI's migrations use.
        line = f"revision: str = '{revision}'" if index % 2 else f'revision = "{revision}"'
        (migrations / f"{revision}_step.py").write_text(
            f'"""step\n\nRevision ID: {revision}\n"""\n{line}\ndown_revision = None\n')
    return app


def new_image(root: Path) -> Path:
    return make_image(root, "0.11.4", [V072_HEAD, prepare.UNIQUE_EMAIL_REVISION, V0114_HEAD])


def old_image(root: Path) -> Path:
    return make_image(root, "0.7.2", ["7e5b5dc7342b", V072_HEAD])


def make_database(path: Path, revision: str = V072_HEAD, emails: tuple[str, ...] = (),
                  unique_index: bool = False) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        connection.execute('CREATE TABLE "user" (id TEXT PRIMARY KEY, email TEXT)')
        connection.execute("CREATE TABLE chat (id TEXT PRIMARY KEY, title TEXT)")
        connection.execute("INSERT INTO chat VALUES ('c1', 'kept')")
        for number, email in enumerate(emails):
            connection.execute('INSERT INTO "user" VALUES (?, ?)', (f"u{number}", email))
        if unique_index:
            connection.execute(f'CREATE UNIQUE INDEX {prepare.UNIQUE_EMAIL_INDEX} ON "user" (lower(email))')
        connection.commit()


def data_dir(root: Path, recorded: str | None = None, database: bool = True, **database_options) -> Path:
    data = root / "data"
    data.mkdir(parents=True)
    if database:
        make_database(data / prepare.DATABASE, **database_options)
    if recorded:
        (data / prepare.VERSION_MARKER).write_text(f"{recorded}\n")
    return data


def run(data: Path, app: Path, now: datetime = NOW) -> int:
    return prepare.main(["--data-dir", str(data), "--app-dir", str(app)], now=now)


def copies(data: Path) -> list[str]:
    return sorted(path.name for path in (data / prepare.BACKUP_DIR).iterdir())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def titles(database: Path) -> list[str]:
    with closing(sqlite3.connect(database)) as connection:
        return [row[0] for row in connection.execute("SELECT title FROM chat ORDER BY id")]


# ---------------------------------------------------------------- backups

def test_a_fresh_install_records_the_version_without_a_backup(tmp_path):
    data = data_dir(tmp_path, database=False)
    assert run(data, new_image(tmp_path)) == 0
    assert (data / prepare.VERSION_MARKER).read_text() == "0.11.4\n"
    assert not (data / prepare.BACKUP_DIR).exists()


def test_the_same_version_starts_without_copying_or_rewriting(tmp_path):
    data = data_dir(tmp_path, recorded="0.11.4", revision=V0114_HEAD, unique_index=True)
    marker = data / prepare.VERSION_MARKER
    before = marker.stat().st_mtime_ns
    assert run(data, new_image(tmp_path)) == 0
    assert not (data / prepare.BACKUP_DIR).exists()
    assert marker.stat().st_mtime_ns == before


def test_an_upgrade_copies_the_database_named_after_the_version_it_replaces(tmp_path, capsys):
    data = data_dir(tmp_path, recorded="0.11.3", revision=V0114_HEAD, unique_index=True)
    original = digest(data / prepare.DATABASE)
    assert run(data, new_image(tmp_path)) == 0
    name = "2026-10-04T17-15-00-123Z-open-webui-0.11.3.db"
    assert copies(data) == [name]
    assert titles(data / prepare.BACKUP_DIR / name) == ["kept"]
    assert digest(data / prepare.DATABASE) == original
    assert (data / prepare.VERSION_MARKER).read_text() == "0.11.4\n"
    err = capsys.readouterr().err
    assert f"saved Open WebUI's database to {data / prepare.BACKUP_DIR / name}" in err
    assert "(previously 0.11.3)" in err


def test_a_database_from_before_odss_marker_is_saved_as_unrecorded(tmp_path):
    # Installs updated from ODS releases that pinned Open WebUI 0.7.2.
    data = data_dir(tmp_path)
    assert run(data, new_image(tmp_path)) == 0
    assert copies(data) == ["2026-10-04T17-15-00-123Z-open-webui-unrecorded.db"]


def test_committed_pages_in_the_write_ahead_log_are_folded_into_one_file(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    build = tmp_path / "build.db"
    with closing(sqlite3.connect(build)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        writer.execute("INSERT INTO alembic_version VALUES (?)", (V072_HEAD,))
        writer.execute("CREATE TABLE chat (id TEXT PRIMARY KEY, title TEXT)")
        writer.execute("INSERT INTO chat VALUES ('c1', 'only in the log')")
        writer.commit()
        # What a container stopped before a checkpoint leaves behind.
        shutil.copyfile(build, data / prepare.DATABASE)
        shutil.copyfile(f"{build}-wal", data / f"{prepare.DATABASE}-wal")
    database_bytes = digest(data / prepare.DATABASE)
    log_bytes = digest(data / f"{prepare.DATABASE}-wal")

    assert run(data, new_image(tmp_path)) == 0
    [name] = copies(data)
    assert name.endswith("-open-webui-unrecorded.db")
    assert titles(data / prepare.BACKUP_DIR / name) == ["only in the log"]
    # The original stays exactly as Open WebUI left it.
    assert digest(data / prepare.DATABASE) == database_bytes
    assert digest(data / f"{prepare.DATABASE}-wal") == log_bytes


def test_a_leftover_rollback_journal_is_not_left_beside_the_copy(tmp_path):
    data = data_dir(tmp_path)
    (data / f"{prepare.DATABASE}-journal").write_bytes(b"")
    assert run(data, new_image(tmp_path)) == 0
    [name] = copies(data)
    assert titles(data / prepare.BACKUP_DIR / name) == ["kept"]


def test_only_the_two_newest_copies_are_kept(tmp_path):
    data = data_dir(tmp_path, revision=V0114_HEAD, unique_index=True)
    upgrades = [("0.11.1", "0.11.2"), ("0.11.2", "0.11.3"), ("0.11.3", "0.11.4")]
    for day, (previous, installed) in enumerate(upgrades):
        (data / prepare.VERSION_MARKER).write_text(previous)
        app = make_image(tmp_path / installed, installed, [V072_HEAD, prepare.UNIQUE_EMAIL_REVISION, V0114_HEAD])
        assert run(data, app, now=NOW + timedelta(days=day)) == 0
    assert copies(data) == [
        "2026-10-05T17-15-00-123Z-open-webui-0.11.2.db",
        "2026-10-06T17-15-00-123Z-open-webui-0.11.3.db",
    ]


def test_an_interrupted_copy_is_cleared_and_the_marker_waits_for_a_complete_one(tmp_path, monkeypatch):
    data = data_dir(tmp_path, recorded="0.11.3", revision=V0114_HEAD, unique_index=True)
    app = new_image(tmp_path)

    def fail(source, target):
        Path(target).write_bytes(b"partial")
        raise OSError("disk went away")

    monkeypatch.setattr(prepare.shutil, "copyfile", fail)
    with pytest.raises(OSError, match="disk went away"):
        run(data, app)
    assert (data / prepare.VERSION_MARKER).read_text() == "0.11.3\n"
    monkeypatch.undo()
    assert run(data, app) == 0
    assert copies(data) == ["2026-10-04T17-15-00-123Z-open-webui-0.11.3.db"]


def test_too_little_space_for_the_copy_refuses_before_anything_changes(tmp_path, monkeypatch):
    data = data_dir(tmp_path, recorded="0.11.3", revision=V0114_HEAD, unique_index=True)
    monkeypatch.setattr(prepare.shutil, "disk_usage", lambda path: SimpleNamespace(total=10, used=9, free=1))
    with pytest.raises(SystemExit) as refused:
        run(data, new_image(tmp_path))
    assert "Free some space" in str(refused.value.code)
    assert not (data / prepare.BACKUP_DIR).exists()
    assert (data / prepare.VERSION_MARKER).read_text() == "0.11.3\n"


def test_the_version_comes_from_the_image_not_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBUI_BUILD_VERSION", "9.9.9")
    monkeypatch.setenv("VERSION", "9.9.9")
    assert prepare.installed_version(new_image(tmp_path)) == "0.11.4"


# ---------------------------------------------------------------- refusals

def test_accounts_whose_emails_differ_only_in_case_are_refused_before_the_upgrade(tmp_path):
    data = data_dir(tmp_path, emails=("Sam@Example.test", "sam@example.test", "kim@example.test"))
    database = digest(data / prepare.DATABASE)
    with pytest.raises(SystemExit) as refused:
        run(data, new_image(tmp_path))
    message = str(refused.value.code)
    assert "Open WebUI was not started" in message
    assert "sam@example.test (2 accounts)" in message
    assert "kim@example.test" not in message
    assert "Admin Panel > Users" in message
    assert digest(data / prepare.DATABASE) == database
    assert not (data / prepare.BACKUP_DIR).exists()
    assert not (data / prepare.VERSION_MARKER).exists()


def test_the_email_check_applies_only_where_the_image_runs_that_migration(tmp_path):
    # An older image does not have the unique-email migration, and a database
    # that already has the index cannot hold such duplicates.
    data = data_dir(tmp_path, emails=("Sam@Example.test", "sam@example.test"))
    assert run(data, old_image(tmp_path)) == 0
    migrated = data_dir(tmp_path / "migrated", recorded="0.11.4", revision=V0114_HEAD, unique_index=True,
                        emails=("sam@example.test", "kim@example.test"))
    assert run(migrated, new_image(tmp_path / "migrated")) == 0


def test_an_older_image_on_data_a_newer_version_used_is_refused(tmp_path):
    data = data_dir(tmp_path, recorded="0.11.4", revision=V0114_HEAD, unique_index=True)
    (data / prepare.BACKUP_DIR).mkdir()
    saved = data / prepare.BACKUP_DIR / "2026-10-01T09-00-00-000Z-open-webui-unrecorded.db"
    make_database(saved)
    with pytest.raises(SystemExit) as refused:
        run(data, old_image(tmp_path))
    message = str(refused.value.code)
    assert "last used by Open WebUI 0.11.4, and this image is the older 0.7.2" in message
    assert saved.name in message
    assert str(data / prepare.VERSION_MARKER) in message
    assert (data / prepare.VERSION_MARKER).read_text() == "0.11.4\n"
    assert copies(data) == [saved.name]


def test_a_downgrade_is_refused_even_when_the_schema_did_not_change(tmp_path):
    data = data_dir(tmp_path, recorded="0.11.4", revision=V0114_HEAD, unique_index=True)
    app = make_image(tmp_path, "0.11.3", [V072_HEAD, prepare.UNIQUE_EMAIL_REVISION, V0114_HEAD])
    with pytest.raises(SystemExit, match="older 0.11.3"):
        run(data, app)


def test_a_database_migrated_by_a_newer_open_webui_is_refused_without_a_marker(tmp_path):
    data = data_dir(tmp_path, revision=V0114_HEAD, unique_index=True)
    with pytest.raises(SystemExit) as refused:
        run(data, old_image(tmp_path))
    message = str(refused.value.code)
    assert f"database revision {V0114_HEAD}" in message
    assert "which Open WebUI 0.7.2 cannot use" in message
    assert not (data / prepare.VERSION_MARKER).exists()


def test_a_restored_copy_starts_once_the_marker_is_deleted(tmp_path):
    # The documented restore: copy the saved database back, delete the
    # marker, pin the previous image.
    data = data_dir(tmp_path)
    assert run(data, old_image(tmp_path)) == 0
    assert (data / prepare.VERSION_MARKER).read_text() == "0.7.2\n"


def test_missing_migrations_in_the_image_fail_loudly(tmp_path):
    data = data_dir(tmp_path)
    app = new_image(tmp_path)
    shutil.rmtree(app / prepare.MIGRATIONS)
    with pytest.raises(RuntimeError, match="no Open WebUI migrations found"):
        run(data, app)


# ---------------------------------------------------------------- as a program

def test_run_as_a_program_it_reports_on_stderr_only(tmp_path):
    data = data_dir(tmp_path, recorded="0.11.3", revision=V0114_HEAD, unique_index=True)
    app = new_image(tmp_path)
    started = subprocess.run([sys.executable, str(SCRIPT), "--data-dir", str(data), "--app-dir", str(app)],
                             capture_output=True, text=True, check=False)
    assert started.returncode == 0, started.stderr
    assert started.stdout == ""
    assert "ODS: saved Open WebUI's database to" in started.stderr


def test_a_refusal_exits_with_status_1_and_says_why(tmp_path):
    data = data_dir(tmp_path, emails=("Sam@Example.test", "sam@example.test"))
    app = new_image(tmp_path)
    refused = subprocess.run([sys.executable, str(SCRIPT), "--data-dir", str(data), "--app-dir", str(app)],
                             capture_output=True, text=True, check=False)
    assert refused.returncode == 1
    assert "ODS: Open WebUI was not started." in refused.stderr
    assert "Traceback" not in refused.stderr


# ---------------------------------------------------------------- wiring

def service_block(compose: str, service: str = "open-webui") -> str:
    """The lines of one service in a compose file, without parsing YAML."""
    found = re.search(rf"^  {re.escape(service)}:\n(.*?)(?=^  \S|^\S|\Z)", compose, re.M | re.S)
    return found.group(1) if found else ""


def block_value(block: str, key: str) -> str:
    found = re.search(rf"^    {key}: (.*)$", block, re.M)
    assert found, key
    return found.group(1)


def test_compose_runs_the_step_before_the_images_own_start_command():
    block = service_block((ODS / "docker-compose.base.yml").read_text(encoding="utf-8"))
    assert block_value(block, "image") == PIN
    assert json.loads(block_value(block, "entrypoint")) == ["/bin/sh", "/opt/ods/openwebui-entrypoint.sh"]
    # The image's CMD, restated because an entrypoint override drops it.
    assert json.loads(block_value(block, "command")) == ["bash", "start.sh"]
    for mount in (
        "./data/open-webui:/app/backend/data:z",
        "./extensions/services/open-webui/openwebui-entrypoint.sh:/opt/ods/openwebui-entrypoint.sh:ro,z",
        "./extensions/services/open-webui/openwebui-prepare.py:/opt/ods/openwebui-prepare.py:ro,z",
    ):
        assert f"      - {mount}\n" in block
    assert '      ENABLE_PERSISTENT_CONFIG: "false"\n' in block
    assert '      ENABLE_SIGNUP: "false"\n' in block
    # Unchanged: the image's user and port, and the health probe.
    assert not re.search(r"^    (user|working_dir):", block, re.M)
    assert '      - "${BIND_ADDRESS:-127.0.0.1}:${WEBUI_PORT:-3000}:8080"\n' in block
    assert '      test: ["CMD", "curl", "-f", "http://127.0.0.1:8080/health"]\n' in block


@pytest.mark.skipif(sys.platform == "win32", reason="runs the POSIX wrapper with sh")
@pytest.mark.parametrize("status", [0, 1])
def test_the_wrapper_starts_open_webui_only_when_the_step_succeeds(tmp_path, status):
    # A stand-in for the image's python3 that records how the step was run.
    stand_in = tmp_path / "python3"
    stand_in.write_text(f'#!/bin/sh\necho "step $*" >&2\nexit {status}\n')
    stand_in.chmod(0o755)
    environment = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"}
    started = subprocess.run(["sh", str(WRAPPER), "echo", "started"], capture_output=True, text=True,
                             env=environment, check=False)
    assert "step /opt/ods/openwebui-prepare.py" in started.stderr
    assert started.returncode == status
    assert started.stdout == ("" if status else "started\n")


@pytest.mark.skipif(sys.platform == "win32", reason="runs the POSIX wrapper with sh")
def test_the_wrapper_refuses_to_run_without_a_start_command():
    refused = subprocess.run(["sh", str(WRAPPER)], capture_output=True, text=True, check=False)
    assert refused.returncode == 64
    assert "no start command given" in refused.stderr


def test_the_wrapper_runs_the_step_then_hands_over_to_the_start_command():
    wrapper = WRAPPER.read_text(encoding="utf-8")
    assert "\r" not in wrapper and "\r" not in SCRIPT.read_text(encoding="utf-8")
    assert wrapper.startswith("#!/bin/sh\nset -eu\n")
    assert wrapper.index("python3 /opt/ods/openwebui-prepare.py") < wrapper.index('exec "$@"')
    script = SCRIPT.read_text(encoding="utf-8")
    assert 'default=Path("/app/backend/data")' in script
    assert 'default=Path("/app")' in script


def test_the_pin_matches_in_the_lock_file_and_the_installer_pull_list():
    lock = json.loads((ODS / "config/dependency-lock.json").read_text(encoding="utf-8"))
    [entry] = [item for item in lock["entries"] if item["id"] == "base.open-webui"]
    assert entry["value"] == PIN
    assert f'PULL_LIST+=("{PIN}|' in (ODS / "installers/phases/08-images.sh").read_text(encoding="utf-8")


def overlays() -> list[Path]:
    paths = [path for path in ODS.glob("docker-compose.*.yml") if path.name != "docker-compose.base.yml"]
    paths += list((ODS / "installers").glob("*/docker-compose*.yml"))
    paths += list((ODS / "extensions/services").glob("*/compose*.y*ml*"))
    return sorted(path for path in paths if "open-webui:" in path.read_text(encoding="utf-8"))


def test_no_overlay_replaces_the_step_or_odss_settings():
    checked = []
    for path in overlays():
        block = service_block(path.read_text(encoding="utf-8"))
        if not block:
            continue
        checked.append(path.relative_to(ODS).as_posix())
        for key in ("image:", "entrypoint:", "command:", "user:", "working_dir:",
                    "ENABLE_PERSISTENT_CONFIG", "ENABLE_SIGNUP"):
            assert key not in block, f"{path} sets {key} on open-webui"
    # The overlays that change Open WebUI's environment are all still seen.
    for expected in (
        "docker-compose.amd.yml", "docker-compose.nvidia.yml", "docker-compose.external-llm.yml",
        "docker-compose.lemonade-external.yml", "docker-compose.gateway-only.yml", "docker-compose.tier0.yml",
        "installers/macos/docker-compose.macos.yml", "installers/windows/docker-compose.windows-amd.yml",
        "extensions/services/pixel-edge/compose.yaml.disabled",
    ):
        assert expected in checked
