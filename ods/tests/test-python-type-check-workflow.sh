#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW="$ROOT_DIR/../.github/workflows/type-check-python.yml"

fail() {
    printf 'FAIL: %s\n' "$1" >&2
    exit 1
}

[[ -f "$WORKFLOW" ]] || fail "Python type-check workflow is missing"

mypy_job="$(awk '
    /^  mypy:/ { in_job = 1 }
    in_job && /^  [[:alnum:]_-]+:/ && $0 !~ /^  mypy:/ { exit }
    in_job { print }
' "$WORKFLOW")"

[[ -n "$mypy_job" ]] || fail "mypy job is missing"

for step in \
    "Type check dashboard-api" \
    "Type check token-spy" \
    "Type check privacy-shield" \
    "Type check scripts"; do
    grep -qF -- "- name: $step" <<< "$mypy_job" \
        || fail "$step step is missing"
done

if grep -Eq '^[[:space:]]+continue-on-error:[[:space:]]*true([[:space:]]|$)' <<< "$mypy_job"; then
    fail "mypy job allows a type-check failure to pass"
fi

[[ "$(grep -c 'check-mypy-regressions.py' <<< "$mypy_job")" -eq 4 ]] \
    || fail "every type-check surface must run through the regression gate"

grep -qF 'pip install "mypy==2.3.1"' <<< "$mypy_job" \
    || fail "mypy must be pinned to the version used by the diagnostic baseline"

printf 'PASS: every Python type-check step is merge-blocking\n'
