#!/usr/bin/env bash
# A failure in a phase that only checks the host and chooses a route (01, 02,
# 02b) says nothing was changed and an existing install keeps working; a
# failure after ODS files change keeps the partial-state guidance. Both end
# with the Discord help line.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { echo "FAIL: $*" >&2; exit 1; }

body="$(awk '/^cleanup_on_error\(\) \{/ { emit = 1 }
    emit { print }
    emit && /^}$/ { exit }' "$ROOT/install-core.sh")"
[[ -n "$body" ]] || fail "cleanup_on_error was not found in install-core.sh"

failure_output() {
    ( set +e; eval "$body"; INSTALL_PHASE="$1"; INSTALL_DIR=/opt/ods; LOG_FILE=/tmp/ods.log
      false; cleanup_on_error ) 2>&1 || true
}

for phase in 01-preflight 02-detection 02b-external-services; do
    output="$(failure_output "$phase")"
    grep -qF "The install stopped before changing any ODS files or services." <<<"$output" \
        || fail "$phase did not say nothing was changed: $output"
    grep -qF "Partial state may exist" <<<"$output" && fail "$phase still warned about partial state"
    grep -qF "https://discord.gg/4ntNp9MAwC" <<<"$output" || fail "$phase lost the help line"
done

for phase in 03-features 06-directories 11-services; do
    output="$(failure_output "$phase")"
    grep -qF "Partial state may exist at:" <<<"$output" || fail "$phase lost the partial-state guidance: $output"
    grep -qF "stopped before changing" <<<"$output" && fail "$phase claimed nothing was changed"
    grep -qF "https://discord.gg/4ntNp9MAwC" <<<"$output" || fail "$phase lost the help line"
done

echo "PASS: install failures say whether anything changed, and point at help"
