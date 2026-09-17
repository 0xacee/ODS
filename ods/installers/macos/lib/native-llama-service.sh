#!/usr/bin/env bash
set -euo pipefail

action="$1"
install_dir="$2"
binary="$3"
pid_file="$4"
shift 4
label=com.ods.llama-server
domain="gui/$(id -u)"
plist="$HOME/Library/LaunchAgents/$label.plist"

if [[ "$action" == stop ]]; then
    if launchctl print "$domain/$label" >/dev/null 2>&1; then
        launchctl bootout "$domain/$label"
    fi
    [[ ! -f "$plist" ]] || rm "$plist"
    [[ ! -f "$pid_file" ]] || rm "$pid_file"
    exit 0
fi
[[ "$action" == start ]] || exit 2
memory_check="$(dirname "$0")/native-memory-budget.py"
model_path=""
previous=""
for argument in "$@"; do
    [[ "$previous" != --model && "$previous" != -m ]] || model_path="$argument"
    previous="$argument"
done
if [[ -n "$model_path" && -f "$memory_check" ]]; then
    "${ODS_PYTHON_CMD:-python3}" "$memory_check" --model "$model_path" || \
        echo 'ODS: native memory estimate failed; review resource settings.' >&2
fi
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/ODS" "$(dirname "$pid_file")"
"${ODS_PYTHON_CMD:-python3}" - "$plist" "$install_dir" "$binary" "$HOME/Library/Logs/ODS/llama-server.log" "$@" <<'PY'
import os
import pathlib
import plistlib
import sys
import tempfile

destination, install, binary, log, *arguments = sys.argv[1:]
payload = {
    "Label": "com.ods.llama-server",
    "ProgramArguments": [binary, *arguments],
    "WorkingDirectory": install,
    "RunAtLoad": True,
    "StandardOutPath": log,
    "StandardErrorPath": log,
}
fd, staged = tempfile.mkstemp(dir=pathlib.Path(destination).parent, suffix=".plist")
try:
    with os.fdopen(fd, "wb") as handle:
        plistlib.dump(payload, handle)
    os.replace(staged, destination)
finally:
    if os.path.exists(staged):
        os.unlink(staged)
PY
if launchctl print "$domain/$label" >/dev/null 2>&1; then
    launchctl bootout "$domain/$label"
fi
loaded=false
for attempt in {1..10}; do
    if launchctl bootstrap "$domain" "$plist"; then
        loaded=true
        break
    fi
    # launchd may still be releasing a just-booted-out service definition.
    sleep 1
done
$loaded || exit 1
launchctl kickstart "$domain/$label"
for attempt in {1..20}; do
    pid="$(launchctl print "$domain/$label" | awk '$1 == "pid" && $2 == "=" {print $3; exit}')"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
        printf '%s\n' "$pid" > "$pid_file"
        exit 0
    fi
    sleep 0.5
done
echo 'Native llama LaunchAgent did not start; check ~/Library/Logs/ODS/llama-server.log' >&2
exit 1
