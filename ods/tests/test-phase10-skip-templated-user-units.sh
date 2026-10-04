#!/usr/bin/env bash
# Phase 10 (AMD tuning) used to copy scripts/systemd/*.{service,timer} into
# the user systemd dir and enable maintenance timers. Copying raw templated
# system units (ods-host-agent, ods-ap-mode, ods-mdns) leaked broken units
# into the user scope, and every timer it enabled served only the removed
# legacy OpenClaw extension. The phase now installs no user units at all; on
# an upgrade it retires the legacy session-cleanup units an older install
# copied there and leaves memory-shepherd timers as the owner configured them.
# This extracts the real retirement block from the phase and runs it.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHASE="${ODS_PHASE10_UNDER_TEST:-$ROOT_DIR/installers/phases/10-amd-tuning.sh}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

fail() { echo "[FAIL] $*" >&2; exit 1; }
pass() { echo "[PASS] $*"; }

[[ -f "$PHASE" ]] || fail "missing $PHASE"

# No unit is copied from scripts/systemd and no timer is enabled any more, so
# a templated system unit can never reach the user scope.
if grep -Fq 'scripts/systemd' "$PHASE"; then
    fail "phase 10 must not copy units from scripts/systemd into the user scope"
fi
if grep -Eq 'ods_systemctl_user[[:space:]]+enable|systemctl[[:space:]]+--user[[:space:]]+enable' "$PHASE"; then
    fail "phase 10 must not enable user maintenance timers"
fi
pass "phase 10 installs no user units, templated or otherwise"

[[ ! -e "$ROOT_DIR/scripts/systemd/openclaw-session-cleanup.service" \
    && ! -e "$ROOT_DIR/scripts/systemd/openclaw-session-cleanup.timer" ]] \
    || fail "the legacy session-cleanup units must not ship"
pass "the legacy session-cleanup units are not shipped"

block="$(awk '
    /_phase10_user_units="\$HOME\/\.config\/systemd\/user"/ {grab=1}
    grab {print}
    grab && /^    unset _phase10_user_units$/ {exit}
' "$PHASE")"
[[ -n "$block" ]] || fail "could not extract the legacy unit retirement block from $PHASE"

run_block() {
    local home="$1" calls="$2"
    (
        HOME="$home"
        LOG_FILE="$TMP_DIR/phase10.log"
        ods_systemctl_user() { printf '%s\n' "$*" >>"$calls"; }
        log() { :; }
        ai_ok() { :; }
        eval "$block"
    )
}

# Upgrade: the legacy units are retired; memory-shepherd timers stay.
upgrade_home="$TMP_DIR/upgrade-home"
units="$upgrade_home/.config/systemd/user"
mkdir -p "$units"
for unit in openclaw-session-cleanup.timer openclaw-session-cleanup.service \
            memory-shepherd-workspace.timer memory-shepherd-workspace.service; do
    printf '[Unit]\nDescription=fixture\n' > "$units/$unit"
done
calls="$TMP_DIR/upgrade-calls"
run_block "$upgrade_home" "$calls"
[[ ! -e "$units/openclaw-session-cleanup.timer" && ! -e "$units/openclaw-session-cleanup.service" ]] \
    || fail "upgrade kept the legacy session-cleanup units"
[[ -f "$units/memory-shepherd-workspace.timer" && -f "$units/memory-shepherd-workspace.service" ]] \
    || fail "upgrade must leave memory-shepherd units as configured"
grep -Fxq 'disable --now openclaw-session-cleanup.timer' "$calls" \
    || fail "upgrade did not stop the legacy session-cleanup timer"
grep -Fxq 'daemon-reload' "$calls" || fail "upgrade did not reload the user manager"
pass "upgrade retires the legacy session-cleanup units and keeps memory-shepherd timers"

# Fresh install: nothing to retire, no user-manager calls.
fresh_home="$TMP_DIR/fresh-home"
mkdir -p "$fresh_home"
calls="$TMP_DIR/fresh-calls"
run_block "$fresh_home" "$calls"
[[ ! -s "$calls" ]] || fail "fresh install touched the user systemd manager: $(cat "$calls")"
[[ ! -e "$fresh_home/.config/systemd/user" ]] || fail "fresh install created a user systemd dir"
pass "fresh install leaves the user systemd scope untouched"
