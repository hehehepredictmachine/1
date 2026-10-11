#!/bin/sh
# Daily backup (cron): consistent SQLite online backup, 14 days retention.
# Restore: systemctl stop mqlicense; cp BACKUP /opt/mqlicense/data/mqlicense.sqlite3; systemctl start mqlicense
set -eu
cd /opt/mqlicense/server
/opt/mqlicense/venv/bin/python -m mqlicense backup --out "/opt/mqlicense/backups/mqlicense_$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
find /opt/mqlicense/backups -name 'mqlicense_*.sqlite3' -mtime +14 -delete
