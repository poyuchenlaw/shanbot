#!/usr/bin/env python3
"""批次 OCR 辨識 unknown 收據圖片 → 重新命名為 YYMMDD_供應商_金額.jpg

使用 Gemini Flash 快速辨識收據內容，提取供應商名稱、日期、金額。
辨識後重新命名並歸入供應商子資料夾。

用法：
    python3 batch_rename_receipts.py [--dry-run] [--limit N]
"""

import argparse
import base64
import json
import logging
import os
import re
import shutil
import sys
import time

# 載入 shanbot 環境
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", ".env"))

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("batch_rename")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"

RECEIPT_DIR = "/mnt/h/我的雲端硬碟/小魚資料/團膳公司資料/2026/03月/收據憑證"
# 可被 --dir 參數覆寫

# 快速辨識 prompt（只要供應商、日期、金額）
QUICK_OCR_PROMPT = (
    "這是一張收據或發票照片。請只回傳 JSON，包含以下欄位：\n"
    '{"supplier": "供應商名稱", "date": "YYYY-MM-DD", "total": 金額數字, "invoice_number": "發票號碼或空字串"}\n'
    "日期是民國年的話請轉為西元年（+1911）。\n"
    "如果看不清楚供應商名稱，填最接近的猜測。\n"
    "如果完全無法辨識，supplier 填 \"unreadable\"。"
)


