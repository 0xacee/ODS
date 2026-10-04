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
python3 /opt/ods/openwebui-prepare.py
exec "$@"
