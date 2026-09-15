#!/usr/bin/env bash
# ============================================================================
# Regression test for ods-restore archive path traversal validation
# ============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

export ODS_DIR="$tmpdir/ods"
export BACKUP_ROOT="$tmpdir/backups"
mkdir -p "$ODS_DIR" "$BACKUP_ROOT"

# Create helper to test extraction validation regex directly
check_archive_traversal() {
    local archive="$1"
    tar -tzf "$archive" 2>/dev/null | grep -qE '(^/|^\.\.(/|$)|/\.\.(/|$))'
}

# 1. Valid archive
valid_tar="$tmpdir/valid.tar.gz"
mkdir -p "$tmpdir/content/data"
echo "hello" > "$tmpdir/content/data/valid..name.txt"
tar -czf "$valid_tar" -C "$tmpdir/content" data
if check_archive_traversal "$valid_tar"; then
    echo "FAIL: valid archive was falsely flagged as traversal" >&2
    exit 1
fi

# 2. Archive containing leading ../
leading_tar="$tmpdir/leading.tar.gz"
(
    cd "$tmpdir"
    mkdir -p sub
    echo "test" > sub/file.txt
    tar -czf "$leading_tar" sub/file.txt
)
# Inject ../ into tar stream
python3 -c "
import tarfile, io
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode='w:gz') as tar:
    info = tarfile.TarInfo(name='../escaped.txt')
    info.size = 4
    tar.addfile(info, io.BytesIO(b'test'))
open('$tmpdir/traversal_leading.tar.gz', 'wb').write(buf.getvalue())
"
if ! check_archive_traversal "$tmpdir/traversal_leading.tar.gz"; then
    echo "FAIL: leading ../ traversal was not detected" >&2
    exit 1
fi

# 3. Archive containing trailing /..
python3 -c "
import tarfile, io
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode='w:gz') as tar:
    info = tarfile.TarInfo(name='data/..')
    info.type = tarfile.DIRTYPE
    tar.addfile(info)
open('$tmpdir/traversal_trailing.tar.gz', 'wb').write(buf.getvalue())
"
if ! check_archive_traversal "$tmpdir/traversal_trailing.tar.gz"; then
    echo "FAIL: trailing /.. traversal was not detected" >&2
    exit 1
fi

# 4. Archive containing exact ..
python3 -c "
import tarfile, io
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode='w:gz') as tar:
    info = tarfile.TarInfo(name='..')
    info.type = tarfile.DIRTYPE
    tar.addfile(info)
open('$tmpdir/traversal_exact.tar.gz', 'wb').write(buf.getvalue())
"
if ! check_archive_traversal "$tmpdir/traversal_exact.tar.gz"; then
    echo "FAIL: exact .. traversal was not detected" >&2
    exit 1
fi

echo "[PASS] test-restore-traversal-guard"
