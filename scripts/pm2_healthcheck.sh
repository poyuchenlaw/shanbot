#!/bin/bash
# shanbot pm2 healthcheck — 對 /health 探活，連 3 次失敗推 LINE + pm2 restart
# 6/3 部署，配合 cron */5 * * * *
set -u

HEALTH_URL="http://127.0.0.1:8025/health"
STATE_FILE="/tmp/shanbot_healthcheck_fails"
LOG_FILE="/home/simon/shanbot/logs/healthcheck.log"
ADMIN_LINE_ID="U2a551ae0489009eb31a864860504b804"
SHANBOT_DIR="/home/simon/shanbot"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*" >> "$LOG_FILE"; }

push_line() {
  local msg="$1"
  cd "$SHANBOT_DIR" || return 1
  ./venv/bin/python3 -c "
import sys
sys.path.insert(0, '$SHANBOT_DIR')
from services.company_service import init_companies
init_companies()
from services.line_service import LineService
r = LineService().push('$ADMIN_LINE_ID', sys.argv[1], company_id=1)
print('OK' if r else 'FAIL')
" "$msg" 2>>"$LOG_FILE"
}

http=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 "$HEALTH_URL" 2>/dev/null || echo "000")

if [ "$http" = "200" ]; then
  if [ -f "$STATE_FILE" ]; then
    fails=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
    if [ "$fails" -ge 3 ]; then
      log "RECOVERED after $fails fails"
      push_line "[shanbot healthcheck] ✅ 已恢復 ($(ts))" > /dev/null
    fi
    rm -f "$STATE_FILE"
  fi
  exit 0
fi

# fail path
fails=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
fails=$((fails + 1))
echo "$fails" > "$STATE_FILE"
log "FAIL #$fails http=$http url=$HEALTH_URL"

if [ "$fails" -eq 3 ]; then
  log "TRIGGER: 3 consecutive fails → pm2 restart shanbot + LINE push"
  pm2 restart shanbot >> "$LOG_FILE" 2>&1
  result=$(push_line "[shanbot healthcheck] ⚠️ 連 3 次 /health 失敗 (http=$http)，已自動 pm2 restart shanbot @ $(ts)")
  log "LINE push: $result"
elif [ "$fails" -gt 3 ] && [ $((fails % 12)) -eq 0 ]; then
  push_line "[shanbot healthcheck] ⚠️ 仍 down 第 $fails 次 (http=$http) @ $(ts)" > /dev/null
fi
