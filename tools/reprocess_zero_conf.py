"""Re-run OCR for pending purchase_staging rows with zero confidence.

This tool is intentionally offline-only:
- no LINE replies
- no conversation_state changes
- no GDrive uploads
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, "config", ".env"))
except ImportError:
    pass

import state_manager as sm
from handlers.photo_handler import _classify_tax_deduction
from services.ocr_service import process_image


DB_WRITE_LOCK = threading.Lock()
LEVELS = ("AUTO_PASS", "REVIEW", "REJECT")


def parse_ids(value: str) -> list[int]:
    ids: list[int] = []
    for raw in value.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            staging_id = int(raw)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid staging id: {raw}") from exc
        if staging_id <= 0:
            raise argparse.ArgumentTypeError(f"staging id must be positive: {raw}")
        ids.append(staging_id)
    if not ids:
        raise argparse.ArgumentTypeError("--ids must contain at least one id")
    return ids


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def fetch_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    sm.init_db()
    conn = sm._get_conn()
    try:
        if args.all:
            # --below X 時改抓 0 < conf < X 的舊引擎結果做升級重跑；預設只抓 0
            max_conf = getattr(args, "below", None)
            if max_conf is not None:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM purchase_staging
                    WHERE status = 'pending'
                      AND ocr_confidence < ?
                    ORDER BY id
                    """,
                    (max_conf,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM purchase_staging
                    WHERE status = 'pending'
                      AND ocr_confidence = 0
                    ORDER BY id
                    """
                ).fetchall()
            return [dict(row) for row in rows]

        rows_by_id: dict[int, dict[str, Any] | None] = {}
        for staging_id in args.ids:
            row = conn.execute(
                "SELECT * FROM purchase_staging WHERE id = ?", (staging_id,)
            ).fetchone()
            rows_by_id[staging_id] = row_to_dict(row)

        rows: list[dict[str, Any]] = []
        for staging_id in args.ids:
            row = rows_by_id[staging_id]
            if row is None:
                rows.append(
                    {
                        "id": staging_id,
                        "company_id": None,
                        "ocr_confidence": None,
                        "_not_found": True,
                    }
                )
            else:
                rows.append(row)
        return rows
    finally:
        conn.close()


def delete_purchase_items(staging_id: int) -> None:
    conn = sqlite3.connect(sm.DB_PATH)
    try:
        conn.execute("DELETE FROM purchase_items WHERE staging_id = ?", (staging_id,))
        conn.commit()
    finally:
        conn.close()


def write_ocr_result(staging: dict[str, Any], ocr_result: Any) -> None:
    staging_id = staging["id"]
    sm.update_purchase_staging(
        staging_id,
        supplier_name=ocr_result.supplier_name,
        supplier_tax_id=ocr_result.supplier_tax_id,
        invoice_prefix=ocr_result.invoice_prefix,
        invoice_number=ocr_result.invoice_number,
        invoice_type=ocr_result.invoice_type or "",
        purchase_date=ocr_result.purchase_date or staging.get("purchase_date"),
        subtotal=ocr_result.subtotal,
        tax_amount=ocr_result.tax_amount,
        total_amount=ocr_result.total_amount,
        raw_ocr_text=(ocr_result.raw_text or "")[:2000],
        ocr_confidence=ocr_result.confidence,
    )

    tax_class = _classify_tax_deduction(
        {
            "supplier_tax_id": ocr_result.supplier_tax_id,
            "invoice_type": ocr_result.invoice_type or "",
        }
    )
    sm.update_purchase_staging(
        staging_id,
        invoice_format_code=tax_class["invoice_format_code"],
        tax_type=tax_class["tax_type"],
        deduction_code=tax_class["deduction_code"],
    )

    delete_purchase_items(staging_id)

    for item in ocr_result.items:
        ingredient = sm.find_ingredient(item.name)
        ingredient_id = ingredient["id"] if ingredient else None
        category = ingredient["category"] if ingredient else "其他"
        account_code = ingredient["account_code"] if ingredient else "5110"

        sm.add_purchase_item(
            staging_id=staging_id,
            item_name=item.name,
            quantity=item.quantity,
            unit=item.unit,
            unit_price=item.unit_price,
            amount=item.amount,
            category=category,
            account_code=account_code,
            confidence=item.confidence,
            is_handwritten=int(item.is_handwritten),
            ingredient_id=ingredient_id,
        )

    if ocr_result.supplier_name:
        supplier = sm.get_supplier(name=ocr_result.supplier_name)
        if supplier:
            sm.update_purchase_staging(
                staging_id,
                supplier_id=supplier["id"],
                supplier_tax_id=supplier.get("tax_id", ocr_result.supplier_tax_id),
            )


def base_audit_record(staging: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": staging.get("id"),
        "company_id": staging.get("company_id"),
        "before_conf": staging.get("ocr_confidence"),
        "after_conf": None,
        "supplier": "",
        "total_amount": 0,
        "items": 0,
        "level": "",
        "elapsed_s": 0,
        "outcome": "",
        "error": "",
    }


def process_one(staging: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    started = time.monotonic()
    record = base_audit_record(staging)

    try:
        if staging.get("_not_found"):
            record["outcome"] = "error"
            record["error"] = "staging row not found"
            return record

        image_path = staging.get("local_image_path") or ""
        if not image_path or not os.path.exists(image_path):
            record["outcome"] = "missing_image"
            record["error"] = image_path
            return record

        ocr_result = process_image(image_path)
        record.update(
            {
                "after_conf": ocr_result.confidence,
                "supplier": ocr_result.supplier_name,
                "total_amount": ocr_result.total_amount,
                "items": len(ocr_result.items),
                "level": ocr_result.result_level,
            }
        )

        if ocr_result.confidence == 0:
            record["outcome"] = "still_zero"
            return record

        if not dry_run:
            with DB_WRITE_LOCK:
                write_ocr_result(staging, ocr_result)

        record["outcome"] = "updated"
        return record
    except Exception as exc:
        record["outcome"] = "error"
        record["error"] = str(exc)
        return record
    finally:
        record["elapsed_s"] = round(time.monotonic() - started, 3)


def make_log_path() -> str:
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(ROOT, "logs", f"reprocess_zero_conf_{stamp}.jsonl")


def print_record(record: dict[str, Any], dry_run: bool) -> None:
    prefix = "DRY-RUN " if dry_run and record["outcome"] == "updated" else ""
    if record["outcome"] == "updated":
        print(
            f"{prefix}#{record['id']}: {record['supplier'] or '未知供應商'} "
            f"${record['total_amount']:,.0f} conf={record['after_conf']:.3f} "
            f"level={record['level']} items={record['items']} "
            f"elapsed={record['elapsed_s']:.1f}s"
        )
    elif record["outcome"] == "still_zero":
        print(f"#{record['id']}: still_zero elapsed={record['elapsed_s']:.1f}s")
    elif record["outcome"] == "missing_image":
        print(f"#{record['id']}: missing_image {record['error']}")
    else:
        print(f"#{record['id']}: error {record['error']}")


def print_summary(records: list[dict[str, Any]], log_path: str) -> None:
    outcomes = Counter(record["outcome"] for record in records)
    levels = Counter(record["level"] for record in records if record["level"] in LEVELS)

    print("\n=== summary ===")
    print(
        "total={total} updated={updated} still_zero={still_zero} "
        "missing_image={missing_image} error={error}".format(
            total=len(records),
            updated=outcomes.get("updated", 0),
            still_zero=outcomes.get("still_zero", 0),
            missing_image=outcomes.get("missing_image", 0),
            error=outcomes.get("error", 0),
        )
    )
    print(
        "confidence_levels "
        + " ".join(f"{level}={levels.get(level, 0)}" for level in LEVELS)
    )
    print(f"audit_log={log_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline re-OCR for purchase_staging rows with ocr_confidence=0."
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--ids", type=parse_ids, help="Comma-separated staging ids")
    target.add_argument(
        "--all",
        action="store_true",
        help="Process all pending rows with ocr_confidence=0",
    )
    parser.add_argument(
        "--below",
        type=float,
        default=None,
        help="With --all: re-OCR pending rows with ocr_confidence < BELOW (upgrade old-engine results)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="OCR concurrency; DB writes are serialized (default: 3)",
    )
    parser.add_argument("--dry-run", action="store_true", help="OCR only; do not write DB")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.workers <= 0:
        parser.error("--workers must be positive")

    rows = fetch_rows(args)
    log_path = make_log_path()
    records: list[dict[str, Any]] = []

    print(
        f"processing {len(rows)} row(s), workers={args.workers}, "
        f"dry_run={args.dry_run}"
    )

    with open(log_path, "a", encoding="utf-8") as log_file:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_row = {
                executor.submit(process_one, row, args.dry_run): row for row in rows
            }
            for done_count, future in enumerate(as_completed(future_to_row), 1):
                record = future.result()
                records.append(record)
                log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                log_file.flush()
                print_record(record, args.dry_run)
                if done_count % 10 == 0 or done_count == len(rows):
                    print(f"[{done_count}/{len(rows)}]")

    print_summary(records, log_path)
    return 0 if not any(record["outcome"] == "error" for record in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
