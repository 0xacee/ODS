#!/usr/bin/env bash
# The installer's hardware summary must not read as a detection error on
# Windows (#7311): VRAM rounds to the nearest GB (a 24GB card reports about
# 24564MiB), and the WSL RAM limit is named next to the RAM figure. The
# Linux-only NVIDIA Blackwell module check is skipped under WSL, where the
# Windows driver serves the GPU.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { echo "FAIL: $1"; exit 1; }

extract() {
    awk -v signature="$1() {" '$0 == signature { f = 1 } f { print } f && $0 == "}" { exit }' "$2"
}

summary="$(extract show_hardware_summary "$ROOT/installers/lib/ui.sh")"
[[ -n "$summary" ]] || fail "show_hardware_summary was not found"
eval "$summary"
GRN="" NC="" BGRN=""

out="$(show_hardware_summary "NVIDIA RTX 3090 Ti" "24" "Ryzen 9" "46" "500" "WSL limit; Windows has 96GB")"
grep -qF "46GB (WSL limit; Windows has 96GB)" <<< "$out" || fail "the WSL RAM note is missing: $out"
out="$(show_hardware_summary "NVIDIA RTX 3090 Ti" "24" "Ryzen 9" "64" "500")"
grep -qE 'RAM: +64GB +\|' <<< "$out" || fail "RAM without a note changed: $out"

grep -qF 'show_hardware_summary "$GPU_NAME" "$(( (GPU_VRAM + 512) / 1024 ))"' \
    "$ROOT/installers/phases/02-detection.sh" \
    || fail "the GPU summary must round VRAM to the nearest GB"
grep -qF '"$DISK_AVAIL" "${_ram_note:-}"' "$ROOT/installers/phases/02-detection.sh" \
    || fail "the hardware summary must receive the WSL RAM note"

check="$(extract validate_nvidia_blackwell_open_modules "$ROOT/installers/lib/detection.sh")"
[[ -n "$check" ]] || fail "validate_nvidia_blackwell_open_modules was not found"
eval "$check"

ods_is_wsl_host() { return 0; }
nvidia_blackwell_hardware_detected() { fail "the Blackwell module probe ran under WSL"; }
validate_nvidia_blackwell_open_modules || fail "the Blackwell check failed under WSL"

ods_is_wsl_host() { return 1; }
probed=false
nvidia_blackwell_hardware_detected() { probed=true; return 1; }
validate_nvidia_blackwell_open_modules
[[ "$probed" == true ]] || fail "the Blackwell check no longer runs on native Linux"

echo "PASS: WSL hardware summary names the RAM limit, rounds VRAM, and skips the Linux Blackwell check"
