#!/usr/bin/env python3
"""Repair backfill archive rows moved into the wrong company folder.

Scope:
  - Read archived events from logs/backfill_archive_*.jsonl.
  - Only update matching purchase_staging rows that are still confirmed.
  - Move the archived file from the wrong company folder to the company folder
    declared in companies.gdrive_folder.
  - Transfer the supplier INDEX.csv row and rebuild affected master indexes.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import state_manager as sm
from services.gdrive_service import GDRIVE_LOCAL, _append_index_csv, update_master_index

INDEX_HEADERS = [
    "日期",
    "供應商",
    "發票號碼",
    "品項數",
    "未稅金額",
    "稅額",
    "總金額",
    "檔案名稱",
    "歸檔時間",
    "來源",
]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(sm.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _load_archived_events() -> dict[int, dict[str, Any]]:
    """Return latest archived event per staging_id."""
    events: dict[int, dict[str, Any]] = {}
    for path in sorted(glob.glob("logs/backfill_archive_*.jsonl")):
        with open(path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON in {path}:{line_no}: {e}") from e
                if event.get("status") != "archived":
                    continue
                staging_id = event.get("staging_id")
                if staging_id is None:
                    continue
                event["_log_path"] = path
                events[int(staging_id)] = event
    return events


def _fetch_rows(ids: list[int]) -> dict[int, dict[str, Any]]:
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    with _conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, company_id, status, purchase_date, supplier_name,
                   invoice_number, subtotal, tax_amount, total_amount, gdrive_path
            FROM purchase_staging
            WHERE id IN ({placeholders})
            """,
            ids,
        ).fetchall()
    return {int(r["id"]): dict(r) for r in rows}


