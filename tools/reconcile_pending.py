#!/usr/bin/env python3
"""reconcile_pending — 盤點 / 處理 purchase_staging 卡住的 pending 紀錄。

用法：
  python3 tools/reconcile_pending.py --report                    只列清單，不動作
  python3 tools/reconcile_pending.py --report --min-age 3        過濾 pending > 3 天
  python3 tools/reconcile_pending.py --auto-confirm --dry-run    預覽自動歸檔（不執行）
  python3 tools/reconcile_pending.py --auto-confirm              執行自動歸檔（confidence >= threshold）
  python3 tools/reconcile_pending.py --auto-confirm --threshold 0.8 --company 3
  python3 tools/reconcile_pending.py --line-repush --dry-run     預覽要重推 LINE 的低信心單

策略：
  - 高信心 + 資訊完整 + 有實體圖檔  → auto-confirm + archive_receipt
  - 低信心 / 缺欄位 / 缺圖檔        → 列入 LINE 重推清單（由 --line-repush 處理，A2 實作）
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import state_manager as sm
from services.gdrive_service import archive_receipt


REQUIRED_FIELDS = ["supplier_name", "purchase_date", "total_amount"]


def _age_days(created_at: str) -> float:
    try:
        ts = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - ts).total_seconds() / 86400
    except Exception:
        return 0.0


def _missing_fields(staging: dict) -> list[str]:
    missing = []
    for f in REQUIRED_FIELDS:
        v = staging.get(f)
        if not v or v in ("unknown", "未知", 0, "0"):
            missing.append(f)
    return missing


def _has_local_image(staging: dict) -> bool:
    p = staging.get("local_image_path")
    return bool(p) and os.path.exists(p)


def classify(staging: dict, threshold: float) -> str:
    """auto | repush | discard_candidate"""
    if _missing_fields(staging) or not _has_local_image(staging):
        return "repush"
    conf = staging.get("ocr_confidence") or 0
    if conf >= threshold:
        return "auto"
    return "repush"


def _fetch_pending(company_id: Optional[int], min_age_days: float) -> list[dict]:
    rows = sm.get_pending_stagings(company_id=company_id)
    return [r for r in rows if _age_days(r.get("created_at", "")) >= min_age_days]


def cmd_report(rows: list[dict], threshold: float):
    if not rows:
        print("沒有符合條件的 pending 紀錄。")
        return

    by_company: dict[int, list[dict]] = {}
    for r in rows:
        by_company.setdefault(r.get("company_id") or 0, []).append(r)

    cls_counter = {"auto": 0, "repush": 0}
    print(f"\n{'='*84}")
    print(f"Pending 盤點（共 {len(rows)} 筆，threshold={threshold}）")
    print(f"{'='*84}")

    for cid, items in sorted(by_company.items()):
        print(f"\n【公司 #{cid}】 {len(items)} 筆")
        print(f"{'ID':>5}  {'age(天)':>7}  {'conf':>5}  {'類別':<7}  {'供應商':<14}  {'金額':>9}  {'缺欄/缺圖'}")
        print("-" * 84)
        for r in items:
            cls = classify(r, threshold)
            cls_counter[cls] += 1
            age = _age_days(r.get("created_at", ""))
            conf = r.get("ocr_confidence") or 0
            supplier = (r.get("supplier_name") or "(無)")[:14]
            amt = r.get("total_amount") or 0
            missing = _missing_fields(r)
            no_img = "" if _has_local_image(r) else "[無圖]"
            tags = ",".join(missing) + ("," if missing and no_img else "") + no_img
            print(f"  #{r['id']:<3}  {age:>7.1f}  {conf:>5.2f}  {cls:<7}  {supplier:<14}  ${amt:>8,.0f}  {tags}")

    print(f"\n{'='*84}")
    print(f"分類：auto-confirmable {cls_counter['auto']}、需 LINE 重推 {cls_counter['repush']}")
    print(f"{'='*84}\n")


async def cmd_auto_confirm(rows: list[dict], threshold: float, dry_run: bool):
    targets = [r for r in rows if classify(r, threshold) == "auto"]
    if not targets:
        print("沒有可自動確認的紀錄。")
        return

    print(f"\n{'DRY-RUN ' if dry_run else ''}將自動確認 + 歸檔 {len(targets)} 筆：")
    ok, fail = 0, 0
    for r in targets:
        sid = r["id"]
        cid = r.get("company_id") or 1
        print(f"  #{sid} co={cid} conf={r.get('ocr_confidence', 0):.2f} "
              f"{r.get('supplier_name', '')} ${r.get('total_amount', 0):,.0f}", end="  ")
        if dry_run:
            print("(dry-run)")
            continue
        try:
            sm.confirm_staging(sid)
            items = sm.get_purchase_items(sid)
            ocr_summary = {
                "invoice_number": r.get("invoice_number", ""),
                "subtotal": r.get("subtotal", 0),
                "tax_amount": r.get("tax_amount", 0),
                "items": [{"name": it["item_name"]} for it in items],
            }
            result = await archive_receipt(
                local_path=r["local_image_path"],
                purchase_date=r.get("purchase_date", ""),
                supplier_name=r.get("supplier_name", ""),
                total_amount=r.get("total_amount", 0),
                staging_id=sid,
                ocr_summary=ocr_summary,
                pending_gdrive_path=r.get("gdrive_path") if "待確認" in (r.get("gdrive_path") or "") else None,
                company_id=cid,
            )
            if result.get("gdrive_path"):
                sm.update_purchase_staging(sid, gdrive_path=result["gdrive_path"])
                print(f"OK → {result['filename']}")
                ok += 1
            else:
                print(f"FAIL: {result.get('error', 'no path returned')}")
                fail += 1
        except Exception as e:
            print(f"EXC: {e}")
            fail += 1

    print(f"\n結果：成功 {ok}、失敗 {fail}（剩餘 {len(rows) - len(targets)} 筆需 LINE 重推）\n")


def _build_repush_message(items: list[dict], page: int, total_pages: int) -> str:
    lines = [f"📋 待處理收據（第 {page}/{total_pages} 頁，共 {sum(1 for _ in items)} 筆）", ""]
    for r in items:
        sid = r["id"]
        supplier = r.get("supplier_name") or "(供應商未知)"
        date = r.get("purchase_date") or "(日期未知)"
        amt = r.get("total_amount") or 0
        conf = r.get("ocr_confidence") or 0
        missing = _missing_fields(r)
        amt_str = f"${amt:,.0f}" if amt else "金額待補"
        flag = f"  ⚠️缺：{','.join(missing)}" if missing else ""
        lines.append(f"#{sid}  {supplier[:14]}  {date}  {amt_str}  (conf={conf:.2f}){flag}")
    lines.append("")
    lines.append("回「最終確認 #ID」歸檔｜「拒絕 #ID」捨棄｜「修改 #ID 欄位 值」更正")
    return "\n".join(lines)


async def cmd_line_repush(rows: list[dict], threshold: float, dry_run: bool, page_size: int = 10):
    """把低信心 / 缺欄位的單據重推 LINE，每頁 page_size 筆摘要。"""
    targets = [r for r in rows if classify(r, threshold) == "repush"]
    if not targets:
        print("沒有需要 LINE 重推的紀錄。")
        return

    by_chat: dict[tuple[str, int], list[dict]] = {}
    for r in targets:
        chat_id = r.get("chat_id")
        cid = r.get("company_id") or 0
        if not chat_id or chat_id == "cymon-backfill":
            continue
        by_chat.setdefault((chat_id, cid), []).append(r)

    skipped = sum(1 for r in targets if not r.get("chat_id") or r.get("chat_id") == "cymon-backfill")
    print(f"\n{'DRY-RUN ' if dry_run else ''}將 LINE 重推 {len(targets) - skipped} 筆"
          f"（跳過 {skipped} 筆 backfill / 無 chat_id）：")
    for (chat, cid), items in sorted(by_chat.items()):
        pages = (len(items) + page_size - 1) // page_size
        print(f"  公司 #{cid} chat={chat[:12]}…：{len(items)} 筆 → {pages} 頁")

    if dry_run:
        return

    # LineService 需要 company_cache 先初始化才能取 token
    try:
        from services.company_service import init_companies
        init_companies()
    except Exception as e:
        print(f"⚠️ init_companies 失敗：{e}")

    from services.line_service import LineService
    line = LineService()

    sent_pages, fail_pages = 0, 0
    for (chat, cid), items in sorted(by_chat.items()):
        pages = (len(items) + page_size - 1) // page_size
        for p in range(pages):
            chunk = items[p * page_size:(p + 1) * page_size]
            msg = _build_repush_message(chunk, p + 1, pages)
            try:
                ok = line.push(chat, msg, company_id=cid)
                if ok:
                    sent_pages += 1
                else:
                    fail_pages += 1
                    print(f"  ⚠️ push 回傳 False：公司 #{cid} 第 {p+1} 頁")
            except Exception as e:
                fail_pages += 1
                print(f"  ⚠️ 公司 #{cid} 第 {p+1} 頁推送 EXC：{e}")

    print(f"\n結果：成功 {sent_pages} 頁、失敗 {fail_pages} 頁\n")


def main():
    p = argparse.ArgumentParser(description="reconcile pending purchase_staging records")
    p.add_argument("--company", type=int, default=None, help="只處理指定公司（1–5）")
    p.add_argument("--min-age", type=float, default=0.0, help="只處理 pending >= N 天的紀錄")
    p.add_argument("--threshold", type=float, default=0.7, help="auto-confirm OCR 信心閾值")
    p.add_argument("--report", action="store_true", help="列出清單（預設動作）")
    p.add_argument("--auto-confirm", action="store_true", help="執行高信心自動確認 + 歸檔")
    p.add_argument("--line-repush", action="store_true", help="把低信心單推回 LINE 等人工確認")
    p.add_argument("--page-size", type=int, default=10, help="LINE 重推每頁筆數")
    p.add_argument("--dry-run", action="store_true", help="預覽，不實際執行")
    args = p.parse_args()

    sm.init_db()
    rows = _fetch_pending(args.company, args.min_age)

    if not (args.auto_confirm or args.line_repush) or args.report:
        cmd_report(rows, args.threshold)

    if args.auto_confirm:
        asyncio.run(cmd_auto_confirm(rows, args.threshold, args.dry_run))

    if args.line_repush:
        asyncio.run(cmd_line_repush(rows, args.threshold, args.dry_run, args.page_size))


if __name__ == "__main__":
    main()
