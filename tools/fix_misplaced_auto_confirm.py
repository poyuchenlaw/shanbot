#!/usr/bin/env python3
"""搬遷事故補救 — 把因 init_companies 缺失誤歸到「福利社/」的檔，移到正確公司資料夾。

2026-04-23 事故：reconcile_pending --auto-confirm 沒 init_companies，導致
get_company_base_path() 全部 fallback 到公司 1 default (福利社)，52 筆非公司 1
的檔案誤放到福利社/ 資料夾下。

本腳本：
  1. 掃 DB 今天 auto-confirmed、company_id != 1 但 gdrive_path 開頭是「福利社/」的紀錄
  2. 找到檔案實體（福利社/2026/04月/收據憑證/{supplier}/{filename}）
  3. 搬到正確目錄（{公司簡稱}/2026/04月/收據憑證/{supplier}/{filename}）
  4. 更新 DB gdrive_path
  5. 修 INDEX.csv（從福利社/ 移除，加到正確公司/）
  6. --dry-run 預覽不動
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import state_manager as sm
from services.company_service import init_companies
from services.gdrive_service import GDRIVE_LOCAL, get_company_base_path


def _find_misplaced() -> list[dict]:
    conn = sm._get_conn()
    rows = conn.execute("""
        SELECT id, company_id, purchase_date, supplier_name, total_amount,
               gdrive_path, confirmed_at, invoice_number, subtotal, tax_amount
        FROM purchase_staging
        WHERE status='confirmed'
          AND date(confirmed_at) = date('now','localtime')
          AND company_id != 1
          AND gdrive_path LIKE '福利社/%'
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _csv_remove_row(csv_path: str, staging_id: int):
    if not os.path.exists(csv_path):
        return
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys()) if rows else []
    filtered = [r for r in rows if r.get("來源") != f"staging#{staging_id}"]
    if len(filtered) == len(rows):
        return
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(filtered)


def _csv_add_row(csv_path: str, row: dict):
    headers = ["日期", "供應商", "發票號碼", "品項數", "未稅金額",
               "稅額", "總金額", "檔案名稱", "歸檔時間", "來源"]
    exists = os.path.exists(csv_path)
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        if not exists:
            w.writeheader()
        w.writerow(row)


def migrate(dry_run: bool):
    init_companies()
    rows = _find_misplaced()
    print(f"找到 {len(rows)} 筆誤歸到福利社/ 的紀錄")
    if not rows:
        return

    ok, fail = 0, 0
    for r in rows:
        sid = r["id"]
        cid = r["company_id"]
        old_rel = r["gdrive_path"]               # 福利社/2026/04月/收據憑證/{supplier}/xxx
        old_abs = os.path.join(GDRIVE_LOCAL, old_rel)

        # 組新路徑
        correct_base = get_company_base_path(cid)
        # old_rel 拆：福利社/{rest...}
        parts = old_rel.split("/", 1)
        if len(parts) != 2:
            print(f"  ⚠️ #{sid} gdrive_path 格式異常：{old_rel}")
            fail += 1
            continue
        new_abs = os.path.join(correct_base, parts[1])
        new_rel = os.path.relpath(new_abs, GDRIVE_LOCAL)

        # 取 supplier_folder name from path
        filename = os.path.basename(old_abs)
        old_dir = os.path.dirname(old_abs)
        new_dir = os.path.dirname(new_abs)

        print(f"  #{sid} co={cid} {filename}")
        print(f"      from: {old_rel}")
        print(f"      to:   {new_rel}")

        if dry_run:
            continue

        if not os.path.exists(old_abs):
            print(f"      ⚠️ 原檔不存在，跳過")
            fail += 1
            continue

        try:
            os.makedirs(new_dir, exist_ok=True)
            shutil.move(old_abs, new_abs)
        except Exception as e:
            print(f"      ❌ 搬檔失敗：{e}")
            fail += 1
            continue

        # 舊 INDEX.csv 移除
        try:
            _csv_remove_row(os.path.join(old_dir, "INDEX.csv"), sid)
        except Exception as e:
            print(f"      ⚠️ 舊 INDEX 清除失敗：{e}")

        # 新 INDEX.csv 加上
        try:
            _csv_add_row(os.path.join(new_dir, "INDEX.csv"), {
                "日期": r["purchase_date"],
                "供應商": r["supplier_name"] or "",
                "發票號碼": r["invoice_number"] or "",
                "品項數": 0,
                "未稅金額": r["subtotal"] or 0,
                "稅額": r["tax_amount"] or 0,
                "總金額": r["total_amount"],
                "檔案名稱": filename,
                "歸檔時間": "(migrate 2026-04-23)",
                "來源": f"staging#{sid}",
            })
        except Exception as e:
            print(f"      ⚠️ 新 INDEX 寫入失敗：{e}")

        # DB 更新
        sm.update_purchase_staging(sid, gdrive_path=new_rel)
        ok += 1

    print(f"\n結果：成功 {ok}、失敗 {fail}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    sm.init_db()
    migrate(args.dry_run)


if __name__ == "__main__":
    main()
