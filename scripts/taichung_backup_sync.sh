#!/bin/bash
# 把 shanbot 最新 DB 備份 + code 快照同步到 taichung-backup（異地雙保險）
set -euo pipefail

SRC_DB_DIR="/home/simon/shanbot/data/backups"
DST_DB_DIR="/home/simon/taichung-backup/shanbot/data/backups"
DST_CODE="/home/simon/taichung-backup/shanbot"

mkdir -p "$DST_DB_DIR"

# 1. DB 備份：同步 backups/ 目錄（保留最近 14 份）
rsync -a --delete "$SRC_DB_DIR/" "$DST_DB_DIR/"

# 2. Code 快照：排除 runtime 資料（DB / logs / 圖檔 / 快取）
rsync -a --delete \
  --exclude="data/" \
  --exclude="logs/" \
  --exclude="__pycache__/" \
  --exclude=".pytest_cache/" \
  --exclude=".worktrees/" \
  /home/simon/shanbot/ "$DST_CODE/"

# 3. 但要保留 DB 備份子目錄
cp -a "$SRC_DB_DIR" "$DST_CODE/data/" 2>/dev/null || true

echo "[$(date)] taichung-backup sync OK (DB + code)"
