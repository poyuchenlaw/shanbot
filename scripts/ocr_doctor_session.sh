#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p data logs

TS="$(date +%Y%m%d_%H%M%S)"
FLAG_PATH="data/.ocr_doctor_last_run"
LOG_PATH="logs/ocr_doctor_${TS}.log"
HISTORY_PATH="logs/ocr_doctor_history.log"
EMAIL_TO="chenpoyu0131@gmail.com"

export GMAIL_TOKEN_PATH="${GMAIL_TOKEN_PATH:-/home/simon/.google-oauth/edu_blogger_token.json}"

date '+%Y-%m-%d %H:%M:%S' > "$FLAG_PATH"

IDS="$(python3 - <<'PY'
import sqlite3
import state_manager as sm

with sqlite3.connect(sm.DB_PATH) as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS ocr_retry_log (staging_id INTEGER PRIMARY KEY, attempts INTEGER DEFAULT 0, last_attempt TEXT, escalated INTEGER DEFAULT 0)")
    rows = conn.execute(
        """
        SELECT p.id
        FROM purchase_staging p
        LEFT JOIN ocr_retry_log r ON r.staging_id = p.id
        WHERE p.status='pending'
          AND p.ocr_confidence=0
          AND p.created_at <= datetime('now','localtime','-20 minutes')
          AND COALESCE(r.escalated, 0) = 0
        ORDER BY p.id
        """
    ).fetchall()

print(",".join(str(row[0]) for row in rows))
PY
)"

ID_COUNT=0
if [[ -n "$IDS" ]]; then
  IFS=',' read -r -a ID_ARRAY <<< "$IDS"
  ID_COUNT="${#ID_ARRAY[@]}"
fi

FIRST_IMAGE="$(python3 - <<'PY'
import sqlite3
import state_manager as sm

with sqlite3.connect(sm.DB_PATH) as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS ocr_retry_log (staging_id INTEGER PRIMARY KEY, attempts INTEGER DEFAULT 0, last_attempt TEXT, escalated INTEGER DEFAULT 0)")
    row = conn.execute(
        """
        SELECT p.local_image_path
        FROM purchase_staging p
        LEFT JOIN ocr_retry_log r ON r.staging_id = p.id
        WHERE p.status='pending'
          AND p.ocr_confidence=0
          AND p.created_at <= datetime('now','localtime','-20 minutes')
          AND COALESCE(p.local_image_path, '') != ''
          AND COALESCE(r.escalated, 0) = 0
        ORDER BY p.id
        LIMIT 1
        """
    ).fetchone()

print(row[0] if row else "")
PY
)"

RECENT_OCR_ERRORS="$(
  if [[ -d logs ]]; then
    grep -RihE 'ocr|OCR|error|ERROR|exception|Traceback' logs 2>/dev/null | tail -n 5 || true
  fi
)"

PM2_ENV="$(
  if command -v pm2 >/dev/null 2>&1; then
    pm2 env shanbot 2>/dev/null | grep -E 'GEMINI_CLI_BIN|CLAUDE_CLI_BIN' || true
  else
    printf 'pm2 not found'
  fi
)"

read -r -d '' PROMPT <<EOF || true
你是小膳 OCR 醫生 session。請只診斷與修復 OCR 服務狀態，禁止改 code、禁止動 DB schema、禁止碰 crontab。

repo: /home/simon/shanbot
卡件清單: ${IDS:-none}
第一張可測圖片: ${FIRST_IMAGE:-none}

最近 5 行 OCR/error log:
${RECENT_OCR_ERRORS:-none}

pm2 env 三鍵:
${PM2_ENV:-none}

請逐步執行：
(a) cd /home/simon/shanbot，跑 1 筆測試 OCR：
python3 - <<'PY'
from services.ocr_service import process_image
image_path = "${FIRST_IMAGE}"
if not image_path:
    raise SystemExit("no pending image path")
result = process_image(image_path)
print({"confidence": result.confidence, "supplier": result.supplier_name, "total": result.total_amount, "items": len(result.items)})
PY

(b) 如果失敗，分層診斷：gemini CLI 驗活（echo test prompt）→ claude CLI 驗活 → rapidocr import → pm2 env 三鍵。
(c) 可修項就地修，僅限：pm2 restart shanbot、重跑 python3 tools/reprocess_zero_conf.py --ids ${IDS:-0}。
(d) 終局輸出固定格式（必須是你回覆的最後三行，輸出後立即結束）：
DIAGNOSIS: <一段>
FIXED: yes/no
ACTION_NEEDED: <人類待辦或 none>

紀律：全程禁止 spawn 背景任務/agent/長輪詢；每個指令逾時請設 120 秒上限；輸出 (d) 三行後不得再做任何事。
EOF

set +e
CLAUDE_HEADLESS_WORKER=1 timeout 600 /home/simon/.npm-global/bin/claude -p "$PROMPT" \
  --model claude-sonnet-4-6 \
  --allowedTools "Bash" "Read" "Grep" \
  --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
  --settings '{"hooks":{}}' > "$LOG_PATH" 2>&1
CLAUDE_EXIT=$?
set -e

DIAGNOSIS="$(grep -E '^DIAGNOSIS:' "$LOG_PATH" | tail -n 1 | sed 's/^DIAGNOSIS:[[:space:]]*//' || true)"
FIXED="$(grep -E '^FIXED:' "$LOG_PATH" | tail -n 1 | sed 's/^FIXED:[[:space:]]*//' || true)"
ACTION_NEEDED="$(grep -E '^ACTION_NEEDED:' "$LOG_PATH" | tail -n 1 | sed 's/^ACTION_NEEDED:[[:space:]]*//' || true)"

DIAGNOSIS="${DIAGNOSIS:-doctor session ended without DIAGNOSIS line; see log}"
FIXED="${FIXED:-no}"
ACTION_NEEDED="${ACTION_NEEDED:-inspect $LOG_PATH}"

printf '%s ids=%s count=%s fixed=%s exit=%s log=%s\n' \
  "$(date '+%Y-%m-%d %H:%M:%S')" "${IDS:-none}" "$ID_COUNT" "$FIXED" "$CLAUDE_EXIT" "$LOG_PATH" >> "$HISTORY_PATH"

BODY="$(cat <<EOF
OCR 醫生出動報告

時間：$(date '+%Y-%m-%d %H:%M:%S')
卡件清單：${IDS:-none}
卡件數：$ID_COUNT
Claude exit：$CLAUDE_EXIT
log：$REPO_ROOT/$LOG_PATH

DIAGNOSIS: $DIAGNOSIS
FIXED: $FIXED
ACTION_NEEDED: $ACTION_NEEDED
EOF
)"

EMAIL_ARGS=(
  --to "$EMAIL_TO"
  --subject "【小膳】OCR 醫生出動報告"
  --body "$BODY"
  --attach "$LOG_PATH"
)

if [[ "${OCR_DOCTOR_EMAIL_DRY_RUN:-0}" == "1" ]]; then
  EMAIL_ARGS+=(--dry-run)
fi

set +e
python3 tools/send_report_email.py "${EMAIL_ARGS[@]}" >> "$LOG_PATH" 2>&1
EMAIL_EXIT=$?
set -e

if [[ "$EMAIL_EXIT" -ne 0 ]]; then
  printf '%s email_failed exit=%s log=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$EMAIL_EXIT" "$LOG_PATH" >> "$HISTORY_PATH"
fi

exit "$CLAUDE_EXIT"