def ocr_quick(image_path: str) -> dict | None:
    """用 Gemini Flash 快速辨識收據基本資訊"""
    if not GEMINI_API_KEY:
        logger.error("No GEMINI_API_KEY")
        return None

    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
        payload = {
            "contents": [{"parts": [
                {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                {"text": QUICK_OCR_PROMPT},
            ]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1,
                "maxOutputTokens": 512,
            },
        }

        resp = requests.post(url, params={"key": GEMINI_API_KEY}, json=payload, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            # 嘗試直接解析
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                # 嘗試修復截斷的 JSON
                text = text.strip()
                if not text.endswith("}"):
                    text += '"}'
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    # 用 regex 提取
                    m_sup = re.search(r'"supplier"\s*:\s*"([^"]*)"', text)
                    m_date = re.search(r'"date"\s*:\s*"([^"]*)"', text)
                    m_total = re.search(r'"total"\s*:\s*(\d+)', text)
                    if m_sup:
                        return {
                            "supplier": m_sup.group(1),
                            "date": m_date.group(1) if m_date else "",
                            "total": int(m_total.group(1)) if m_total else 0,
                            "invoice_number": "",
                        }
                    logger.warning(f"Cannot parse Gemini response: {text[:200]}")
                    return None
        elif resp.status_code == 429:
            logger.warning("Rate limited, waiting 10s...")
            time.sleep(10)
            return ocr_quick(image_path)  # retry once
        else:
            logger.error(f"Gemini API error: {resp.status_code}")
            return None
    except Exception as e:
        logger.error(f"OCR error for {os.path.basename(image_path)}: {e}")
        return None


def date_to_yy(date_str: str) -> str:
    """YYYY-MM-DD → YYMMDD (民國年風格的6碼)"""
    if not date_str or len(date_str) < 10:
        return ""
    try:
        parts = date_str.split("-")
        year = int(parts[0]) - 1911  # 西元 → 民國
        return f"{year:03d}{parts[1]}{parts[2]}"
    except Exception:
        return ""


def sanitize_name(name: str) -> str:
    """清理供應商名稱作為檔名"""
    # 移除不適合檔名的字元
    name = re.sub(r'[/\\:*?"<>|]', '', name)
    name = name.strip()
    return name


def find_supplier_folder(supplier: str, existing_folders: list[str]) -> str | None:
    """模糊匹配供應商名稱到現有資料夾"""
    if not supplier:
        return None
    for folder in existing_folders:
        # 完全包含或被包含
        if supplier in folder or folder in supplier:
            return folder
        # 去掉後綴比對
        clean_supplier = re.sub(r'(有限公司|股份有限公司|企業|商行|工廠|行$)', '', supplier)
        clean_folder = re.sub(r'(有限公司|股份有限公司|企業|商行|工廠|行$)', '', folder)
        if clean_supplier and clean_folder and (clean_supplier in clean_folder or clean_folder in clean_supplier):
            return folder
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只顯示不實際執行")
    parser.add_argument("--limit", type=int, default=0, help="最多處理幾張")
    parser.add_argument("--dir", type=str, default="", help="覆寫掃描資料夾路徑（不指定則用內建 RECEIPT_DIR）")
    args = parser.parse_args()

    global RECEIPT_DIR
    if args.dir:
        RECEIPT_DIR = args.dir
    logger.info(f"掃描資料夾：{RECEIPT_DIR}")
    if not os.path.isdir(RECEIPT_DIR):
        logger.error(f"資料夾不存在：{RECEIPT_DIR}")
        sys.exit(1)

    # 列出 unknown 檔案
    all_files = os.listdir(RECEIPT_DIR)
    unknown_files = sorted([
        f for f in all_files
        if f.startswith("unknown_") and f.endswith(".jpg") and os.path.getsize(os.path.join(RECEIPT_DIR, f)) > 100
    ])

    if args.limit:
        unknown_files = unknown_files[:args.limit]

    logger.info(f"找到 {len(unknown_files)} 張 unknown 收據待處理")

    # 現有子資料夾
    existing_folders = [
        f for f in all_files
        if os.path.isdir(os.path.join(RECEIPT_DIR, f))
    ]
    logger.info(f"現有供應商資料夾: {existing_folders}")

    results = {"renamed": 0, "moved": 0, "failed": 0, "unreadable": 0}

    for i, filename in enumerate(unknown_files):
        filepath = os.path.join(RECEIPT_DIR, filename)
        logger.info(f"[{i+1}/{len(unknown_files)}] 辨識 {filename}...")

        ocr = ocr_quick(filepath)
        if not ocr:
            results["failed"] += 1
            continue

        supplier = sanitize_name(ocr.get("supplier", ""))
        date_str = ocr.get("date", "")
        total = int(ocr.get("total", 0) or 0)
        invoice = ocr.get("invoice_number", "")

        if not supplier or supplier == "unreadable":
            results["unreadable"] += 1
            logger.warning(f"  → 無法辨識供應商: {filename}")
            continue

        # 生成新檔名
        yy = date_to_yy(date_str)
        if not yy:
            # 從原始檔名中提取日期
            m = re.search(r'unknown_(\d{8})', filename)
            if m:
                orig_date = m.group(1)
                year = int(orig_date[:4]) - 1911
                yy = f"{year:03d}{orig_date[4:6]}{orig_date[6:8]}"

        new_name = f"{yy}_{supplier}_{total}.jpg" if yy else f"000000_{supplier}_{total}.jpg"

        # 確保不重複
        target_dir = RECEIPT_DIR
        folder_match = find_supplier_folder(supplier, existing_folders)

        if folder_match:
            target_dir = os.path.join(RECEIPT_DIR, folder_match)
        else:
            # 建立新供應商資料夾
            new_folder = os.path.join(RECEIPT_DIR, supplier)
            if not args.dry_run:
                os.makedirs(new_folder, exist_ok=True)
            target_dir = new_folder
            existing_folders.append(supplier)
            logger.info(f"  → 新建資料夾: {supplier}/")

        target_path = os.path.join(target_dir, new_name)

        # 避免覆蓋
        counter = 1
        while os.path.exists(target_path):
            base, ext = os.path.splitext(new_name)
            target_path = os.path.join(target_dir, f"{base}_{counter}{ext}")
            counter += 1

        logger.info(f"  → {filename} → {os.path.relpath(target_path, RECEIPT_DIR)}")

        if not args.dry_run:
            shutil.move(filepath, target_path)
            results["renamed"] += 1
            if target_dir != RECEIPT_DIR:
                results["moved"] += 1

        # Rate limiting: 每 5 張暫停 1 秒
        if (i + 1) % 5 == 0:
            time.sleep(1)

    logger.info(f"\n=== 完成 ===")
    logger.info(f"重新命名: {results['renamed']}")
    logger.info(f"歸入資料夾: {results['moved']}")
    logger.info(f"無法辨識: {results['unreadable']}")
    logger.info(f"API 失敗: {results['failed']}")


if __name__ == "__main__":
    main()
