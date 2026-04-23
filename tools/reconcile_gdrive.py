#!/usr/bin/env python3
"""reconcile_gdrive — 比對 GDrive 收據憑證 / 實體檔 vs DB confirmed 紀錄。

用法：
  python3 tools/reconcile_gdrive.py                       全部公司全部月份
  python3 tools/reconcile_gdrive.py --company 3 --month 2026-03
  python3 tools/reconcile_gdrive.py --rebuild-index       自動重建漏的 INDEX.csv
  python3 tools/reconcile_gdrive.py --csv reconcile.csv   匯出差異到 CSV

差異分類：
  [DB-only]    DB confirmed 但 GDrive 找不到實體檔（歸檔失敗 / 檔被刪）
  [FS-only]    GDrive 有檔但 DB 無對應 staging（手動上傳 / 舊資料）
  [INDEX-miss] 檔案實體存在但 INDEX.csv 沒收錄
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import defaultdict
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import state_manager as sm
from services.gdrive_service import (
    GDRIVE_LOCAL,
    MONTHLY_FOLDERS,
    get_company_base_path,
    _append_index_csv,
)


FILENAME_RE = re.compile(r"^(\d{6})_(.+?)_(\d+)_#(\d+)(\.[\w]+)$")


def _parse_filename(fname: str) -> Optional[dict]:
    m = FILENAME_RE.match(fname)
    if not m:
        return None
    yymmdd, supplier, amount, sid, ext = m.groups()
    return {
        "date": f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}",
        "supplier": supplier,
        "amount": int(amount),
        "staging_id": int(sid),
        "ext": ext,
        "filename": fname,
    }


def _scan_dir_for_receipts(month_dir: str, found: dict, fallback_marker: str = ""):
    """掃一個「收據憑證/」根（含子資料夾＋直接檔），回填 found dict"""
    if not os.path.isdir(month_dir):
        return
    # 直接檔（舊單租戶模式）
    for fname in os.listdir(month_dir):
        fp = os.path.join(month_dir, fname)
        if os.path.isfile(fp):
            if fname in ("INDEX.csv", ".DS_Store", "desktop.ini"):
                continue
            parsed = _parse_filename(fname)
            if parsed:
                parsed["dest_dir"] = month_dir
                parsed["supplier_folder"] = "(無分類)"
                parsed["fallback"] = fallback_marker
                found[parsed["staging_id"]] = parsed
        elif os.path.isdir(fp):
            for fname2 in os.listdir(fp):
                if fname2 in ("INDEX.csv", ".DS_Store", "desktop.ini"):
                    continue
                parsed = _parse_filename(fname2)
                if not parsed:
                    continue
                parsed["dest_dir"] = fp
                parsed["supplier_folder"] = fname
                parsed["fallback"] = fallback_marker
                found[parsed["staging_id"]] = parsed


def _scan_company_month(company_id: int, year_month: str) -> dict:
    """回傳 {staging_id: {filename, dest_dir, supplier_folder, fallback}}

    雙路徑掃描：先掃公司專屬目錄，再 fallback 掃 GDrive 根目錄（舊單租戶歸檔）。
    """
    found: dict[int, dict] = {}
    year, month = year_month.split("-")
    month_seg = f"{int(month):02d}月"

    base = get_company_base_path(company_id)
    _scan_dir_for_receipts(os.path.join(base, year, month_seg, "收據憑證"), found, "")

    # 根目錄 fallback 只對公司 1 (default) 生效，避免多公司 reconcile 時
    # 把公司 1 的檔誤判成其他公司的 FS-only
    if company_id == 1:
        root_month = os.path.join(GDRIVE_LOCAL, year, month_seg, "收據憑證")
        fallback_found: dict[int, dict] = {}
        _scan_dir_for_receipts(root_month, fallback_found, "ROOT")
        for sid, info in fallback_found.items():
            if sid not in found:
                found[sid] = info

    return found


def _index_csv_ids(supplier_dir: str) -> set[int]:
    csv_path = os.path.join(supplier_dir, "INDEX.csv")
    if not os.path.exists(csv_path):
        return set()
    ids: set[int] = set()
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                src = row.get("來源", "")
                m = re.match(r"staging#(\d+)", src)
                if m:
                    ids.add(int(m.group(1)))
    except Exception:
        pass
    return ids


def _all_year_months_for_company(company_id: int) -> list[str]:
    base = get_company_base_path(company_id)
    yms: list[str] = []
    if not os.path.isdir(base):
        return yms
    for year in os.listdir(base):
        ypath = os.path.join(base, year)
        if not (os.path.isdir(ypath) and year.isdigit() and len(year) == 4):
            continue
        for month_dir in os.listdir(ypath):
            mm = re.match(r"^(\d{1,2})月$", month_dir)
            if mm:
                yms.append(f"{year}-{int(mm.group(1)):02d}")
    return sorted(set(yms))


def reconcile(company_id: int, year_month: str, rebuild_index: bool) -> list[dict]:
    diffs: list[dict] = []

    fs = _scan_company_month(company_id, year_month)
    db = sm.get_stagings_by_month(year_month, company_id=company_id)
    db_confirmed = {s["id"]: s for s in db if s.get("status") == "confirmed"}

    fs_ids = set(fs.keys())
    db_ids = set(db_confirmed.keys())

    for sid in db_ids - fs_ids:
        s = db_confirmed[sid]
        diffs.append({
            "type": "DB-only",
            "company_id": company_id,
            "year_month": year_month,
            "staging_id": sid,
            "supplier": s.get("supplier_name", ""),
            "amount": s.get("total_amount", 0),
            "note": "DB confirmed 但 GDrive 找不到實體檔（含根目錄 fallback）",
        })

    misplaced = [(sid, info) for sid, info in fs.items()
                 if sid in db_ids and info.get("fallback") == "ROOT"]
    for sid, info in misplaced:
        diffs.append({
            "type": "MIS-PLACED",
            "company_id": company_id,
            "year_month": year_month,
            "staging_id": sid,
            "supplier": info["supplier"],
            "amount": info["amount"],
            "note": f"{info['filename']} 在根目錄/{year_month[:4]}/，應在公司資料夾內",
        })

    for sid in fs_ids - db_ids:
        info = fs[sid]
        diffs.append({
            "type": "FS-only",
            "company_id": company_id,
            "year_month": year_month,
            "staging_id": sid,
            "supplier": info["supplier"],
            "amount": info["amount"],
            "note": f"GDrive 有檔 {info['filename']} 但 DB 查無 staging#{sid}",
        })

    by_dir: dict[str, list[dict]] = defaultdict(list)
    for sid, info in fs.items():
        by_dir[info["dest_dir"]].append(info)

    for supplier_dir, files in by_dir.items():
        indexed = _index_csv_ids(supplier_dir)
        for info in files:
            if info["staging_id"] in indexed:
                continue
            diffs.append({
                "type": "INDEX-miss",
                "company_id": company_id,
                "year_month": year_month,
                "staging_id": info["staging_id"],
                "supplier": info["supplier"],
                "amount": info["amount"],
                "note": f"{info['filename']} 在 {os.path.basename(supplier_dir)}/ 但 INDEX.csv 漏",
            })
            if rebuild_index:
                row = {
                    "日期": info["date"],
                    "供應商": info["supplier"],
                    "發票號碼": "",
                    "品項數": 0,
                    "未稅金額": 0,
                    "稅額": 0,
                    "總金額": info["amount"],
                    "檔案名稱": info["filename"],
                    "歸檔時間": "(reconcile rebuild)",
                    "來源": f"staging#{info['staging_id']}",
                }
                try:
                    _append_index_csv(supplier_dir, row)
                except Exception as e:
                    print(f"  rebuild INDEX 失敗 {supplier_dir}: {e}")

    return diffs


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--company", type=int, default=None, help="只跑指定公司")
    p.add_argument("--month", type=str, default=None, help="YYYY-MM；不指定則掃全部年月")
    p.add_argument("--rebuild-index", action="store_true", help="自動補回漏的 INDEX.csv 列")
    p.add_argument("--csv", type=str, default=None, help="匯出差異到 CSV 檔")
    args = p.parse_args()

    sm.init_db()

    companies = [args.company] if args.company else [1, 2, 3, 4, 5]
    all_diffs: list[dict] = []

    for cid in companies:
        yms = [args.month] if args.month else _all_year_months_for_company(cid)
        for ym in yms:
            diffs = reconcile(cid, ym, args.rebuild_index)
            all_diffs.extend(diffs)

    type_count = defaultdict(int)
    for d in all_diffs:
        type_count[d["type"]] += 1

    print(f"\n{'='*72}")
    print(f"GDrive ↔ DB Reconcile 結果（共 {len(all_diffs)} 筆差異）")
    print(f"{'='*72}")
    for t in ("DB-only", "FS-only", "INDEX-miss", "MIS-PLACED"):
        print(f"  [{t}]  {type_count[t]} 筆")
    print(f"{'='*72}\n")

    for d in all_diffs[:50]:
        print(f"  [{d['type']:<10}] co{d['company_id']} {d['year_month']} "
              f"#{d['staging_id']:<5} {d['supplier'][:14]:<14} ${d['amount']:>7,}  {d['note']}")
    if len(all_diffs) > 50:
        print(f"  … 還有 {len(all_diffs) - 50} 筆，加 --csv 匯出查看")

    if args.csv:
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["type", "company_id", "year_month",
                                               "staging_id", "supplier", "amount", "note"])
            w.writeheader()
            w.writerows(all_diffs)
        print(f"\n已匯出：{args.csv}")


if __name__ == "__main__":
    main()
