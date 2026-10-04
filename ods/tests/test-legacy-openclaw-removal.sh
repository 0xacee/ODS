#!/usr/bin/env bash
# The legacy OpenClaw extension (the ods-openclaw container) was removed.
# Portal (Pixel) and Hermes are the supported agents.
#
# Scripts that still pass the old flags must keep working: every installer
# accepts them, prints one notice and changes nothing else. Upgrades must
# delete the stale extensions/services/openclaw tree (the source copy never
# prunes) while keeping the owner's data/openclaw and config/openclaw.
#
# This runs the real Linux and macOS argument loops and prune blocks against
# throwaway directories, and checks the Windows entry points statically.
set -euo pipefail

if (( BASH_VERSINFO[0] < 4 )); then
    for modern_bash in /opt/homebrew/bin/bash /usr/local/bin/bash; do
        if [[ -x "$modern_bash" ]]; then
            exec "$modern_bash" "$0" "$@"
        fi
    done
    printf '[SKIP] requires Bash 4+\n'
    exit 0
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
LINUX_INSTALLER="$ROOT/install-core.sh"
MACOS_INSTALLER="$ROOT/installers/macos/install-macos.sh"
LINUX_PHASE06="$ROOT/installers/phases/06-directories.sh"
WINDOWS_PHASE06="$ROOT/installers/windows/phases/06-directories.ps1"
WINDOWS_PORTAL_SETUP="$ROOT/installers/windows/lib/wsl-portal-setup.ps1"
WINDOWS_INSTALLER="$ROOT/installers/windows/install-windows.ps1"
NOTICE='The legacy OpenClaw extension was removed;'
AGENTS='Portal (Pixel) and Hermes are the supported agents.'

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

# ── Flags: Linux and macOS parse them as notices and keep parsing ────────────
argument_loop() {
    sed -n '/^while \[\[ \$# -gt 0 \]\]; do$/,/^done$/p' "$1"
}

check_flags() {
    local label="$1" loop="$2" flag
    [[ -n "$loop" ]] || fail "$label argument loop not found"
    for flag in --openclaw --no-openclaw; do
        # --voice after the legacy flag proves parsing continued normally.
        # errexit is off inside an `if` condition, so each check exits itself.
        # shellcheck disable=SC2034  # read by the eval'd loop
        if ! (
            set -- "$flag" --voice
            ENABLE_VOICE=false
            eval "$loop"
            [[ "$ENABLE_VOICE" == true ]] || exit 1
            [[ -z "${ENABLE_OPENCLAW+x}${OPENCLAW_EXPLICIT+x}" ]] || exit 1
        ) >"$tmp/flag.out" 2>"$tmp/flag.err"; then
            cat "$tmp/flag.out" "$tmp/flag.err" >&2
            fail "$label did not accept $flag as a no-op"
        fi
        grep -Fq -- "$NOTICE $flag is ignored. $AGENTS" "$tmp/flag.err" \
            || fail "$label did not print the removal notice for $flag"
        pass "$label accepts $flag and prints the removal notice"
    done
}

check_flags install-core.sh "$(argument_loop "$LINUX_INSTALLER")"
check_flags install-macos.sh "$(argument_loop "$MACOS_INSTALLER")"

for installer in "$LINUX_INSTALLER" "$MACOS_INSTALLER"; do
    if grep -Eq 'ENABLE_OPENCLAW|OPENCLAW_EXPLICIT' "$installer"; then
        fail "$(basename "$installer") must not select the removed extension"
    fi
done
pass "Linux and macOS installers no longer carry OpenClaw feature state"

# ── Flags: Windows keeps -OpenClaw accepted and only prints a notice ─────────
for script in "$REPO_ROOT/install.ps1" "$ROOT/installers/windows-portal.ps1" "$WINDOWS_INSTALLER"; do
    grep -Fq '[switch]$OpenClaw' "$script" \
        || fail "$(basename "$script") must keep accepting -OpenClaw"
done
for script in "$WINDOWS_PORTAL_SETUP" "$WINDOWS_INSTALLER"; do
    grep -Fq "$NOTICE -OpenClaw is ignored. $AGENTS" "$script" \
        || fail "$(basename "$script") must print the removal notice for -OpenClaw"
done
if grep -Fq -- '--no-openclaw' "$WINDOWS_PORTAL_SETUP"; then
    fail "Portal setup must not pass a removed flag to the Linux installer"
