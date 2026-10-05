#!/bin/bash
# ============================================================================
# ODS Installer — Extension .env carry-over
# ============================================================================
# Purpose: Keep the settings installed extensions own across a .env rewrite
#
# Expects: nothing (pure file operation; no globals)
# Provides: ods_carry_extension_env_keys()
#
# Modder notes:
#   Phase 06 rewrites .env from its template on every installer run. The
#   template does not know extension settings: a Library extension's setup hook
#   appends its own secrets (LibreChat's database password and credential
#   encryption key, Flowise's login, ...) and declares them in its manifest's
#   env_vars. Dropping them makes Compose refuse the whole stack on the
#   extension's required variables, and the original values cannot be
#   regenerated without losing the extension's data.
# ============================================================================

# Append to NEW_ENV every key an installed extension declares in its manifest
# env_vars that NEW_ENV lacks and PREVIOUS_ENV has, copying the exact line.
# Usage: ods_carry_extension_env_keys PREVIOUS_ENV NEW_ENV EXTENSIONS_DIR
ods_carry_extension_env_keys() {
    local previous_env="$1" new_env="$2" extensions_dir="$3"
    local manifest key line header_written=false
    [[ -f "$previous_env" && -f "$new_env" && -d "$extensions_dir" ]] || return 0
    for manifest in "$extensions_dir"/*/manifest.yaml; do
        [[ -f "$manifest" ]] || continue
        while IFS= read -r key; do
            grep -q "^${key}=" "$new_env" && continue
            line="$(grep -m1 "^${key}=" "$previous_env")" || continue
            if [[ "$header_written" != true ]]; then
                printf '\n#=== Installed extensions (kept from the previous .env) ===\n' >> "$new_env"
                header_written=true
            fi
            printf '%s\n' "$line" >> "$new_env"
        done < <(awk '
            /^[[:space:]]*-[[:space:]]*key:[[:space:]]*/ {
                k = $0
                sub(/^[[:space:]]*-[[:space:]]*key:[[:space:]]*/, "", k)
                gsub(/["\047[:space:]]/, "", k)
                if (k ~ /^[A-Z][A-Z0-9_]*$/) print k
            }' "$manifest")
    done
}
