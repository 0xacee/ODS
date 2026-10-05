#!/usr/bin/env bash
# ods doctor checks the llama-server the Windows Portal runs outside the stack
# (NATIVE_LLM_BASE_URL): it probes that server's /health without a key and
# never falls back to the absent in-stack llama-server.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_file="$root/scripts/ods-doctor.sh"
extract_function() {
    awk -v signature="^$1[(][)]" '
        $0 ~ signature { in_block = 1 }
        in_block { print }
        in_block && /^}/ { exit }
    ' "$source_file"
}
for name in _doctor_check_host_native_llm _doctor_check_external_llm _doctor_check_llm_backend; do
    body="$(extract_function "$name")"
    [[ -n "$body" ]] || { printf '[FAIL] %s not found in ods-doctor.sh\n' "$name" >&2; exit 1; }
    eval "$body"
done

fail() { printf '[FAIL] %s\n' "$*" >&2; exit 1; }
log_ok() { :; }
log_fail() { :; }
log_info() { :; }
log_warn() { :; }

curl_calls=0
curl_rc=0
curl_args=()
curl() {
    curl_calls=$((curl_calls + 1))
    curl_args=("$@")
    return "$curl_rc"
}
local_checks=0
_doctor_check_llama_server() {
    local_checks=$((local_checks + 1))
    LLM_STATUS=local
}

DOCKER_DAEMON=false
EXTERNAL_LLM_URL=
ODS_MODE=local
LLM_BACKEND=llama-server
NATIVE_LLM_BASE_URL=http://localhost:8080
GGUF_FILE=Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
LLAMA_SERVER_API_KEY=abababababababababababababababab

_doctor_check_llm_backend
[[ "$LLM_STATUS" == ok && "$LLM_PROVIDER" == "llama-server (Windows)" && "$LLM_MODEL" == "$GGUF_FILE" ]] \
    || fail "the host-native llama-server must be reported as the active, healthy LLM backend ($LLM_STATUS|$LLM_PROVIDER|$LLM_MODEL)"
[[ "$curl_calls" == 1 && "$local_checks" == 0 ]] \
    || fail 'doctor must probe the host-native server once and skip the in-stack llama-server'
[[ " ${curl_args[*]} " == *' http://localhost:8080/health '* ]] \
    || fail "doctor must probe the native server's /health (${curl_args[*]})"
[[ " ${curl_args[*]} " != *"$LLAMA_SERVER_API_KEY"* && " ${curl_args[*]} " != *Authorization* ]] \
    || fail 'the /health probe needs no key and must not carry one'

curl_rc=7
_doctor_check_llm_backend
[[ "$LLM_STATUS" == fail && "$LLM_PROVIDER" == "llama-server (Windows)" && "$local_checks" == 0 ]] \
    || fail 'an unreachable host-native server must fail, not fall back to the absent in-stack llama-server'
[[ "$LLM_RECOVERY" == *"ODS Portal"* ]] \
    || fail "recovery must point at the Portal that owns the Windows task ($LLM_RECOVERY)"

NATIVE_LLM_BASE_URL=
_doctor_check_llm_backend
[[ "$LLM_STATUS" == local && "$local_checks" == 1 ]] \
    || fail 'managed local installs must retain the llama-server diagnostic'

# The retired Lemonade branch is gone: an unmigrated .env gets the in-stack
# llama-server diagnostic (and the inference-contract blocker), never a
# Lemonade probe.
ODS_MODE=lemonade
LLM_BACKEND=lemonade
LEMONADE_EXTERNAL=true
LEMONADE_BASE_URL=http://127.0.0.1:13305
before_calls="$curl_calls"
_doctor_check_llm_backend
[[ "$LLM_STATUS" == local && "$local_checks" == 2 && "$curl_calls" == "$before_calls" ]] \
    || fail 'a Lemonade-era .env must not be probed as a Lemonade server'

printf '[OK] doctor checks the host-native llama-server, not absent local llama-server or Lemonade\n'
