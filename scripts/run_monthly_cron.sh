#!/usr/bin/env bash
# cron: 0 5 1 * * /home/simon/shanbot/scripts/run_monthly_cron.sh >> /home/simon/shanbot/logs/monthly_report.log 2>&1
set -euo pipefail

# Gmail 寄送 token：nomis token 已撤銷（invalid_grant 6/5），改用 edu_blogger（含 gmail.send，6/5 驗活）
export GMAIL_TOKEN_PATH="${GMAIL_TOKEN_PATH:-/home/simon/.google-oauth/edu_blogger_token.json}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

detect_gdrive_root() {
  if [[ -n "${GDRIVE_LOCAL:-}" ]]; then
    printf '%s\n' "$GDRIVE_LOCAL"
    return 0
  fi

  local candidate
  for candidate in \
    "/mnt/h/小魚資料/團膳公司資料" \
    "/mnt/h/我的雲端硬碟/小魚資料/團膳公司資料"; do
    if [[ -d "$candidate/福利社" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  printf '%s\n' "/mnt/h/我的雲端硬碟/小魚資料/團膳公司資料"
}

LAST_MONTH="$(date -d "$(date +%Y-%m-01) -1 month" +%Y-%m)"
GDRIVE_ROOT="$(detect_gdrive_root)"
REPORT_PATH="$GDRIVE_ROOT/_月報彙總/小膳月報_${LAST_MONTH}.xlsx"

python3 tools/run_monthly_reports.py "$LAST_MONTH"

if [[ ! -f "$REPORT_PATH" ]]; then
  echo "ERROR monthly report not found: $REPORT_PATH" >&2
  exit 1
fi

python3 tools/send_report_email.py \
  --subject "小膳月報 ${LAST_MONTH}" \
  --body "小膳月報 ${LAST_MONTH} 已產出，附件為本月彙總報表。" \
  --attach "$REPORT_PATH"
