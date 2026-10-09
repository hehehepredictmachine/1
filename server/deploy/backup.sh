#!/bin/sh
# Daily backup (cron): pg_dump custom format, 14 days retention. Restore: pg_restore --clean -d mqcentral FILE
set -eu
cd /opt/mqcentral/server
/opt/mqcentral/venv/bin/python -m mqcentral backup /opt/mqcentral/backups
find /opt/mqcentral/backups -name 'mqcentral_*.dump' -mtime +14 -delete
