#!/usr/bin/env python3
"""ODS start-up step for the Open WebUI container.

openwebui-entrypoint.sh runs it before Open WebUI's own start command, as the
container's user, with Open WebUI's data directory mounted. Open WebUI is not
running yet, so nothing writes to its database while this runs.

Open WebUI migrates its SQLite database when a new version first starts, and
those migrations cannot be undone. This step:

1. refuses to start when Open WebUI would damage the database: the image is
   older than the version that last ran here (a rollback), the database was
   migrated by a newer Open WebUI, or user accounts have email addresses that
   differ only in case, which one migration rejects partway through
   (revision f0bd01a18a3d);
2. when the Open WebUI version differs from the one recorded beside the
   database, copies the database to ods-backups/ first, keeping the two newest
   copies, and records the new version.

It reports on stderr. A refusal exits with status 1 before Open WebUI starts
and leaves the database and the recorded version as they were. Standard
library only: it runs on the Python that the Open WebUI image ships.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DATABASE = "webui.db"
VERSION_MARKER = ".ods-open-webui-version"
BACKUP_DIR = "ods-backups"
BACKUPS_KEPT = 2
PARTIAL_PREFIX = ".partial-"
# Files SQLite keeps beside a database. A write-ahead log holds committed
# pages not yet written back, and a rollback journal left by an interrupted
# write must be replayed, so both travel with the copy. The shared-memory
# index is rebuilt from the log and is not copied.
LOGS = ("-wal", "-journal")
SHARED_MEMORY = "-shm"
# Relative to the image's /app: the version file Open WebUI reports, and the
# Alembic revisions it can migrate a database to.
PACKAGE_FILE = "package.json"
MIGRATIONS = "backend/open_webui/migrations/versions"
# The migration that adds a unique index on lower(email). It raises, and Open
# WebUI stops partway through the upgrade, when two accounts differ only in case.
UNIQUE_EMAIL_REVISION = "f0bd01a18a3d"
UNIQUE_EMAIL_INDEX = "uq_user_email_lower"
REVISION = re.compile(r"""^revision(?:\s*:[^=\n]*)?\s*=\s*['"]([0-9A-Za-z_]+)['"]""", re.M)
DOCS = "ods/extensions/services/open-webui/README.md (Upgrades and backups)"


def report(message: str) -> None:
    print(f"ODS: {message}", file=sys.stderr)


def installed_version(app_dir: Path) -> str:
    """The version of the Open WebUI in this image, from the file it reports."""
    return json.loads((app_dir / PACKAGE_FILE).read_text(encoding="utf-8"))["version"]


def recorded_version(data_dir: Path) -> str | None:
    """The Open WebUI version that last started with this data directory."""
    try:
        return (data_dir / VERSION_MARKER).read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None


def version_key(version: str) -> tuple[int, ...] | None:
    parts = version.split(".")
    return tuple(int(part) for part in parts) if all(part.isdigit() for part in parts) else None


def image_revisions(migrations: Path) -> set[str]:
    """Every Alembic revision this image's Open WebUI knows."""
    revisions = set()
    for script in migrations.glob("*.py"):
        found = REVISION.search(script.read_text(encoding="utf-8"))
        if found:
            revisions.add(found.group(1))
    if not revisions:
        raise RuntimeError(f"no Open WebUI migrations found in {migrations}")
    return revisions


def read_only(database: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)


