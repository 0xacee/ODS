#!/usr/bin/env bash
# Prepare the Linux installer's diagnostic log before any message can append.

ods_prepare_install_log() {
    local log_path="$1" parent parent_mode file_mode
    # An explicit discard sink is useful for source tests and cannot disclose
    # diagnostics to another reader.
    [[ "$log_path" == /dev/null ]] && return 0

    parent="$(dirname -- "$log_path")" || return 1
    if [[ ! -d "$parent" || -L "$parent" ]]; then
        printf '%s\n' '[ERROR] Installer log directory is missing or unsafe.' >&2
        return 1
    fi
    parent_mode="$(stat -c '%a' -- "$parent")" || return 1
    if [[ ! "$parent_mode" =~ ^[0-7]{3,4}$ ]] \
        || (( (8#$parent_mode & 0022) != 0 && (8#$parent_mode & 01000) == 0 )); then
        printf '%s\n' '[ERROR] Installer log directory is writable by others without sticky protection.' >&2
        return 1
    fi

    if [[ -L "$log_path" ]]; then
        printf '%s\n' '[ERROR] Installer log cannot be a symlink.' >&2
        return 1
    fi
    if [[ -e "$log_path" ]]; then
        if [[ ! -f "$log_path" || ! -O "$log_path" ]] || ! chmod 600 -- "$log_path"; then
            printf '%s\n' '[ERROR] Installer log must be an owned regular file.' >&2
            return 1
        fi
    elif ! ( umask 077; set -C; : > "$log_path" ); then
        # noclobber uses exclusive creation, so a competing path cannot be
        # silently replaced or followed during the first open.
        printf '%s\n' '[ERROR] Could not create a private installer log.' >&2
        return 1
    fi

    if [[ -L "$log_path" || ! -f "$log_path" || ! -O "$log_path" ]]; then
        printf '%s\n' '[ERROR] Installer log ownership changed unexpectedly.' >&2
        return 1
    fi
    file_mode="$(stat -c '%a' -- "$log_path")" || return 1
    if [[ "$file_mode" != 600 ]]; then
        printf '%s\n' '[ERROR] Installer log is not private.' >&2
        return 1
    fi
}
