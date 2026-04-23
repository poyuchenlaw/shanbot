#!/bin/bash
# shanbot DB 每日備份（仿 trading/daily_db_backup.sh 樣板）
DB="/home/simon/shanbot/data/shanbot.db"
BACKUP_DIR="/home/simon/shanbot/data/backups"
DATE=$(date +%Y%m%d)
MAX_BACKUPS=14

mkdir -p "$BACKUP_DIR"
if [ -f "$DB" ]; then
    /usr/bin/python3 -c "
import sqlite3
src = sqlite3.connect('$DB')
dst = sqlite3.connect('$BACKUP_DIR/shanbot_$DATE.db')
src.backup(dst)
dst.close(); src.close()
print('Backup OK')
" 2>&1
    if [ $? -eq 0 ]; then
        SIZE=$(du -h "$BACKUP_DIR/shanbot_$DATE.db" | cut -f1)
        echo "[$(date)] Backup OK: shanbot_$DATE.db ($SIZE)"
        # 保留最近 14 份
        cd "$BACKUP_DIR" && ls -t shanbot_*.db 2>/dev/null | tail -n +$((MAX_BACKUPS + 1)) | xargs -r rm
    else
        echo "[$(date)] ERROR: Backup failed!"
        exit 1
    fi
fi