def _fetch_confirmed_rows() -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT id, company_id, status, purchase_date, supplier_name,
                   invoice_number, subtotal, tax_amount, total_amount, gdrive_path
            FROM purchase_staging
            WHERE status='confirmed'
              AND gdrive_path IS NOT NULL
              AND gdrive_path != ''
            ORDER BY id
            """
        ).fetchall()
    return [dict(r) for r in rows]


def _company_folders() -> dict[int, str]:
    with _conn() as conn:
        rows = conn.execute("SELECT id, gdrive_folder FROM companies").fetchall()
    return {int(r["id"]): r["gdrive_folder"] for r in rows if r["gdrive_folder"]}


def _fetch_items_count(staging_id: int) -> int:
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM purchase_items WHERE staging_id=?",
            (staging_id,),
        ).fetchone()
    return int(row["c"] if row else 0)


def _first_segment(path: str | None) -> str:
    if not path:
        return ""
    normalized = path.replace("\\", "/")
    if os.path.isabs(normalized):
        try:
            normalized = os.path.relpath(normalized, GDRIVE_LOCAL)
        except ValueError:
            return ""
    return normalized.split("/", 1)[0]


def _abs_from_rel(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.join(GDRIVE_LOCAL, path)


def _correct_rel(old_rel: str, correct_company_folder: str) -> str:
    parts = old_rel.replace("\\", "/").split("/", 1)
    rest = parts[1] if len(parts) == 2 else old_rel
    return os.path.join(correct_company_folder, rest)


def _year_month_from_rel(rel_path: str) -> str | None:
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) < 3:
        return None
    year = parts[1]
    month = parts[2].replace("月", "").zfill(2)
    if len(year) == 4 and month.isdigit():
        return f"{year}-{month}"
    return None


def _read_index(csv_path: str) -> tuple[list[str], list[dict[str, str]]]:
    if not os.path.exists(csv_path):
        return INDEX_HEADERS[:], []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or INDEX_HEADERS)
    return fieldnames, rows


def _write_index(csv_path: str, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    if not rows:
        if os.path.exists(csv_path):
            os.remove(csv_path)
        return
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _remove_index_row(index_path: str, filename: str) -> dict[str, str] | None:
    fieldnames, rows = _read_index(index_path)
    kept: list[dict[str, str]] = []
    removed: dict[str, str] | None = None
    for row in rows:
        if row.get("檔案名稱") == filename:
            if removed is None:
                removed = row
        else:
            kept.append(row)
    if removed is not None:
        _write_index(index_path, fieldnames, kept)
    return removed


def _index_has_filename(index_path: str, filename: str) -> bool:
    _, rows = _read_index(index_path)
    return any(row.get("檔案名稱") == filename for row in rows)


def _build_index_row(row: dict[str, Any], filename: str) -> dict[str, Any]:
    return {
        "日期": row.get("purchase_date") or "",
        "供應商": row.get("supplier_name") or "",
        "發票號碼": row.get("invoice_number") or "",
        "品項數": _fetch_items_count(int(row["id"])),
        "未稅金額": row.get("subtotal") or 0,
        "稅額": row.get("tax_amount") or 0,
        "總金額": row.get("total_amount") or 0,
        "檔案名稱": filename,
        "歸檔時間": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "來源": f"staging#{row['id']}",
    }


def _cleanup_supplier_dir(supplier_dir: str) -> bool:
    if not os.path.isdir(supplier_dir):
        return False
    try:
        os.rmdir(supplier_dir)
    except OSError:
        return False
    return True


def _find_misplaced() -> list[dict[str, Any]]:
    events = _load_archived_events()
    rows = _fetch_rows(sorted(events))
    folders = _company_folders()
    plans: list[dict[str, Any]] = []

    for staging_id, event in sorted(events.items()):
        row = rows.get(staging_id)
        if not row:
            plans.append({
                "staging_id": staging_id,
                "status": "missing_db_row",
                "old_gdrive_path": event.get("new_gdrive_path"),
            })
            continue
        if row.get("status") != "confirmed":
            plans.append({
                "staging_id": staging_id,
                "status": "skipped_non_confirmed",
                "db_status": row.get("status"),
                "old_gdrive_path": row.get("gdrive_path"),
            })
            continue

        company_id = int(row.get("company_id") or event.get("company_id") or 0)
        correct_folder = folders.get(company_id)
        current_rel = row.get("gdrive_path") or event.get("new_gdrive_path") or ""
        if os.path.isabs(current_rel):
            current_rel = os.path.relpath(current_rel, GDRIVE_LOCAL)

        if not correct_folder:
            plans.append({
                "staging_id": staging_id,
                "status": "missing_company_folder",
                "company_id": company_id,
                "old_gdrive_path": current_rel,
            })
            continue
        if _first_segment(current_rel) == correct_folder:
            logged_rel = event.get("new_gdrive_path") or ""
            if logged_rel and not os.path.isabs(logged_rel) and _first_segment(logged_rel) != correct_folder:
                old_abs = _abs_from_rel(logged_rel)
                filename = os.path.basename(logged_rel)
                old_index = os.path.join(os.path.dirname(old_abs), "INDEX.csv")
                if os.path.exists(old_abs) or _index_has_filename(old_index, filename):
                    plans.append({
                        "staging_id": staging_id,
                        "company_id": company_id,
                        "supplier": row.get("supplier_name"),
                        "amount": row.get("total_amount"),
                        "status": "cleanup_residual",
                        "old_gdrive_path": logged_rel,
                        "new_gdrive_path": current_rel,
                        "old_abs": old_abs,
                        "new_abs": _abs_from_rel(current_rel),
                        "filename": filename,
                        "year_month": _year_month_from_rel(current_rel),
                        "row": row,
                        "log_path": event.get("_log_path"),
                    })
            continue

        new_rel = _correct_rel(current_rel, correct_folder)
        plans.append({
            "staging_id": staging_id,
            "company_id": company_id,
            "supplier": row.get("supplier_name"),
            "amount": row.get("total_amount"),
            "status": "planned",
            "old_gdrive_path": current_rel,
            "new_gdrive_path": new_rel,
            "old_abs": _abs_from_rel(current_rel),
            "new_abs": _abs_from_rel(new_rel),
            "filename": os.path.basename(current_rel),
            "year_month": _year_month_from_rel(new_rel),
            "row": row,
            "log_path": event.get("_log_path"),
        })
    return plans


def _find_misplaced_from_db() -> list[dict[str, Any]]:
    rows = _fetch_confirmed_rows()
    folders = _company_folders()
    known_folders = set(folders.values())
    plans: list[dict[str, Any]] = []

    for row in rows:
        staging_id = int(row["id"])
        company_id = int(row.get("company_id") or 0)
        correct_folder = folders.get(company_id)
        current_rel = row.get("gdrive_path") or ""
        if os.path.isabs(current_rel):
            try:
                current_rel = os.path.relpath(current_rel, GDRIVE_LOCAL)
            except ValueError:
                plans.append({
                    "staging_id": staging_id,
                    "company_id": company_id,
                    "status": "skipped_no_company_segment",
                    "reason": "absolute path outside GDRIVE_LOCAL",
                    "old_gdrive_path": row.get("gdrive_path"),
                })
                continue

        current_folder = _first_segment(current_rel)
        if not correct_folder:
            plans.append({
                "staging_id": staging_id,
                "company_id": company_id,
                "status": "missing_company_folder",
                "old_gdrive_path": current_rel,
            })
            continue

        # Legacy flat paths such as 2026/03月/... have no company segment.
        # They are intentionally outside this repair batch.
        if current_folder not in known_folders:
            plans.append({
                "staging_id": staging_id,
                "company_id": company_id,
                "status": "skipped_no_company_segment",
                "old_gdrive_path": current_rel,
            })
            continue

        if current_folder == correct_folder:
            continue

        new_rel = _correct_rel(current_rel, correct_folder)
        plans.append({
            "staging_id": staging_id,
            "company_id": company_id,
            "supplier": row.get("supplier_name"),
            "amount": row.get("total_amount"),
            "status": "planned",
            "old_gdrive_path": current_rel,
            "new_gdrive_path": new_rel,
            "old_abs": _abs_from_rel(current_rel),
            "new_abs": _abs_from_rel(new_rel),
            "filename": os.path.basename(current_rel),
            "year_month": _year_month_from_rel(new_rel),
            "row": row,
            "source": "db",
        })
    return plans


def _apply_plan(plan: dict[str, Any]) -> dict[str, Any]:
    old_abs = plan["old_abs"]
    new_abs = plan["new_abs"]
    filename = plan["filename"]
    old_dir = os.path.dirname(old_abs)
    new_dir = os.path.dirname(new_abs)
    old_index = os.path.join(old_dir, "INDEX.csv")
    new_index = os.path.join(new_dir, "INDEX.csv")

    if plan.get("status") == "cleanup_residual":
        old_file_removed = False
        if os.path.exists(old_abs):
            os.remove(old_abs)
            old_file_removed = True
        moved_index_row = _remove_index_row(old_index, filename)
        removed_supplier_dir = _cleanup_supplier_dir(old_dir)
        return {
            **{k: v for k, v in plan.items() if k != "row"},
            "status": "residual_cleaned",
            "old_file_removed": old_file_removed,
            "old_index_row_found": moved_index_row is not None,
            "removed_supplier_dir": removed_supplier_dir,
        }

    if not os.path.exists(old_abs):
        if os.path.exists(new_abs):
            sm.update_purchase_staging(int(plan["staging_id"]), gdrive_path=plan["new_gdrive_path"])
            return {**plan, "status": "already_moved_db_updated"}
        return {**plan, "status": "error", "error": "old file not found"}

    os.makedirs(new_dir, exist_ok=True)
    shutil.move(old_abs, new_abs)

    moved_index_row = _remove_index_row(old_index, filename)
    if not _index_has_filename(new_index, filename):
        _append_index_csv(new_dir, moved_index_row or _build_index_row(plan["row"], filename))

    sm.update_purchase_staging(int(plan["staging_id"]), gdrive_path=plan["new_gdrive_path"])
    removed_supplier_dir = _cleanup_supplier_dir(old_dir)

    return {
        **{k: v for k, v in plan.items() if k != "row"},
        "status": "fixed",
        "old_index_row_found": moved_index_row is not None,
        "removed_supplier_dir": removed_supplier_dir,
    }


def _event_for_log(event: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in event.items() if k not in {"row"}}


def _run(args: argparse.Namespace) -> int:
    sm.init_db()
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    audit_path = log_dir / f"fix_misplaced_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    plans = _find_misplaced_from_db() if args.from_db else _find_misplaced()

    summary = {
        "dry_run": args.dry_run,
        "planned": sum(1 for p in plans if p.get("status") == "planned"),
        "cleanup_residual": sum(1 for p in plans if p.get("status") == "cleanup_residual"),
        "fixed": 0,
        "residual_cleaned": 0,
        "already_moved_db_updated": 0,
        "skipped_non_confirmed": sum(1 for p in plans if p.get("status") == "skipped_non_confirmed"),
        "skipped_no_company_segment": sum(1 for p in plans if p.get("status") == "skipped_no_company_segment"),
        "missing_db_row": sum(1 for p in plans if p.get("status") == "missing_db_row"),
        "missing_company_folder": sum(1 for p in plans if p.get("status") == "missing_company_folder"),
        "error": 0,
        "affected_indexes": [],
    }
    affected: set[tuple[int, str]] = set()
    printed = 0

    with audit_path.open("w", encoding="utf-8") as audit:
        for idx, plan in enumerate(plans, start=1):
            if plan.get("status") not in {"planned", "cleanup_residual"}:
                event = _event_for_log(plan)
            elif args.dry_run:
                event = {**_event_for_log(plan), "action": plan.get("status"), "status": "dry_run"}
            else:
                event = _apply_plan(plan)
                status = event.get("status")
                if status == "fixed":
                    summary["fixed"] += 1
                elif status == "residual_cleaned":
                    summary["residual_cleaned"] += 1
                elif status == "already_moved_db_updated":
                    summary["already_moved_db_updated"] += 1
                else:
                    summary["error"] += 1
                if event.get("year_month") and status in {"fixed", "already_moved_db_updated"}:
                    affected.add((int(event["company_id"]), event["year_month"]))

            audit.write(json.dumps({"ts": datetime.now().isoformat(), **_event_for_log(event)}, ensure_ascii=False) + "\n")
            if args.dry_run and plan.get("status") in {"planned", "cleanup_residual"} and printed < args.print_first:
                print(json.dumps(_event_for_log(event), ensure_ascii=False))
                printed += 1
            elif not args.dry_run and plan.get("status") in {"planned", "cleanup_residual"}:
                print(json.dumps(_event_for_log(event), ensure_ascii=False))

    if not args.dry_run:
        for company_id, year_month in sorted(affected):
            try:
                path = update_master_index(year_month, company_id=company_id)
                summary["affected_indexes"].append({"company_id": company_id, "year_month": year_month, "path": path})
            except Exception as e:
                summary["error"] += 1
                summary["affected_indexes"].append({"company_id": company_id, "year_month": year_month, "error": str(e)})

    summary["audit_log"] = str(audit_path)
    print(json.dumps({"summary": summary}, ensure_ascii=False))
    return 0 if summary["error"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Move misplaced backfill archives to the correct company folder")
    parser.add_argument("--from-db", action="store_true",
                        help="Scan confirmed purchase_staging rows directly instead of backfill logs")
    parser.add_argument("--dry-run", action="store_true", help="Print planned moves without touching files or DB")
    parser.add_argument("--print-first", type=int, default=5, help="Number of dry-run plans to print")
    args = parser.parse_args()
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
