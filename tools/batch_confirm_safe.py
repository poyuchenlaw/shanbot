#!/usr/bin/env python3
"""安全批次 confirm 工具 — 對符合嚴格條件的 staging 自動 confirm + 過帳

⚠️ 高風險工具。預設 dry-run。--apply 才會實際 confirm + generate journal entries。

安全條件（同時滿足才會 confirm）：
  1. status='pending'
  2. handler_name 在白名單（預設 'cymon-backfill' — 由我們補檔來的，不是廚房手動標記過的）
  3. total_amount > 0
  4. supplier_name 長度 >= 3
  5. supplier_name 不在 OCR 截斷黑名單

不符合的留 pending 並列出原因。

用法：
  python3 batch_confirm_safe.py --company-id 3 --dry-run
  python3 batch_confirm_safe.py --company-id 3 --apply
"""

import argparse
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", ".env"))

import state_manager as sm
from services.accounting_service import generate_journal_entries, verify_balance

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("batch_confirm")

# OCR 截斷或誤判的供應商名稱黑名單（合併過後不該再出現，但保險起見）
SUPPLIER_BLACKLIST = {"美", "振", "台達", "听", "上諭", "黃子蔬菜物流"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--handler", default="cymon-backfill",
                        help="只處理這個 handler 的 staging。傳 'null' 可選 NULL handler（如使用者直接從 LINE 進來的）")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true",
                        help="實際執行 confirm + generate journal entries")
    args = parser.parse_args()

    if args.apply:
        args.dry_run = False

    sm.init_db()

    # 拉所有候選 staging
    conn = sm._get_conn()
    if args.handler.lower() in ("null", "empty", ""):
        rows = conn.execute(
            "SELECT * FROM purchase_staging "
            "WHERE company_id=? AND status='pending' "
            "AND (handler_name IS NULL OR handler_name='') "
            "ORDER BY purchase_date, id",
            (args.company_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM purchase_staging "
            "WHERE company_id=? AND status='pending' AND handler_name=? "
            "ORDER BY purchase_date, id",
            (args.company_id, args.handler),
        ).fetchall()
    conn.close()

    safe = []
    skipped = []
    for r in rows:
        d = dict(r)
        reasons = []
        if d["total_amount"] <= 0:
            reasons.append("金額=0")
        if not d["supplier_name"] or len(d["supplier_name"]) < 3:
            reasons.append(f"供應商過短({d['supplier_name']!r})")
        if d["supplier_name"] in SUPPLIER_BLACKLIST:
            reasons.append(f"供應商在黑名單({d['supplier_name']})")
        if reasons:
            skipped.append((d, reasons))
        else:
            safe.append(d)

    logger.info(f"=== 候選統計 ===")
    logger.info(f"  總 pending (handler={args.handler}): {len(rows)}")
    logger.info(f"  ✓ 符合 confirm 條件: {len(safe)}  總額=${sum(s['total_amount'] for s in safe):.0f}")
    logger.info(f"  ⊙ 跳過待人工: {len(skipped)}")

    # 顯示要 confirm 的
    if safe:
        logger.info(f"\n=== 將 confirm 的（前 20）===")
        for s in safe[:20]:
            logger.info(f"  #{s['id']:<4} {s['purchase_date']} {s['supplier_name'][:20]:<22} ${s['total_amount']:>8.0f}")
        if len(safe) > 20:
            logger.info(f"  ... 還有 {len(safe)-20} 筆")

    if args.dry_run and not args.apply:
        logger.info(f"\n[DRY-RUN] 沒有實際變更。要執行請加 --apply")
        return

    # 實際執行
    logger.info(f"\n=== 開始 confirm + 過帳 ===")
    stats = {"confirmed": 0, "balanced": 0, "unbalanced": 0, "errors": 0}
    total_debit_sum = 0
    total_credit_sum = 0
    for s in safe:
        sid = s["id"]
        try:
            sm.confirm_staging(sid)
            entries = generate_journal_entries(sid)
            check = verify_balance(sid)
            if check["balanced"]:
                stats["balanced"] += 1
            else:
                stats["unbalanced"] += 1
                logger.warning(f"  ⚠ #{sid} 借貸不平衡 diff=${check['difference']}")
            total_debit_sum += check["total_debit"]
            total_credit_sum += check["total_credit"]
            stats["confirmed"] += 1
            if stats["confirmed"] % 20 == 0:
                logger.info(f"  ... 已過帳 {stats['confirmed']} 筆")
        except Exception as e:
            stats["errors"] += 1
            logger.error(f"  ✗ #{sid} 過帳失敗: {e}")

    logger.info(f"\n=== 完成 ===")
    logger.info(f"  Confirmed: {stats['confirmed']}")
    logger.info(f"  借貸平衡: {stats['balanced']}")
    logger.info(f"  借貸不平衡: {stats['unbalanced']}")
    logger.info(f"  錯誤: {stats['errors']}")
    logger.info(f"  借方合計: ${total_debit_sum:,.0f}")
    logger.info(f"  貸方合計: ${total_credit_sum:,.0f}")

    # 跳過清單存到 GDrive
    if skipped:
        report_path = f"/mnt/h/我的雲端硬碟/Claude/260407_shanbot_補檔/待人工確認_company{args.company_id}.csv"
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        try:
            with open(report_path, "w", encoding="utf-8-sig") as f:
                f.write("staging_id,purchase_date,supplier_name,total_amount,gdrive_path,跳過原因\n")
                for d, reasons in skipped:
                    f.write(f"{d['id']},{d['purchase_date']},{d['supplier_name']},"
                            f"{d['total_amount']},{d.get('gdrive_path','')},{';'.join(reasons)}\n")
            logger.info(f"\n  📋 待人工確認清單寫入：{report_path}")
        except Exception as e:
            logger.warning(f"寫 CSV 失敗: {e}")


if __name__ == "__main__":
    main()
