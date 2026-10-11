#!/bin/sh
# LOCAL DEVELOPMENT ONLY: http://127.0.0.1:8790, dev keys in server/data/dev (never use them in production).
# First administrator (once):  python -m mqlicense --env-file data/dev/dev.env bootstrap-admin --email you@example.com
set -eu
cd "$(dirname "$0")"
PY="${PY:-python3}"
if [ ! -f data/dev/dev.env ]; then
  "$PY" -m mqlicense gen-keys --out data/dev
  { cat data/dev/secrets.env; echo "MQL_ENV=dev"; echo "MQL_DB_PATH=data/dev/mqlicense.sqlite3"; } > data/dev/dev.env
  chmod 600 data/dev/dev.env
fi
"$PY" -m mqlicense --env-file data/dev/dev.env migrate
echo "Panel: http://127.0.0.1:8790/admin/"
exec "$PY" -m mqlicense --env-file data/dev/dev.env serve
