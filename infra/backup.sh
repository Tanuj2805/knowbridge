#!/usr/bin/env bash
# Daily database backup: a compressed dump in ~/backups, keeping the last 14.
# Install once (runs at 03:30 every night):
#   chmod +x infra/backup.sh
#   (crontab -l 2>/dev/null; echo "30 3 * * * $PWD/infra/backup.sh >> $HOME/backups/backup.log 2>&1") | crontab -
# Restore a backup:
#   gunzip -c ~/backups/knowbridge-YYYY-MM-DD.sql.gz | docker compose exec -T postgres psql -U knowbridge knowbridge
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p "$HOME/backups"
file="$HOME/backups/knowbridge-$(date +%F).sql.gz"
docker compose -f compose.yaml -f compose.prod.yaml exec -T postgres \
  pg_dumpall -U "${POSTGRES_USER:-knowbridge}" | gzip > "$file"
ls -1t "$HOME"/backups/knowbridge-*.sql.gz | tail -n +15 | xargs -r rm --
echo "$(date -Is) saved $file ($(du -h "$file" | cut -f1))"