def has(connection: sqlite3.Connection, kind: str, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?", (kind, name)).fetchone() is not None


def database_revisions(connection: sqlite3.Connection) -> set[str] | None:
    if not has(connection, "table", "alembic_version"):
        return None
    return {row[0] for row in connection.execute("SELECT version_num FROM alembic_version")}


def duplicate_emails(connection: sqlite3.Connection) -> list[tuple[str, int]]:
    """Addresses held by more than one account once case is ignored, as the migration counts them."""
    if not has(connection, "table", "user"):
        return []
    return connection.execute(
        'SELECT lower(email), count(*) FROM "user" WHERE email IS NOT NULL '
        "GROUP BY lower(email) HAVING count(*) > 1 ORDER BY lower(email)").fetchall()


def saved_copies(data_dir: Path) -> list[str]:
    directory = data_dir / BACKUP_DIR
    if not directory.is_dir():
        return []
    return sorted(path.name for path in directory.glob("*-open-webui-*.db") if not path.name.startswith("."))


def refuse(message: str, data_dir: Path) -> None:
    copies = saved_copies(data_dir)
    listing = ", ".join(copies) if copies else "none"
    raise SystemExit(
        f"ODS: Open WebUI was not started. {message}\n"
        f"ODS: copies saved before earlier upgrades in {data_dir / BACKUP_DIR}: {listing}\n"
        f"ODS: see {DOCS}")


def is_older(installed: str, recorded: str | None) -> bool:
    installed_key = version_key(installed)
    recorded_key = version_key(recorded) if recorded else None
    return installed_key is not None and recorded_key is not None and installed_key < recorded_key


def preflight(data_dir: Path, app_dir: Path, installed: str, recorded: str | None) -> None:
    """Refuse a start that would damage the database; read-only."""
    database = data_dir / DATABASE
    if not database.exists():
        return
    if is_older(installed, recorded):
        refuse(
            f"This data was last used by Open WebUI {recorded}, and this image is the older "
            f"{installed}. Open WebUI cannot undo the database changes {recorded} made. Either pin "
            f"Open WebUI {recorded} again, or restore a copy saved before {recorded} first started "
            f"and then delete {data_dir / VERSION_MARKER}.", data_dir)
    known = image_revisions(app_dir / MIGRATIONS)
    try:
        with closing(read_only(database)) as connection:
            revisions = database_revisions(connection)
            unique_index = has(connection, "index", UNIQUE_EMAIL_INDEX)
            duplicates = duplicate_emails(connection) if UNIQUE_EMAIL_REVISION in known and not unique_index else []
    except sqlite3.Error as error:
        error.add_note(f"ODS: could not read {database} before Open WebUI {installed} starts")
        raise
    unknown = sorted((revisions or set()) - known)
    if unknown:
        refuse(
            f"{database} was migrated by a newer Open WebUI (database revision "
            f"{', '.join(unknown)}), which Open WebUI {installed} cannot use. Pin the newer "
            f"Open WebUI again, or restore a copy saved before that upgrade.", data_dir)
    if duplicates:
        accounts = ", ".join(f"{email} ({count} accounts)" for email, count in duplicates)
        refuse(
            f"Open WebUI {installed} requires a different email address for every account, and "
            f"its upgrade stops partway through when two differ only in case: {accounts}. Start "
            f"the previous Open WebUI version, keep one account per address (move or delete the "
            f"others' chats first, then delete those accounts in Admin Panel > Users), and update "
            f"again. Nothing was changed.", data_dir)


def remove_set(base: Path) -> None:
    for suffix in ("",) + LOGS + (SHARED_MEMORY,):
        Path(f"{base}{suffix}").unlink(missing_ok=True)


def prune(directory: Path) -> None:
    copies = sorted(path for path in directory.glob("*-open-webui-*.db") if not path.name.startswith("."))
    for old in copies[:-BACKUPS_KEPT]:
        old.unlink()
        report(f"removed the older copy {old}")


def backup_database(data_dir: Path, previous: str | None, now: datetime) -> Path | None:
    """Copy webui.db aside as one file that opens on its own; keep the newest two."""
    database = data_dir / DATABASE
    if not database.exists():
        return None
    directory = data_dir / BACKUP_DIR
    if directory.is_dir():
        for leftover in directory.glob(f"{PARTIAL_PREFIX}*"):
            leftover.unlink()  # from a copy that was interrupted
    sources = [Path(f"{database}{suffix}") for suffix in ("",) + LOGS]
    sources = [source for source in sources if source.exists()]
    needed = sum(source.stat().st_size for source in sources)
    free = shutil.disk_usage(data_dir).free
    if free < needed:
        refuse(
            f"Copying {database} before the upgrade needs {needed} bytes in {data_dir}, and "
            f"{free} are free. Free some space and start Open WebUI again.", data_dir)
    directory.mkdir(mode=0o700, exist_ok=True)
    # ISO time first, so names sort by age; then the version being replaced.
    stamp = now.strftime("%Y-%m-%dT%H-%M-%S-") + f"{now.microsecond // 1000:03d}Z"
    name = f"{stamp}-open-webui-{previous or 'unrecorded'}.db"
    partial = directory / f"{PARTIAL_PREFIX}{name}"
    for source in sources:
        shutil.copyfile(source, f"{partial}{source.name[len(DATABASE):]}")
    # Fold what the copied log holds into the copy, so restoring it is a
    # single file: SQLite replays a write-ahead log or rollback journal that
    # sits beside the database it opens, and leaving WAL mode writes the log
    # back and removes it.
    with closing(sqlite3.connect(partial)) as copy:
        copy.execute("SELECT count(*) FROM sqlite_master").fetchone()
        mode = copy.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
    if mode != "delete":
        raise RuntimeError(f"could not make {partial} a standalone database (journal mode {mode})")
    for suffix in LOGS + (SHARED_MEMORY,):
        Path(f"{partial}{suffix}").unlink(missing_ok=True)
    target = directory / name
    os.replace(partial, target)
    prune(directory)
    return target


def record_version(data_dir: Path, version: str) -> None:
    marker = data_dir / VERSION_MARKER
    temporary = marker.with_name(f"{VERSION_MARKER}.tmp")
    temporary.write_text(f"{version}\n", encoding="utf-8")
    os.replace(temporary, marker)


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=Path("/app/backend/data"),
                        help="Open WebUI's data directory (default: %(default)s)")
    parser.add_argument("--app-dir", type=Path, default=Path("/app"),
                        help="the Open WebUI installation in the image (default: %(default)s)")
    args = parser.parse_args(argv)
    data_dir, app_dir = args.data_dir, args.app_dir

    installed = installed_version(app_dir)
    recorded = recorded_version(data_dir)
    preflight(data_dir, app_dir, installed, recorded)
    if recorded == installed:
        return 0
    saved = backup_database(data_dir, recorded, now or datetime.now(timezone.utc))
    if saved:
        report(f"saved Open WebUI's database to {saved} before Open WebUI {installed} migrates it")
    record_version(data_dir, installed)
    report(f"Open WebUI {installed} starts with this data" + (f" (previously {recorded})" if recorded else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
