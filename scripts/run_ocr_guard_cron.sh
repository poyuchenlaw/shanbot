#!/usr/bin/env bash
# cron: */20 * * * * /home/simon/shanbot/scripts/run_ocr_guard_cron.sh >> /home/simon/shanbot/logs/ocr_guard.cron.log 2>&1
set -euo pipefail

export GMAIL_TOKEN_PATH="${GMAIL_TOKEN_PATH:-/home/simon/.google-oauth/edu_blogger_token.json}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

exec python3 tools/ocr_retry_guard.py
