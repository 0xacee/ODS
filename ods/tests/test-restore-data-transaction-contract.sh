#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT_DIR/ods/ods-restore.sh"

grep -q 'local staging_dir="\$ODS_DIR/.data.restore.\$\$"' "$SCRIPT" \
    || { echo "FAIL: data restore has no staging tree" >&2; exit 1; }
grep -q 'local -a restored_dirs=()' "$SCRIPT" \
    || { echo "FAIL: data restore does not track activated paths" >&2; exit 1; }
grep -q 'rolling back restored user data' "$SCRIPT" \
    || { echo "FAIL: later activation failures do not roll back earlier paths" >&2; exit 1; }
grep -q 'Failed to stage \$dir; live user data was left unchanged.' "$SCRIPT" \
    || { echo "FAIL: staging failure is not fail-closed" >&2; exit 1; }

echo "PASS: user-data restore stages and rolls back as one transaction"
