#!/usr/bin/env python3
"""OCR retry guard for stale zero-confidence purchase_staging rows."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import state_manager as sm


LOCK_PATH = Path("/tmp/ocr_retry_guard.lock")
LOG_PATH = ROOT / "logs" / "ocr_retry_guard.jsonl"
DOCTOR_FLAG_PATH = ROOT / "data" / ".ocr_doctor_last_run"
DOCTOR_COOLDOWN_SECONDS = 6 * 60 * 60
# escalated=1 的記錄已交醫生 session 處理過並通報人類，哨兵不再糾纏（防絕望件每 6h 重複出動醫生）
STALE_ZERO_SQL = """
SELECT p.id
FROM purchase_staging p
LEFT JOIN ocr_retry_log r ON r.staging_id = p.id
WHERE p.status='pending'
  AND p.ocr_confidence=0
  AND p.created_at <= datetime('now','localtime','-20 minutes')
  AND COALESCE(r.escalated, 0) = 0
ORDER BY p.id
"""


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def json_default(value: Any) -> str:
    return str(value)


def write_audit(event: str, **fields: Any) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": now_text(), "event": event, **fields}
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=json_default) + "\n")


def acquire_lock() -> Any | None:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("w", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("ocr_retry_guard: another instance is running; exit")
        handle.close()
        return None
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(sm.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_retry_log(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ocr_retry_log (
            staging_id INTEGER PRIMARY KEY,
            attempts INTEGER DEFAULT 0,
            last_attempt TEXT,
            escalated INTEGER DEFAULT 0
        )
        """
    )
    conn.commit()


def fetch_stale_zero_ids(conn: sqlite3.Connection) -> list[int]:
    return [int(row["id"]) for row in conn.execute(STALE_ZERO_SQL).fetchall()]


def ensure_ledger_rows(conn: sqlite3.Connection, staging_ids: list[int]) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO ocr_retry_log (staging_id) VALUES (?)",
        [(staging_id,) for staging_id in staging_ids],
    )
    conn.commit()


def fetch_attempts(conn: sqlite3.Connection, staging_ids: list[int]) -> dict[int, int]:
    if not staging_ids:
        return {}
    placeholders = ",".join("?" for _ in staging_ids)
    rows = conn.execute(
        f"SELECT staging_id, attempts FROM ocr_retry_log WHERE staging_id IN ({placeholders})",
        staging_ids,
    ).fetchall()
    return {int(row["staging_id"]): int(row["attempts"] or 0) for row in rows}


def fetch_zero_ids(conn: sqlite3.Connection, staging_ids: list[int]) -> set[int]:
    if not staging_ids:
        return set()
    placeholders = ",".join("?" for _ in staging_ids)
    rows = conn.execute(
        f"""
        SELECT id
        FROM purchase_staging
        WHERE id IN ({placeholders})
          AND status='pending'
          AND ocr_confidence=0
        """,
        staging_ids,
    ).fetchall()
    return {int(row["id"]) for row in rows}


def delete_ledger_rows(conn: sqlite3.Connection, staging_ids: list[int]) -> None:
    if not staging_ids:
        return
    conn.executemany(
        "DELETE FROM ocr_retry_log WHERE staging_id = ?",
        [(staging_id,) for staging_id in staging_ids],
    )
    conn.commit()


def increment_attempts(conn: sqlite3.Connection, staging_ids: list[int]) -> None:
    if not staging_ids:
        return
    conn.executemany(
        """
        UPDATE ocr_retry_log
        SET attempts = attempts + 1,
            last_attempt = datetime('now','localtime')
        WHERE staging_id = ?
        """,
        [(staging_id,) for staging_id in staging_ids],
    )
    conn.commit()


def mark_escalated(conn: sqlite3.Connection, staging_ids: list[int]) -> None:
    if not staging_ids:
        return
    conn.executemany(
        """
        UPDATE ocr_retry_log
        SET escalated = 1
        WHERE staging_id = ?
        """,
        [(staging_id,) for staging_id in staging_ids],
    )
    conn.commit()


