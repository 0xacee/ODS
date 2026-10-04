#!/bin/sh
set -eu

# Back up Open WebUI's database before a new Open WebUI version migrates it,
# and refuse a start that would leave it half-migrated (openwebui-prepare.py).
# Then run the image's own start command, which compose passes as arguments
# (`bash start.sh` in the image's working directory, /app/backend).
if [ "$#" -eq 0 ]; then
    echo "openwebui-entrypoint.sh: no start command given" >&2
    exit 64
fi

# With sign-in off, Open WebUI makes whoever reaches it its administrator.
# Compose publishes it on ODS_WEBUI_BIND_ADDRESS (BIND_ADDRESS in .env). When
# that is not loopback, start with sign-in on, whatever WEBUI_AUTH says, so a
# recreate that skipped the CLI's check (the Dashboard's update, a rollback, a
# plain `docker compose up`) cannot publish it on the network without sign-in.
# Loopback follows the host agent's rule: trimmed, unquoted, any case; empty
# means 127.0.0.1.
bind="$(printf '%s' "${ODS_WEBUI_BIND_ADDRESS:-}" | tr -d " \t\"'" | tr '[:upper:]' '[:lower:]')"
case "$bind" in
    ''|127.0.0.1|::1|'[::1]'|localhost) ;;
    *)
        # Open WebUI reads sign-in as on only when WEBUI_AUTH is "true" in any
        # case, or unset. An empty value counts as off.
        if [ "$(printf '%s' "${WEBUI_AUTH-true}" | tr '[:upper:]' '[:lower:]')" != true ]; then
            echo "openwebui-entrypoint.sh: Open WebUI is published on $bind, so it starts with sign-in on (WEBUI_AUTH=true)" >&2
            WEBUI_AUTH=true
            export WEBUI_AUTH
        fi
        ;;
esac

python3 /opt/ods/openwebui-prepare.py
exec "$@"
