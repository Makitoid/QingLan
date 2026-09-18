#!/usr/bin/env bash
set -euo pipefail

# cron 示例：每天凌晨 3 点备份一次（脚本自动只保留最近 7 份）
# 0 3 * * * /opt/qinglan/scripts/backup.sh >> /var/log/qinglan-backup.log 2>&1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${DATA_DIR:-$ROOT/backend/data}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT/backups}"
KEEP=7
TS="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

cp -a "$DATA_DIR" "$STAGE/data"
rm -f "$STAGE/data"/cg.db "$STAGE/data"/cg.db-wal "$STAGE/data"/cg.db-shm
sqlite3 "$DATA_DIR/cg.db" ".backup '$STAGE/data/cg.db'"

tar czf "$BACKUP_DIR/qinglan-$TS.tar.gz" -C "$STAGE" data

ls -1t "$BACKUP_DIR"/qinglan-*.tar.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f

echo "backup ok: $BACKUP_DIR/qinglan-$TS.tar.gz"
