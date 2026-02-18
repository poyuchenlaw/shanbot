"""GDrive 索引服務 — 掃描、搜尋、統計"""

import json
import logging
import os
from datetime import datetime

from services.gdrive_service import (
    GDRIVE_LOCAL,
    get_folder_index,
    get_annual_index,
)

logger = logging.getLogger("shanbot.gdrive_index")

INDEX_FILE = os.path.join(GDRIVE_LOCAL, "索引.json")


def update_index(year_month: str | None = None) -> dict:
    """掃描資料夾更新索引.json，回傳索引內容"""
    if not year_month:
        year_month = datetime.now().strftime("%Y-%m")

    year = year_month[:4]

    # 讀取現有索引
    index = _load_index()

    # 更新月份索引
    month_idx = get_folder_index(year_month)
    if "months" not in index:
        index["months"] = {}
    index["months"][year_month] = {
        "total_files": month_idx["total_files"],
        "folders": {
            k: len(v) for k, v in month_idx["folders"].items()
        },
        "updated_at": datetime.now().isoformat(),
    }

    # 更新年度索引
    annual_idx = get_annual_index(year)
    if "years" not in index:
        index["years"] = {}
    index["years"][year] = {
        "total_files": annual_idx["total_files"],
        "months": annual_idx["months"],
        "annual_folders": {
            k: len(v) for k, v in annual_idx["annual_folders"].items()
        },
        "updated_at": datetime.now().isoformat(),
    }

    index["last_updated"] = datetime.now().isoformat()

    # 寫入
    _save_index(index)
    logger.info(f"Index updated: {year_month} ({month_idx['total_files']} files)")
    return index


def search_index(keyword: str) -> list[dict]:
    """搜尋檔案名（遍歷 GDrive 資料夾）"""
    results = []
    keyword_lower = keyword.lower()

    for root, dirs, files in os.walk(GDRIVE_LOCAL):
        for f in files:
            if keyword_lower in f.lower():
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, GDRIVE_LOCAL)
                results.append({
                    "name": f,
                    "path": rel,
                    "size": os.path.getsize(fp),
                    "mtime": datetime.fromtimestamp(
                        os.path.getmtime(fp)
                    ).isoformat(),
                })

    results.sort(key=lambda x: x["mtime"], reverse=True)
    return results


def get_summary(year_month: str | None = None) -> dict:
    """檔案統計摘要"""
    if not year_month:
        year_month = datetime.now().strftime("%Y-%m")

    folder_idx = get_folder_index(year_month)
    total_size = 0
    folder_stats = {}

    for folder_name, files in folder_idx["folders"].items():
        count = len(files)
        size = sum(f["size"] for f in files)
        total_size += size
        folder_stats[folder_name] = {"count": count, "size": size}

    return {
        "year_month": year_month,
        "total_files": folder_idx["total_files"],
        "total_size": total_size,
        "total_size_mb": round(total_size / 1024 / 1024, 2),
        "folders": folder_stats,
    }


def _load_index() -> dict:
    """讀取索引檔"""
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_index(data: dict):
    """寫入索引檔"""
    os.makedirs(os.path.dirname(INDEX_FILE), exist_ok=True)
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
