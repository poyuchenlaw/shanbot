#!/usr/bin/env python3
"""回填現有 purchase_staging 記錄的扣抵分類代號。

根據 supplier_tax_id 和 invoice_type 重新分類：
- 有統編 + 三聯式 → deduction_code=1, invoice_format_code=21
- 有統編 + 電子發票 → deduction_code=1, invoice_format_code=25
- 有統編 + 其他 → deduction_code=2, invoice_format_code=22
- 無統編 → deduction_code=2, invoice_format_code=22

用法：
    python scripts/backfill_deduction_codes.py [--dry-run]
"""

import os
import sys

# 加入專案根目錄到 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import state_manager as sm


def _classify(supplier_tax_id: str, invoice_type: str) -> dict:
    """同 photo_handler._classify_tax_deduction 的邏輯"""
    has_tax_id = bool(supplier_tax_id and supplier_tax_id.strip())
    inv = invoice_type or "receipt"

    if inv in ("免稅", "tax_exempt"):
        return {"deduction_code": "2", "tax_type": "3", "invoice_format_code": "22"}
    if has_tax_id and inv in ("三聯式", "triplicate"):
        return {"deduction_code": "1", "tax_type": "1", "invoice_format_code": "21"}
    elif has_tax_id and inv in ("電子發票", "electronic"):
        return {"deduction_code": "1", "tax_type": "1", "invoice_format_code": "25"}
    elif has_tax_id:
        return {"deduction_code": "2", "tax_type": "1", "invoice_format_code": "22"}
    else:
        return {"deduction_code": "2", "tax_type": "1", "invoice_format_code": "22"}


def backfill(dry_run: bool = False):
    """執行回填"""
    conn = sm._get_conn()
    rows = conn.execute(
        "SELECT id, supplier_tax_id, invoice_type, deduction_code, "
        "tax_type, invoice_format_code FROM purchase_staging"
    ).fetchall()
    conn.close()

    updated = 0
    skipped = 0

    for row in rows:
        row_dict = dict(row)
        sid = row_dict["id"]
        tax_id = row_dict.get("supplier_tax_id", "") or ""
        inv_type = row_dict.get("invoice_type", "") or ""

        new_class = _classify(tax_id, inv_type)

        # 比較是否有變化
        changed = (
            str(row_dict.get("deduction_code", "")) != new_class["deduction_code"]
            or str(row_dict.get("tax_type", "")) != new_class["tax_type"]
            or str(row_dict.get("invoice_format_code", "")) != new_class["invoice_format_code"]
        )

        if changed:
            if dry_run:
                print(
                    f"  [DRY-RUN] #{sid}: tax_id='{tax_id}' inv='{inv_type}' "
                    f"→ deduction={new_class['deduction_code']} "
                    f"tax_type={new_class['tax_type']} "
                    f"format={new_class['invoice_format_code']}"
                )
            else:
                sm.update_purchase_staging(
                    sid,
                    deduction_code=new_class["deduction_code"],
                    tax_type=new_class["tax_type"],
                    invoice_format_code=new_class["invoice_format_code"],
                )
            updated += 1
        else:
            skipped += 1

    action = "Would update" if dry_run else "Updated"
    print(f"\n{action} {updated} records, skipped {skipped} (already correct)")
    print(f"Total: {len(rows)} records")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("=== DRY RUN MODE ===\n")
    backfill(dry_run=dry_run)
