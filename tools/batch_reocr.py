"""批次重新 OCR — 針對 OCR 失敗（confidence=0 / 無供應商）的 pending 記錄重跑辨識

用法：
    python3 tools/batch_reocr.py --dry-run     # 預覽，不修改
    python3 tools/batch_reocr.py --limit 10    # 只處理 10 張
    python3 tools/batch_reocr.py               # 全部處理
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", ".env"))

import state_manager as sm
from services.ocr_service import process_image

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("batch_reocr")


def get_failed_entries():
    """取得 OCR 失敗的 pending 記錄"""
    sm.init_db()
    conn = sm._get_conn()
    rows = conn.execute("""
        SELECT id, local_image_path, ocr_confidence, supplier_name,
               total_amount, company_id, purchase_date
        FROM purchase_staging
        WHERE status = 'pending'
          AND (ocr_confidence = 0 OR ocr_confidence IS NULL
               OR supplier_name IS NULL OR supplier_name = '')
        ORDER BY id
    """).fetchall()
    return [dict(r) for r in rows]


def reocr_entry(entry: dict, dry_run: bool = False) -> dict:
    """重新 OCR 一筆記錄"""
    sid = entry["id"]
    path = entry["local_image_path"]

    if not path or not os.path.exists(path):
        return {"id": sid, "status": "missing_image", "path": path}

    if dry_run:
        return {"id": sid, "status": "dry_run", "path": path}

    try:
        result = process_image(path)

        # 更新 DB
        sm.update_purchase_staging(
            sid,
            supplier_name=result.supplier_name,
            supplier_tax_id=result.supplier_tax_id,
            invoice_prefix=result.invoice_prefix,
            invoice_number=result.invoice_number,
            invoice_type=result.invoice_type or "",
            purchase_date=result.purchase_date or entry["purchase_date"],
            subtotal=result.subtotal,
            tax_amount=result.tax_amount,
            total_amount=result.total_amount,
            raw_ocr_text=result.raw_text[:2000],
            ocr_confidence=result.confidence,
        )

        # 稅務分類
        from handlers.photo_handler import _classify_tax_deduction
        tax_class = _classify_tax_deduction({
            "supplier_tax_id": result.supplier_tax_id,
            "invoice_type": result.invoice_type or "",
        })
        sm.update_purchase_staging(
            sid,
            invoice_format_code=tax_class["invoice_format_code"],
            tax_type=tax_class["tax_type"],
            deduction_code=tax_class["deduction_code"],
        )

        # 更新品項（先刪舊的再新增）
        conn = sm._get_conn()
        conn.execute("DELETE FROM purchase_items WHERE staging_id = ?", (sid,))
        conn.commit()

        for item in result.items:
            ingredient = sm.find_ingredient(item.name)
            ingredient_id = ingredient["id"] if ingredient else None
            category = ingredient["category"] if ingredient else "其他"
            account_code = ingredient["account_code"] if ingredient else "5110"

            sm.add_purchase_item(
                staging_id=sid,
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

        # 匹配供應商
        if result.supplier_name:
            supplier = sm.get_supplier(name=result.supplier_name)
            if supplier:
                sm.update_purchase_staging(
                    sid,
                    supplier_id=supplier["id"],
                    supplier_tax_id=supplier.get("tax_id", result.supplier_tax_id),
                )

        return {
            "id": sid,
            "status": "success",
            "supplier": result.supplier_name,
            "amount": result.total_amount,
            "confidence": result.confidence,
            "level": result.result_level,
            "items": len(result.items),
        }

    except Exception as e:
        logger.error(f"Re-OCR #{sid} failed: {e}", exc_info=True)
        return {"id": sid, "status": "error", "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="批次重新 OCR")
    parser.add_argument("--dry-run", action="store_true", help="預覽模式")
    parser.add_argument("--limit", type=int, default=0, help="限制處理數量")
    args = parser.parse_args()

    entries = get_failed_entries()
    if args.limit > 0:
        entries = entries[:args.limit]

    logger.info(f"Found {len(entries)} entries needing re-OCR")

    success = 0
    errors = 0
    missing = 0

    for i, entry in enumerate(entries, 1):
        logger.info(f"[{i}/{len(entries)}] Re-OCR #{entry['id']}...")
        result = reocr_entry(entry, dry_run=args.dry_run)

        if result["status"] == "success":
            success += 1
            logger.info(
                f"  ✅ #{result['id']}: {result['supplier']} "
                f"${result['amount']:,.0f} conf={result['confidence']:.2f} "
                f"[{result['level']}] {result['items']} items"
            )
        elif result["status"] == "missing_image":
            missing += 1
            logger.warning(f"  ❌ #{result['id']}: image missing at {result['path']}")
        elif result["status"] == "dry_run":
            logger.info(f"  🔍 #{result['id']}: would re-OCR {result['path']}")
        else:
            errors += 1
            logger.error(f"  ❌ #{result['id']}: {result.get('error', 'unknown')}")

        # Gemini rate limit: 避免太快
        if not args.dry_run and i < len(entries):
            time.sleep(2)

    logger.info(f"\n=== 完成 ===")
    logger.info(f"成功: {success} | 失敗: {errors} | 圖片遺失: {missing}")
    if args.dry_run:
        logger.info(f"（預覽模式，未實際修改）")


if __name__ == "__main__":
    main()
