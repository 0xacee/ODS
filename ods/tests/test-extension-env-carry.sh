#!/usr/bin/env bash
# An installer rerun rewrites .env from phase 06's template. Settings that
# installed extensions own (declared in their manifest env_vars and written by
# their setup hooks) must survive it: Compose refuses the whole stack when an
# extension's required variable is missing, and the original secrets (for
# example LibreChat's database password) cannot be regenerated.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHASE="$ROOT_DIR/installers/phases/06-directories.sh"
LIB="$ROOT_DIR/installers/lib/extension-env-carry.sh"
LIBRARY="$ROOT_DIR/extensions/library/services"

FAILED=0
pass() { echo "[PASS] $1"; }
fail() { echo "[FAIL] $1" >&2; FAILED=$((FAILED + 1)); }

[[ -f "$LIB" ]] || { fail "missing installers/lib/extension-env-carry.sh"; exit 1; }
# shellcheck source=../installers/lib/extension-env-carry.sh
. "$LIB"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
ext="$tmp/data/user-extensions"
mkdir -p "$ext/librechat" "$ext/flowise"
cp "$LIBRARY/librechat/manifest.yaml" "$ext/librechat/manifest.yaml"
cp "$LIBRARY/flowise/manifest.yaml" "$ext/flowise/manifest.yaml"

cat > "$tmp/previous.env" <<'ENV'
WEBUI_SECRET=old-webui
LIBRECHAT_MONGO_PASSWORD=mongo-original
CREDS_KEY=creds-original
CREDS_IV=iv-original
JWT_SECRET=jwt-original
JWT_REFRESH_SECRET=refresh-original
LIBRECHAT_MEILI_KEY=meili-original
FLOWISE_USERNAME=admin
FLOWISE_PASSWORD='pa$$ #word'
RETIRED_SETTING=must-not-return
ENV
printf 'WEBUI_SECRET=new-webui\nCREDS_KEY=kept-by-template\n' > "$tmp/new.env"

ods_carry_extension_env_keys "$tmp/previous.env" "$tmp/new.env" "$ext"

for line in LIBRECHAT_MONGO_PASSWORD=mongo-original CREDS_IV=iv-original JWT_SECRET=jwt-original \
            JWT_REFRESH_SECRET=refresh-original LIBRECHAT_MEILI_KEY=meili-original \
            FLOWISE_USERNAME=admin "FLOWISE_PASSWORD='pa\$\$ #word'"; do
    if grep -qxF "$line" "$tmp/new.env"; then
        pass "carried: ${line%%=*}"
    else
        fail "not carried exactly: ${line%%=*}"
    fi
done
[[ "$(grep -c '^CREDS_KEY=' "$tmp/new.env")" == 1 ]] && grep -qx 'CREDS_KEY=kept-by-template' "$tmp/new.env" \
    && pass "a key the template already wrote is not overridden or duplicated" \
    || fail "template value for CREDS_KEY was overridden or duplicated"
grep -q '^RETIRED_SETTING=' "$tmp/new.env" \
    && fail "a key no installed extension declares must not be carried" \
    || pass "undeclared keys are not resurrected"
grep -qx 'WEBUI_SECRET=new-webui' "$tmp/new.env" \
    && pass "ODS's own keys keep the template value" || fail "template value for WEBUI_SECRET changed"

cp "$tmp/new.env" "$tmp/once.env"
ods_carry_extension_env_keys "$tmp/previous.env" "$tmp/new.env" "$ext"
cmp -s "$tmp/once.env" "$tmp/new.env" && pass "a second run changes nothing" || fail "carry-over is not idempotent"

printf 'WEBUI_SECRET=x\n' > "$tmp/bare.env"
ods_carry_extension_env_keys "$tmp/previous.env" "$tmp/bare.env" "$tmp/no-extensions"
[[ "$(cat "$tmp/bare.env")" == "WEBUI_SECRET=x" ]] \
    && pass "no installed extensions: .env untouched" || fail "carry-over wrote without installed extensions"

# Phase 06 must snapshot the previous .env before its rewrite and carry the
# keys over after it.
line_of() { awk -v needle="$1" 'index($0, needle) { print NR; exit }' "$PHASE"; }
snapshot="$(line_of 'cp "$INSTALL_DIR/.env" "$_phase06_previous_env"')"
rewrite="$(line_of 'cat > "$INSTALL_DIR/.env" << ENV_EOF')"
carry="$(line_of 'ods_carry_extension_env_keys "$_phase06_previous_env" "$INSTALL_DIR/.env"')"
if [[ -n "$snapshot" && -n "$rewrite" && -n "$carry" && "$snapshot" -lt "$rewrite" && "$rewrite" -lt "$carry" ]]; then
    pass "phase 06 snapshots .env before the rewrite and carries extension keys after it"
else
    fail "phase 06 does not carry installed extensions' keys across its .env rewrite"
fi

[[ $FAILED -eq 0 ]] || { echo "$FAILED check(s) failed" >&2; exit 1; }
echo "All extension .env carry-over checks passed"
