#!/usr/bin/env bash
# Run the real requirements phase on a simulated WSL host whose Windows side
# already listens on port 9000 (as a native app's websocket can), then the
# phase 06 resolver that persists WHISPER_PORT.
#
# A lean install (voice off) must still move the generated Whisper default off
# 9000: Whisper can be added from the Extensions Library later, and Docker
# Desktop then cannot publish 127.0.0.1:9000. A rerun moves a retained 9000,
# which earlier installers wrote as the generated default, but never a port
# the owner chose.
# Variables below are consumed by the sourced phases.
# shellcheck disable=SC2034
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/source/lib"
cp "$ROOT/lib/safe-env.sh" "$tmp/source/lib/safe-env.sh"
unset WHISPER_PORT

# The Windows listener table, as powershell.exe reports it to WSL.
cat > "$tmp/bin/powershell.exe" <<'STUB'
#!/bin/bash
for port in ${ODS_TEST_WINDOWS_PORTS:-}; do
    printf '%s\r\n' "$port"
done
printf 'ODS_WINDOWS_PORT_SCAN_OK\r\n'
STUB
chmod +x "$tmp/bin/powershell.exe"
export PATH="$tmp/bin:$PATH"

# Phase 06's own resolver for the value it writes to .env.
phase06_resolver="$(sed -n \
    -e '/^    _env_get() {$/,/^    }$/p' \
    -e '/^    _env_get_explicit_first() {$/,/^    }$/p' \
    -e '/^    _phase06_lemonade_uses_host_9000() {$/,/^    WHISPER_PORT="\$WHISPER_PORT_VALUE"$/p' \
    "$ROOT/installers/phases/06-directories.sh")"
if [[ "$phase06_resolver" != *'WHISPER_PORT_VALUE="$(_env_get_explicit_first WHISPER_PORT "9000")"'* ]]; then
    printf 'FAIL: phase 06 no longer resolves WHISPER_PORT where this test reads it\n' >&2
    exit 1
fi

# Prints "<WHISPER_PORT after phase 04, or unset> <port phase 04 checks for
# Whisper> <WHISPER_PORT phase 06 persists>".
run_case() (
    # Command substitution clears errexit; a failed phase must fail the case.
    set -euo pipefail
    local voice="$1" windows_ports="$2" retained="${3:-}" explicit="${4:-}"
    local gpu_backend="${5:-nvidia}" wsl="${6:-true}" lemonade_external="${7:-false}"
    rm -rf "$tmp/install"
    mkdir -p "$tmp/install"
    if [[ -n "$retained" ]]; then
        printf 'WHISPER_PORT=%s\n' "$retained" > "$tmp/install/.env"
    fi
    if [[ -n "$explicit" ]]; then
        WHISPER_PORT="$explicit"
    fi
    export ODS_TEST_WINDOWS_PORTS="$windows_ports" ODS_WSL_HOST_OVERRIDE="$wsl"
    SCRIPT_DIR="$tmp/source" INSTALL_DIR="$tmp/install"
    LOG_FILE="$tmp/requirements.log" PREFLIGHT_REPORT_FILE="$tmp/preflight.json"
    TIER=2 RAM_GB=64 DISK_AVAIL=200
    GPU_BACKEND="$gpu_backend" GPU_VRAM=24000 GPU_NAME=fixture GPU_COUNT=1
    INTERACTIVE=false DRY_RUN=true
    CAP_PLATFORM_ID=wsl CAP_COMPOSE_OVERLAYS=docker-compose.base.yml
    ENABLE_VOICE="$voice" ENABLE_WORKFLOWS=false ENABLE_RAG=false ENABLE_COMFYUI=false
    EXTERNAL_LLM_URL='' ODS_MODE=local LEMONADE_EXTERNAL="$lemonade_external"
    # The service registry's manifest defaults, as install-core loads them.
    declare -A SERVICE_PORTS=([whisper]=9000 [tts]=8880 [open-webui]=3000 [llama-server]=8080)
    tier_rank() { printf '2\n'; }
    ods_progress() { :; }; chapter() { :; }; ai() { :; }
    log() { printf 'LOG: %s\n' "$*"; }; warn() { printf 'WARN: %s\n' "$*"; }
    ai_ok() { printf 'OK: %s\n' "$*"; }; ai_bad() { printf 'BAD: %s\n' "$*"; }
    ai_warn() { printf 'WARN: %s\n' "$*"; }
    # Only the stubbed Windows listener table may report a port as taken.
    docker() { :; }; pgrep() { return 1; }; lsof() { return 1; }
    ss() { :; }; netstat() { :; }
    source "$ROOT/installers/lib/detection.sh"
    source "$ROOT/installers/lib/external-services.sh"
    source "$ROOT/installers/phases/04-requirements.sh" >"$tmp/output"

    local after_phase04="${WHISPER_PORT-unset}" checked="${SERVICE_PORTS[whisper]}"
    _env_existing=""
    if [[ -f "$INSTALL_DIR/.env" ]]; then
        _env_existing="$INSTALL_DIR/.env"
    fi
    LEMONADE_EXTERNAL_VALUE="$lemonade_external"
    source <(printf '%s\n' "$phase06_resolver") >>"$tmp/output"
    printf '%s %s %s\n' "$after_phase04" "$checked" "$WHISPER_PORT_VALUE"
)

expect() {
    local label="$1" expected="$2" actual
    shift 2
    actual="$(run_case "$@")"
    if [[ "$actual" != "$expected" ]]; then
        printf 'FAIL: %s: expected "%s", got "%s"\n' "$label" "$expected" "$actual" >&2
        cat "$tmp/output" >&2
        exit 1
    fi
    printf 'PASS: %s\n' "$label"
}

#      label                                                    expected          voice windows-listeners  retained explicit gpu  wsl   lemonade
expect 'Lean install reserves 9100 for a later Library add'   '9100 9100 9100' false '9000'
expect 'Lean install falls back to 9001 when 9100 is taken'   '9001 9001 9001' false '9000 9100'
expect 'Free Windows port 9000 keeps the default'             'unset 9000 9000' false ''
expect 'Rerun moves a retained generated 9000'                '9100 9100 9100' false '9000'           9000
expect 'Rerun keeps a retained owner port'                    'unset 9500 9500' false '9000'           9500
expect 'Voice rerun keeps and checks a retained owner port'   'unset 9500 9500' true  '9000'           9500
expect 'An explicit WHISPER_PORT is used as given'            '9500 9500 9500' false '9000'           ''       9500
expect 'Voice install still moves the generated default'      '9100 9100 9100' true  '9000'
expect 'A native Linux host never consults Windows'           'unset 9000 9000' false '9000'           ''       ''       nvidia false
expect 'Native AMD lean install still gets 9100 from phase 06' 'unset 9000 9100' false ''              ''       ''       amd    false
expect 'WSL Lemonade lean install keeps a free alternate'     '9001 9001 9001' false '9000 9100'      ''       ''       amd    true  true

run_case false '9000 9100 9001' >/dev/null
if ! grep -q 'Whisper alternates 9100 and 9001 are unavailable' "$tmp/output"; then
    printf 'FAIL: no warning when every Whisper alternate is taken\n' >&2
    cat "$tmp/output" >&2
    exit 1
fi
printf 'PASS: Taken alternates are reported and leave the default\n'

run_case true '9000' 9500 >/dev/null
if grep -q 'Port 9000 is in use' "$tmp/output"; then
    printf 'FAIL: a voice rerun checked 9000 instead of its retained port\n' >&2
    cat "$tmp/output" >&2
    exit 1
fi
printf 'PASS: A voice rerun does not report the port it does not use\n'
