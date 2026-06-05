#!/usr/bin/env python3
"""Backfill confirmed purchase_staging rows stuck in 待確認.

Rows handled:
  status='confirmed' AND gdrive_path LIKE '%待確認%'

The tool is intentionally narrow: it archives files through
services.gdrive_service.archive_receipt(), updates only gdrive_path, and writes
one JSONL audit entry per row.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import state_manager as sm
from services.gdrive_service import (
    GDRIVE_LOCAL,
    _append_index_csv,
    archive_receipt,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(sm.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_rows(limit: int | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT *
        FROM purchase_staging
        WHERE status='confirmed'
          AND gdrive_path LIKE '%待確認%'
        ORDER BY id
    """
    params: list[Any] = []
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    with _conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _fetch_items(staging_id: int) -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT item_name, quantity, unit, unit_price, amount
            FROM purchase_items
            WHERE staging_id=?
            ORDER BY id
            """,
            (staging_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _company_folder(company_id: int) -> str:
    company = sm.get_company(company_id) or {}
    return company.get("gdrive_folder") or "福利社"


def _company_base(company_id: int) -> str:
    return os.path.join(GDRIVE_LOCAL, _company_folder(company_id))


def _safe_supplier(supplier_name: str | None) -> str:
    return re.sub(r'[\\/:*?"<>|\s]', "_", supplier_name or "unknown")[:20]


def _expected_archive_rel(row: dict[str, Any]) -> str:
    purchase_date = row.get("purchase_date") or datetime.now().strftime("%Y-%m-%d")
    try:
        y, m, d = purchase_date.split("-")[:3]
        date_prefix = f"{y[2:]}{m}{d}"
    except ValueError:
        date_prefix = datetime.now().strftime("%y%m%d")

    safe_supplier = _safe_supplier(row.get("supplier_name"))
    amount = int(row.get("total_amount") or 0)
    source = _resolve_source(row)
    ext = os.path.splitext(source or row.get("local_image_path") or "")[1] or ".jpg"
    filename = f"{date_prefix}_{safe_supplier}_{amount}_#{row['id']}{ext}"
    month_seg = f"{int(purchase_date[5:7]):02d}月" if len(purchase_date) >= 7 else datetime.now().strftime("%m月")
    return os.path.join(
        _company_folder(int(row.get("company_id") or 1)),
        purchase_date[:4],
        month_seg,
        "收據憑證",
        safe_supplier,
        filename,
    )


def _resolve_source(row: dict[str, Any]) -> str | None:
    rel = row.get("gdrive_path") or ""
    company_id = int(row.get("company_id") or 1)
    candidates = []
    if rel:
        candidates.append(os.path.join(GDRIVE_LOCAL, rel))
        candidates.append(os.path.join(_company_base(company_id), rel))
    if row.get("local_image_path"):
        candidates.append(row["local_image_path"])

    seen = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        if os.path.isfile(path):
            return path
    return None


def _pending_cleanup_rel(source_path: str | None) -> str | None:
    if not source_path:
        return None
    try:
        rel = os.path.relpath(source_path, GDRIVE_LOCAL)
    except ValueError:
        return None
    if rel.startswith("..") or os.path.isabs(rel):
        return None
    return rel if "待確認" in rel else None


def _index_has_staging(index_path: str, staging_id: int) -> bool:
    if not os.path.exists(index_path):
        return False
    try:
        with open(index_path, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("來源") == f"staging#{staging_id}":
                    return True
    except Exception:
        return False
    return False


def _index_row(row: dict[str, Any], filename: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "日期": row.get("purchase_date") or "",
        "供應商": row.get("supplier_name") or "",
        "發票號碼": row.get("invoice_number") or "",
        "品項數": len(items),
        "未稅金額": row.get("subtotal") or 0,
        "稅額": row.get("tax_amount") or 0,
        "總金額": row.get("total_amount") or 0,
        "檔案名稱": filename,
        "歸檔時間": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "來源": f"staging#{row['id']}",
    }


def _ensure_existing_archive_index(row: dict[str, Any], dest_abs: str) -> None:
    items = _fetch_items(int(row["id"]))
    index_path = os.path.join(os.path.dirname(dest_abs), "INDEX.csv")
    if _index_has_staging(index_path, int(row["id"])):
        return
    _append_index_csv(os.path.dirname(dest_abs), _index_row(row, os.path.basename(dest_abs), items))


async def _archive_one(row: dict[str, Any]) -> dict[str, Any]:
    source = _resolve_source(row)
    expected_rel = _expected_archive_rel(row)
    expected_abs = os.path.join(GDRIVE_LOCAL, expected_rel)
    pending_rel = _pending_cleanup_rel(source)

    if os.path.exists(expected_abs):
        _ensure_existing_archive_index(row, expected_abs)
        if pending_rel:
            pending_abs = os.path.join(GDRIVE_LOCAL, pending_rel)
            if os.path.isfile(pending_abs):
                os.remove(pending_abs)
        sm.update_purchase_staging(int(row["id"]), gdrive_path=expected_rel)
        return {
            "status": "already_archived",
            "old_gdrive_path": row.get("gdrive_path"),
            "new_gdrive_path": expected_rel,
            "source": source,
        }

    if not source:
        return {
            "status": "error",
            "error": "source file not found",
            "old_gdrive_path": row.get("gdrive_path"),
            "expected_gdrive_path": expected_rel,
        }

    items = _fetch_items(int(row["id"]))
    result = await archive_receipt(
        local_path=source,
        purchase_date=row.get("purchase_date") or datetime.now().strftime("%Y-%m-%d"),
        supplier_name=row.get("supplier_name") or "unknown",
        total_amount=row.get("total_amount") or 0,
        staging_id=int(row["id"]),
        ocr_summary={
            "invoice_number": row.get("invoice_number") or "",
            "subtotal": row.get("subtotal") or 0,
            "tax_amount": row.get("tax_amount") or 0,
            "items": items,
        },
        pending_gdrive_path=pending_rel,
        company_id=int(row.get("company_id") or 1),
    )
    if result.get("gdrive_path"):
        sm.update_purchase_staging(int(row["id"]), gdrive_path=result["gdrive_path"])
        return {
            "status": "archived",
            "old_gdrive_path": row.get("gdrive_path"),
            "new_gdrive_path": result["gdrive_path"],
            "source": source,
            "filename": result.get("filename"),
        }
    return {
        "status": "error",
        "error": result.get("error") or "archive_receipt returned no gdrive_path",
        "old_gdrive_path": row.get("gdrive_path"),
        "source": source,
        "filename": result.get("filename"),
    }


def _dry_run_action(row: dict[str, Any]) -> dict[str, Any]:
    source = _resolve_source(row)
    return {
        "status": "dry_run",
        "staging_id": row["id"],
        "company_id": row.get("company_id"),
        "supplier": row.get("supplier_name"),
        "amount": row.get("total_amount"),
        "old_gdrive_path": row.get("gdrive_path"),
        "source": source,
        "new_gdrive_path": _expected_archive_rel(row),
        "source_exists": bool(source),
    }


async def _run(args: argparse.Namespace) -> int:
    sm.init_db()
    rows = _fetch_rows(args.limit)
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"backfill_archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

    summary = {"dry_run": args.dry_run, "total": len(rows), "archived": 0, "already_archived": 0, "error": 0}
    with log_path.open("w", encoding="utf-8") as log:
        for idx, row in enumerate(rows, start=1):
            if args.dry_run:
                event = _dry_run_action(row)
                if idx <= args.print_first:
                    print(json.dumps(event, ensure_ascii=False))
            else:
                result = await _archive_one(row)
                event = {
                    "staging_id": row["id"],
                    "company_id": row.get("company_id"),
                    "supplier": row.get("supplier_name"),
                    "amount": row.get("total_amount"),
                    **result,
                }
                print(json.dumps(event, ensure_ascii=False))
                status = result.get("status")
                if status in summary:
                    summary[status] += 1
                elif status == "archived":
                    summary["archived"] += 1
                else:
                    summary["error"] += 1

            log.write(json.dumps({"ts": datetime.now().isoformat(), **event}, ensure_ascii=False) + "\n")

    print(json.dumps({"summary": summary, "audit_log": str(log_path)}, ensure_ascii=False))
    return 0 if summary["error"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive confirmed rows still stored under 待確認")
    parser.add_argument("--dry-run", action="store_true", help="List planned actions without moving files or writing DB")
    parser.add_argument("--limit", type=int, default=None, help="Limit rows for testing")
    parser.add_argument("--print-first", type=int, default=10, help="Dry-run rows to print")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
