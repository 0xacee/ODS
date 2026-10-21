#!/usr/bin/env bash
# Exercise the public import command with real tar payloads, and failures at
# extraction/publication boundaries. No installed tree or service is used.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CLI=${ODS_CLI_UNDER_TEST:-$ROOT/ods-cli}
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/foreign/presets/shared" "$TMP/archive/shared"
printf 'foreign\n' > "$TMP/foreign/presets/shared/env"
printf 'name=shared\n' > "$TMP/archive/shared/meta.txt"
printf 'enabled:example\n' > "$TMP/archive/shared/extensions.list"
printf 'replacement\n' > "$TMP/archive/shared/env"
tar czf "$TMP/valid.tar.gz" -C "$TMP/archive" shared
rm "$TMP/archive/shared/extensions.list"
tar czf "$TMP/missing-extensions.tar.gz" -C "$TMP/archive" shared
rm "$TMP/archive/shared/meta.txt"
tar czf "$TMP/missing-meta.tar.gz" -C "$TMP/archive" shared
export PRESET_REAL_TAR=$(command -v tar) PRESET_REAL_MV=$(command -v mv)
cat > "$TMP/bin/tar" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == xzf && "${3:-}" == -C ]]; then
    stage=$(dirname "$4")
    mode=$(stat -c '%a' "$stage" 2>/dev/null || stat -f '%Lp' "$stage")
    [[ "$mode" == 700 ]] || exit 98
fi
if [[ "${PRESET_FAILURE:-}" == extract && "$1" == xzf ]]; then
    "$PRESET_REAL_TAR" "$@"
    exit 23
fi
exec "$PRESET_REAL_TAR" "$@"
EOF
cat > "$TMP/bin/mv" <<'EOF'
#!/usr/bin/env bash
case "${PRESET_FAILURE:-}" in
    park) [[ "$3" != */previous ]] || exit 24 ;;
    publish|rollback-failure) [[ "$2" != */payload/shared ]] || exit 24 ;;
    term) if [[ "$2" == */payload/shared ]]; then kill -TERM "$PPID"; exit 24; fi ;;
    term-after-publish)
        if [[ "$2" == */payload/shared ]]; then
            "$PRESET_REAL_MV" "$@" || exit "$?"
            kill -TERM "$PPID"
            exit 24
        fi ;;
esac
if [[ "${PRESET_FAILURE:-}" == rollback-failure && "$2" == */previous ]]; then exit 25; fi
exec "$PRESET_REAL_MV" "$@"
EOF
for command in docker sudo systemctl service launchctl curl powershell.exe; do
    printf '#!/bin/sh\necho "Unexpected host command: $0" >&2\nexit 99\n' > "$TMP/bin/$command"
done
chmod +x "$TMP/bin/"*
export PATH="$TMP/bin:$PATH"

for scenario in missing-extensions missing-meta extract park publish term term-after-publish rollback-failure cancel success fresh; do
    install="$TMP/$scenario"
    mkdir -p "$install/lib" "$install/extensions/services" "$install/presets/unrelated"
    cp "$ROOT"/lib/*.sh "$install/lib/"
    touch "$install/docker-compose.base.yml"
    printf 'active settings\n' > "$install/.env"
    printf 'unrelated\n' > "$install/presets/unrelated/env"
    if [[ "$scenario" != fresh ]]; then
        mkdir "$install/presets/shared"
        printf 'old metadata\n' > "$install/presets/shared/meta.txt"
        printf 'old selection\n' > "$install/presets/shared/extensions.list"
        printf 'original\n' > "$install/presets/shared/env"
    fi
    archive="$TMP/valid.tar.gz" reply=y PRESET_FAILURE=""
    case "$scenario" in
        missing-*) archive="$TMP/$scenario.tar.gz" ;;
        extract|park|publish|term|term-after-publish|rollback-failure) PRESET_FAILURE="$scenario" ;;
        cancel) reply=n ;;
    esac
    export INSTALL_DIR="$install" ODS_HOME="$install" ODS_INSTALL_DIR="$TMP/foreign" PRESET_FAILURE
    rc=0
    output=$(printf '%s\n' "$reply" | bash "$CLI" preset import "$archive" 2>&1) || rc=$?
    case "$scenario" in
        missing-*|extract|park|publish|term)
            [[ "$rc" != 0 && $(cat "$install/presets/shared/env") == original ]] || {
                echo "FAIL: $scenario lost the previous preset: $output"; exit 1;
            }
            [[ $(cat "$install/presets/shared/meta.txt") == 'old metadata' &&
               $(cat "$install/presets/shared/extensions.list") == 'old selection' ]] || exit 1
            [[ "$output" != *'imported successfully'* ]] || exit 1 ;;
        rollback-failure|term-after-publish)
            recovery=$(find "$install/presets" -maxdepth 2 -path '*/.import-*/previous' -print)
            [[ "$rc" != 0 && -n "$recovery" && $(cat "$recovery/env") == original &&
               "$output" == *"Recovery copy retained at: $recovery"* ]] || {
                echo "FAIL: rollback failure discarded recovery or its location: $output"; exit 1;
            }
            if [[ "$scenario" == term-after-publish ]]; then
                [[ $(cat "$install/presets/shared/env") == replacement && ! -e "$install/presets/shared/previous" ]] || exit 1
            fi ;;
        cancel)
            [[ "$rc" == 0 && $(cat "$install/presets/shared/env") == original && "$output" == *Cancelled* ]] || exit 1 ;;
        success|fresh)
            [[ "$rc" == 0 && $(cat "$install/presets/shared/env") == replacement && "$output" == *'imported successfully'* ]] || {
                echo "FAIL: $scenario import failed: $output"; exit 1;
            }
            [[ $(cat "$install/presets/shared/extensions.list") == enabled:example ]] || exit 1 ;;
    esac
    [[ $(cat "$install/.env") == 'active settings' && $(cat "$install/presets/unrelated/env") == unrelated &&
       $(cat "$TMP/foreign/presets/shared/env") == foreign ]] || exit 1
    [[ "$scenario" == rollback-failure || "$scenario" == term-after-publish || -z $(find "$install/presets" -maxdepth 1 -name '.import-*' -print) ]] || {
        echo "FAIL: $scenario left staging behind"; exit 1;
    }
    echo "PASS: public preset import $scenario preserves recovery and unrelated state"
done
