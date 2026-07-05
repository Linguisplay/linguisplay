#!/usr/bin/env bash
# Daily LinguisPlay backups — runs ON the server via cron (see install line below).
# - SQLite: consistent snapshot via the sqlite3 backup API (safe against live writes),
#   gzipped, keep the last 14 days
# - scene assets (player uploads + generated art): Sunday tar, keep the last 4 weeks
#
# Install once:
#   ssh persona '(crontab -l 2>/dev/null | grep -v backup.sh; \
#     echo "30 4 * * * bash /opt/linguisplay/deploy/backup.sh >> /opt/backups/linguisplay/backup.log 2>&1") | crontab -'
# Restore a dump:
#   gunzip -k linguisplay-YYYYMMDD.db.gz && systemctl stop linguisplay \
#     && cp linguisplay-YYYYMMDD.db /opt/linguisplay/apps/api/data/linguisplay.db \
#     && systemctl start linguisplay
set -e
BK=/opt/backups/linguisplay
DB=/opt/linguisplay/apps/api/data/linguisplay.db
PY=/opt/linguisplay/apps/api/.venv/bin/python
mkdir -p "$BK"
stamp=$(date +%Y%m%d)

"$PY" - "$DB" "$BK/linguisplay-$stamp.db" <<'EOF'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close(); src.close()
print("db snapshot ok")
EOF
gzip -f "$BK/linguisplay-$stamp.db"

if [ "$(date +%u)" = "7" ]; then
  tar czf "$BK/scene-$stamp.tgz" -C /opt/linguisplay/apps/api/app/static scene
fi

ls -1t "$BK"/linguisplay-*.db.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
ls -1t "$BK"/scene-*.tgz 2>/dev/null | tail -n +5 | xargs -r rm -f
echo "$(date '+%F %T') backup done"