def run_reprocess(staging_ids: list[int]) -> subprocess.CompletedProcess[str]:
    cmd = [
        "python3",
        "tools/reprocess_zero_conf.py",
        "--ids",
        ",".join(str(staging_id) for staging_id in staging_ids),
    ]
    write_audit("reprocess_start", ids=staging_ids, cmd=cmd)
    env = os.environ.copy()
    env["DB_PATH"] = sm.DB_PATH
    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    write_audit(
        "reprocess_done",
        ids=staging_ids,
        returncode=result.returncode,
        stdout_tail=result.stdout[-2000:],
        stderr_tail=result.stderr[-2000:],
    )
    return result


def doctor_recently_started() -> tuple[bool, float | None]:
    if not DOCTOR_FLAG_PATH.exists():
        return False, None
    age_seconds = time.time() - DOCTOR_FLAG_PATH.stat().st_mtime
    return age_seconds < DOCTOR_COOLDOWN_SECONDS, age_seconds


def launch_doctor(conn: sqlite3.Connection, staging_ids: list[int]) -> None:
    cooling, age_seconds = doctor_recently_started()
    if cooling:
        mark_escalated(conn, staging_ids)
        write_audit(
            "doctor_cooldown",
            ids=staging_ids,
            flag=str(DOCTOR_FLAG_PATH),
            age_seconds=round(age_seconds or 0, 1),
        )
        return

    cmd = ["bash", "scripts/ocr_doctor_session.sh"]
    process = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    mark_escalated(conn, staging_ids)
    write_audit("doctor_launched", ids=staging_ids, pid=process.pid, cmd=cmd)


def dry_run(conn: sqlite3.Connection) -> int:
    staging_ids = fetch_stale_zero_ids(conn)
    payload = {
        "dry_run": True,
        "db_path": sm.DB_PATH,
        "query": "stale pending rows with ocr_confidence=0 older than 20 minutes",
        "count": len(staging_ids),
        "ids": staging_ids,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def run_guard() -> int:
    with connect() as conn:
        init_retry_log(conn)
        stale_ids = fetch_stale_zero_ids(conn)
        if not stale_ids:
            print("ocr_retry_guard: no stale zero-confidence pending rows")
            return 0

        write_audit("detected", ids=stale_ids, count=len(stale_ids), db_path=sm.DB_PATH)
        ensure_ledger_rows(conn, stale_ids)
        attempts = fetch_attempts(conn, stale_ids)
        retry_ids = [staging_id for staging_id in stale_ids if attempts.get(staging_id, 0) < 2]
        if retry_ids:
            result = run_reprocess(retry_ids)
            still_zero = fetch_zero_ids(conn, retry_ids)
            recovered = [staging_id for staging_id in retry_ids if staging_id not in still_zero]
            delete_ledger_rows(conn, recovered)
            increment_attempts(conn, sorted(still_zero))
            write_audit(
                "retry_accounted",
                retried=retry_ids,
                recovered=recovered,
                still_zero=sorted(still_zero),
                reprocess_returncode=result.returncode,
            )

        current_stale = fetch_stale_zero_ids(conn)
        current_attempts = fetch_attempts(conn, current_stale)
        escalate_ids = [
            staging_id
            for staging_id in current_stale
            if current_attempts.get(staging_id, 0) >= 2
        ]
        if escalate_ids:
            launch_doctor(conn, escalate_ids)
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retry and escalate stale OCR 0% rows.")
    parser.add_argument("--dry-run", action="store_true", help="Only print detected stale ids; no DB writes.")
    parser.add_argument("--db-path", help="Override SQLite DB path, mainly for snapshot validation.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.db_path:
        sm.DB_PATH = args.db_path

    lock_handle = acquire_lock()
    if lock_handle is None:
        return 0

    try:
        with connect() as conn:
            if args.dry_run:
                return dry_run(conn)
        return run_guard()
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