fi
if grep -Eq 'openClawFlag|enableOpenClaw|EnableOpenClaw' "$WINDOWS_INSTALLER" \
        "$ROOT"/installers/windows/phases/*.ps1 "$ROOT"/installers/windows/lib/*.ps1; then
    fail "the Windows installer must not carry OpenClaw feature state"
fi
pass "Windows entry points accept -OpenClaw as a notice-only switch"

# ── Upgrade prune: Linux and macOS delete only the stale service tree ────────
prune_block() {
    case "$1" in
        linux)
            awk '
                /_phase06_step "prune-retired-services"/ {grab=1}
                /# A Pixel-to-Hermes rerun must retire/ {exit}
                grab {print}
            ' "$LINUX_PHASE06"
            ;;
        macos)
            awk '
                index($0, "extensions/services/odsforge\" ]]; then") {grab=1}
                grab && /# Copy extensions library to data dir/ {exit}
                grab {print}
            ' "$MACOS_INSTALLER"
            ;;
    esac
}

run_prune() {
    local platform="$1" block install
    block="$(prune_block "$platform")"
    [[ -n "$block" ]] || fail "$platform prune block not found"

    install="$tmp/$platform-upgrade"
    mkdir -p "$install/extensions/services/openclaw" "$install/extensions/services/hermes" \
        "$install/data/openclaw/home" "$install/config/openclaw/workspace"
    printf 'services: {}\n' > "$install/extensions/services/openclaw/compose.yaml.disabled"
    printf 'services: {}\n' > "$install/extensions/services/hermes/compose.yaml"
    printf '{}\n' > "$install/data/openclaw/home/openclaw.json"
    printf 'notes\n' > "$install/config/openclaw/workspace/MEMORY.md"
    (
        INSTALL_DIR="$install"
        _phase06_step() { :; }
        log() { printf 'log: %s\n' "$*"; }
        ai() { printf 'ai: %s\n' "$*"; }
        eval "$block"
    ) >"$tmp/$platform.out"
    [[ ! -e "$install/extensions/services/openclaw" ]] \
        || fail "$platform upgrade kept the stale OpenClaw service tree"
    [[ -f "$install/extensions/services/hermes/compose.yaml" ]] \
        || fail "$platform upgrade touched a supported service"
    [[ -f "$install/data/openclaw/home/openclaw.json" && -f "$install/config/openclaw/workspace/MEMORY.md" ]] \
        || fail "$platform upgrade deleted the owner's OpenClaw data"
    grep -Fq 'delete them by hand' "$tmp/$platform.out" \
        || fail "$platform upgrade did not say the OpenClaw folders were kept"
    pass "$platform upgrade prunes extensions/services/openclaw and keeps data/openclaw and config/openclaw"

    install="$tmp/$platform-fresh"
    mkdir -p "$install/extensions/services/hermes"
    (
        INSTALL_DIR="$install"
        _phase06_step() { :; }
        log() { printf 'log: %s\n' "$*"; }
        ai() { printf 'ai: %s\n' "$*"; }
        eval "$block"
    ) >"$tmp/$platform-fresh.out"
    if grep -qi 'openclaw' "$tmp/$platform-fresh.out"; then
        fail "$platform fresh install mentions the removed extension"
    fi
    [[ ! -e "$install/data/openclaw" && ! -e "$install/config/openclaw" ]] \
        || fail "$platform fresh install created OpenClaw folders"
    pass "$platform fresh install stays silent and creates no OpenClaw folders"
}

run_prune linux
run_prune macos

# The held Pixel source transaction records the installed extensions tree as
# its baseline and checks it again before release; a prune after it is
# applied would be reported as live drift. Prune before it is staged.
prune_line="$(grep -n '_phase06_step "prune-retired-services"' "$LINUX_PHASE06" | head -n 1 | cut -d: -f1)"
stage_line="$(grep -n '_ods_pixel_source_upgrade stage' "$LINUX_PHASE06" | head -n 1 | cut -d: -f1)"
[[ -n "$prune_line" && -n "$stage_line" ]] || fail "could not locate the prune step or the Pixel source stage"
(( prune_line < stage_line )) \
    || fail "Linux prune must run before the Pixel source transaction is staged"
pass "Linux prune runs before the Pixel source transaction is staged"

# ── Upgrade prune: Windows mirrors the ODSForge precedent ────────────────────
grep -Fq '$_retiredOpenClaw = Join-Path $installDir "extensions\services\openclaw"' "$WINDOWS_PHASE06" \
    || fail "Windows phase 06 must locate the stale OpenClaw service tree"
grep -Fq 'Remove-Item -LiteralPath $_retiredOpenClaw -Recurse -Force' "$WINDOWS_PHASE06" \
    || fail "Windows phase 06 must remove the stale OpenClaw service tree"
if grep -Eiq 'Remove-Item[^#]*(data|config)[\\/]openclaw' "$WINDOWS_PHASE06"; then
    fail "Windows phase 06 must keep data\\openclaw and config\\openclaw"
fi
pass "Windows phase 06 prunes the stale service tree and keeps the owner's data"

echo "All legacy OpenClaw removal checks passed."
