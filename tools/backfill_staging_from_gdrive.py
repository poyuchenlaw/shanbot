#!/usr/bin/env python3
"""補檔工具 — 從 GDrive 已歸檔的收據檔名反向補一筆 purchase_staging

使用情境：當 batch_rename_receipts.py 已經把零散的 unknown_*.jpg 重命名
歸入供應商子資料夾，但這些圖片的 staging 記錄沒進 DB（例如靜默故障期間
LINE webhook 沒進 photo_handler），就用這個工具補。

檔名格式：YYMMDD_供應商_金額.jpg 或 YYMMDD_供應商_金額_N.jpg（重複編號）
  - YYMMDD 是民國年（例 1150329 = 2026-03-29）
  - 供應商從父資料夾名稱取（更可靠）
  - 金額從檔名末尾解析

用法：
  python3 backfill_staging_from_gdrive.py --dir <資料夾路徑> --company-id 3 [--dry-run]
"""

import argparse
import hashlib
import logging
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", ".env"))

import state_manager as sm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("backfill_staging")

# 從檔名解析金額：1150329_供應商_4886.jpg 或 1150329_供應商_4886_2.jpg
FILENAME_RE = re.compile(r"^(\d{6,7})_(.+?)_(\d+)(?:_\w+)?\.(?:jpg|jpeg|png)$", re.IGNORECASE)


def parse_filename(filename: str) -> dict | None:
    """從檔名解析 民國日期+金額"""
    m = FILENAME_RE.match(filename)
    if not m:
        return None
    yymmdd = m.group(1)
    total = int(m.group(3))
    # 民國年 → 西元年（YYMMDD 6 碼或 YYYMMDD 7 碼）
    if len(yymmdd) == 7:
        roc_year = int(yymmdd[:3])
        mm = yymmdd[3:5]
        dd = yymmdd[5:7]
    else:
        roc_year = int(yymmdd[:2])
        mm = yymmdd[2:4]
        dd = yymmdd[4:6]
    if roc_year < 100:  # 不合理
        return None
    western_year = roc_year + 1911
    try:
        purchase_date = datetime(western_year, int(mm), int(dd)).date().isoformat()
    except ValueError:
        return None
    return {
        "purchase_date": purchase_date,
        "total_amount": total,
    }


def file_sha256(path: str) -> str:
    """算圖片內容 hash 用於去重"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="待掃描資料夾（裡面有供應商子資料夾）")
    parser.add_argument("--company-id", type=int, required=True, help="公司 ID（1=福利社 2=王凱 3=台達2廠 4=富燚 5=台達1廠）")
    parser.add_argument("--user-id", default="cymon-backfill", help="模擬的 user_id")
    parser.add_argument("--chat-id", default="cymon-backfill", help="模擬的 chat_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        logger.error(f"資料夾不存在：{args.dir}")
        sys.exit(1)

    # 列出所有供應商子資料夾下的圖片
    targets = []
    for sub in sorted(os.listdir(args.dir)):
        sub_path = os.path.join(args.dir, sub)
        if not os.path.isdir(sub_path):
            continue
        if sub.startswith("."):
            continue
        for f in sorted(os.listdir(sub_path)):
            if not f.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            targets.append((sub, f, os.path.join(sub_path, f)))

    logger.info(f"找到 {len(targets)} 張已歸檔圖片")

    sm.init_db()
    stats = {"created": 0, "skipped_dup": 0, "skipped_parse": 0, "errors": 0}

    for supplier_folder, filename, full_path in targets:
        parsed = parse_filename(filename)
        if not parsed:
            logger.warning(f"  ✗ 無法解析檔名：{supplier_folder}/{filename}")
            stats["skipped_parse"] += 1
            continue

        # 算 hash 去重（避免重跑時重複建）
        try:
            img_hash = file_sha256(full_path)
        except Exception as e:
            logger.error(f"  ✗ hash 失敗 {filename}: {e}")
            stats["errors"] += 1
            continue

        existing = sm.find_by_hash(img_hash)
        if existing:
            logger.info(f"  ⊙ 已存在 staging #{existing['id']} ({supplier_folder}/{filename})")
            stats["skipped_dup"] += 1
            continue

        if args.dry_run:
            logger.info(f"  + DRY {supplier_folder}/{filename} → {parsed['purchase_date']} ${parsed['total_amount']}")
            stats["created"] += 1
            continue

        # 建立 staging 基本記錄
        try:
            staging_id = sm.add_purchase_staging(
                user_id=args.user_id,
                chat_id=args.chat_id,
                image_message_id=f"backfill-{img_hash[:12]}",
                local_image_path=full_path,
                purchase_date=parsed["purchase_date"],
                company_id=args.company_id,
            )
            # 補欄位：供應商、金額、gdrive_path、處理者標記
            sm.update_purchase_staging(
                staging_id,
                supplier_name=supplier_folder,
                total_amount=parsed["total_amount"],
                subtotal=parsed["total_amount"],  # 保守：先全額當未稅，confirm 時可改
                tax_amount=0,
                gdrive_path=full_path,
                handler_name="cymon-backfill",
                handler_note=f"由 backfill_staging_from_gdrive.py 補檔（{datetime.now().isoformat()}）",
                ocr_confidence=0,  # 標記低信心度，提示人工檢查
            )
            sm.update_staging_hash(staging_id, img_hash)
            stats["created"] += 1
            if stats["created"] % 20 == 0:
                logger.info(f"  ... 已建 {stats['created']} 筆")
        except Exception as e:
            logger.error(f"  ✗ DB 寫入失敗 {filename}: {e}")
            stats["errors"] += 1

    logger.info(f"\n=== 完成 ===")
    logger.info(f"  新建 staging: {stats['created']}")
    logger.info(f"  跳過（已有 hash）: {stats['skipped_dup']}")
    logger.info(f"  跳過（檔名無法解析）: {stats['skipped_parse']}")
    logger.info(f"  錯誤: {stats['errors']}")


if __name__ == "__main__":
    main()
