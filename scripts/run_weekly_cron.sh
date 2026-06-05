#!/usr/bin/env bash
# cron: 15 8 * * 1 cd /home/simon/shanbot && scripts/run_weekly_cron.sh >> logs/weekly_cron.log 2>&1
set -euo pipefail

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

GDRIVE_ROOT="$(detect_gdrive_root)"
WEEKLY_DIR="$GDRIVE_ROOT/_週報彙總"

python3 tools/generate_weekly_report.py

if [[ ! -d "$WEEKLY_DIR" ]]; then
  echo "ERROR weekly report directory not found: $WEEKLY_DIR" >&2
  exit 1
fi

REPORT_PATH="$(find "$WEEKLY_DIR" -maxdepth 1 -type f -name '*.xlsx' -printf '%T@ %p\n' | sort -nr | awk 'NR==1 {sub(/^[^ ]+ /, ""); print}')"
if [[ -z "$REPORT_PATH" || ! -f "$REPORT_PATH" ]]; then
  echo "ERROR weekly report xlsx not found in: $WEEKLY_DIR" >&2
  exit 1
fi

BASENAME="$(basename "$REPORT_PATH")"
RANGE="${BASENAME#小膳週報_}"
RANGE="${RANGE%.xlsx}"

python3 tools/send_report_email.py \
  --subject "小膳週報 ${RANGE}" \
  --body "小膳週報 ${RANGE} 已產出，附件為本週彙總報表。" \
  --attach "$REPORT_PATH"
