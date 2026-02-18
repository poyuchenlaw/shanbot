"""Google Drive 本地同步檔案操作（v2.1 — 結構化資料夾管理）"""

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("shanbot.gdrive")

GDRIVE_LOCAL = os.environ.get(
    "GDRIVE_LOCAL", "/mnt/h/我的雲端硬碟/小魚資料/團膳公司資料"
)

# 每月子資料夾名稱
MONTHLY_FOLDERS = [
    "收據憑證", "採購單據", "月報表", "稅務匯出", "菜單企劃",
    "薪資表", "租約與合約", "會計資料", "財務報表",
]

# 年度子資料夾
ANNUAL_FOLDERS = ["年度報表", "食材價格對照"]


# === 基礎操作（保留原有 API） ===

async def ensure_dir(path: str) -> bool:
    """確保目錄存在"""
    full = os.path.join(GDRIVE_LOCAL, path)
    try:
        os.makedirs(full, exist_ok=True)
        return True
    except Exception as e:
        logger.error(f"mkdir failed: {full} — {e}")
        return False


async def upload_file(local_path: str, remote_path: str) -> bool:
    """複製檔案到 GDrive 本地資料夾"""
    full = os.path.join(GDRIVE_LOCAL, remote_path)
    try:
        os.makedirs(os.path.dirname(full), exist_ok=True)
        shutil.copy2(local_path, full)
        logger.info(f"Uploaded: {local_path} → {full}")
        return True
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        return False


async def list_dir(path: str = "") -> list[dict]:
    """列出目錄內容"""
    full = os.path.join(GDRIVE_LOCAL, path)
    result = []
    try:
        for entry in sorted(os.listdir(full)):
            fp = os.path.join(full, entry)
            result.append({
                "name": entry,
                "is_dir": os.path.isdir(fp),
                "size": os.path.getsize(fp) if os.path.isfile(fp) else 0,
            })
    except Exception as e:
        logger.error(f"list_dir failed: {full} — {e}")
    return result


async def file_exists(path: str) -> bool:
    """檢查檔案是否存在"""
    full = os.path.join(GDRIVE_LOCAL, path)
    return os.path.exists(full)


def get_full_path(relative_path: str) -> str:
    """取得完整路徑"""
    return os.path.join(GDRIVE_LOCAL, relative_path)


# === v2.1 結構化資料夾管理 ===

def _year_month_path(year_month: str) -> tuple[str, str]:
    """解析 year_month (如 '2026-02') → (年路徑, 月路徑)"""
    parts = year_month.split("-")
    year = parts[0]
    month = f"{int(parts[1]):02d}月"
    year_path = os.path.join(GDRIVE_LOCAL, year)
    month_path = os.path.join(year_path, month)
    return year_path, month_path


def init_folder_structure(year_month: str | None = None) -> str:
    """建立年/月/類別資料夾結構，回傳月路徑"""
    if not year_month:
        year_month = datetime.now().strftime("%Y-%m")

    year_path, month_path = _year_month_path(year_month)

    # 月份子資料夾
    for folder in MONTHLY_FOLDERS:
        os.makedirs(os.path.join(month_path, folder), exist_ok=True)

    # 年度子資料夾
    for folder in ANNUAL_FOLDERS:
        os.makedirs(os.path.join(year_path, folder), exist_ok=True)

    logger.info(f"Folder structure initialized: {month_path}")
    return month_path


async def upload_receipt(
    local_path: str,
    year_month: str | None = None,
    supplier: str = "unknown",
) -> str | None:
    """上傳收據到 收據憑證/ 資料夾，回傳 GDrive 相對路徑"""
    if not year_month:
        year_month = datetime.now().strftime("%Y-%m")

    _, month_path = _year_month_path(year_month)
    dest_dir = os.path.join(month_path, "收據憑證")
    os.makedirs(dest_dir, exist_ok=True)

    # 檔名：原始檔名加上供應商前綴
    basename = os.path.basename(local_path)
    safe_supplier = supplier.replace("/", "_").replace("\\", "_")[:20]
    dest_name = f"{safe_supplier}_{basename}"
    dest_path = os.path.join(dest_dir, dest_name)

    try:
        shutil.copy2(local_path, dest_path)
        # 計算相對路徑
        rel = os.path.relpath(dest_path, GDRIVE_LOCAL)
        logger.info(f"Receipt uploaded: {local_path} → {dest_path}")
        return rel
    except Exception as e:
        logger.error(f"upload_receipt failed: {e}")
        return None


async def upload_export(
    local_path: str,
    export_type: str,
    period: str,
) -> str | None:
    """上傳匯出檔案到對應類別資料夾，回傳 GDrive 相對路徑

    export_type: monthly / annual / mof_txt / accounting / handler_cert / menu
    period: 如 '2026-02' 或 '2026'
    """
    # 判斷目標資料夾
    type_folder_map = {
        "monthly": "月報表",
        "mof_txt": "稅務匯出",
        "accounting": "稅務匯出",
        "handler_cert": "稅務匯出",
        "menu": "菜單企劃",
    }

    if export_type == "annual":
        # 年度報表放年度資料夾下
        year = period[:4]
        dest_dir = os.path.join(GDRIVE_LOCAL, year, "年度報表")
    elif export_type == "price_compare":
        year = period[:4]
        dest_dir = os.path.join(GDRIVE_LOCAL, year, "食材價格對照")
    else:
        # 月份類別
        folder_name = type_folder_map.get(export_type, "月報表")
        year_month = period[:7] if len(period) >= 7 else period
        _, month_path = _year_month_path(year_month)
        dest_dir = os.path.join(month_path, folder_name)

    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, os.path.basename(local_path))

    try:
        shutil.copy2(local_path, dest_path)
        rel = os.path.relpath(dest_path, GDRIVE_LOCAL)
        logger.info(f"Export uploaded: {local_path} → {dest_path}")
        return rel
    except Exception as e:
        logger.error(f"upload_export failed: {e}")
        return None


def get_folder_index(year_month: str | None = None) -> dict:
    """掃描取得月份檔案索引"""
    if not year_month:
        year_month = datetime.now().strftime("%Y-%m")

    _, month_path = _year_month_path(year_month)
    index = {"year_month": year_month, "folders": {}, "total_files": 0}

    if not os.path.isdir(month_path):
        return index

    for folder in MONTHLY_FOLDERS:
        folder_path = os.path.join(month_path, folder)
        files = []
        if os.path.isdir(folder_path):
            for entry in sorted(os.listdir(folder_path)):
                fp = os.path.join(folder_path, entry)
                if os.path.isfile(fp):
                    files.append({
                        "name": entry,
                        "size": os.path.getsize(fp),
                        "mtime": datetime.fromtimestamp(
                            os.path.getmtime(fp)
                        ).isoformat(),
                    })
        index["folders"][folder] = files
        index["total_files"] += len(files)

    return index


# doc_category → GDrive 子資料夾映射
_CATEGORY_FOLDER_MAP = {
    "payroll": "薪資表",
    "general": "租約與合約",
    "revenue": "會計資料",
    "financing": "會計資料",
    "investment": "會計資料",
    "fixed_asset": "會計資料",
    "expenditure": "採購單據",
    "production": "會計資料",
}


async def upload_financial_doc(
    local_path: str,
    year_month: str,
    category: str,
    filename: str | None = None,
) -> str | None:
    """上傳財務文件到對應分類的月度子資料夾，回傳 GDrive 相對路徑"""
    _, month_path = _year_month_path(year_month)
    folder_name = _CATEGORY_FOLDER_MAP.get(category, "會計資料")
    dest_dir = os.path.join(month_path, folder_name)
    os.makedirs(dest_dir, exist_ok=True)

    dest_name = filename or os.path.basename(local_path)
    dest_path = os.path.join(dest_dir, dest_name)

    try:
        shutil.copy2(local_path, dest_path)
        rel = os.path.relpath(dest_path, GDRIVE_LOCAL)
        logger.info(f"Financial doc uploaded: {local_path} → {dest_path}")
        return rel
    except Exception as e:
        logger.error(f"upload_financial_doc failed: {e}")
        return None


def get_financial_doc_index(year_month: str | None = None) -> dict:
    """掃描所有財務文件子資料夾的索引"""
    if not year_month:
        year_month = datetime.now().strftime("%Y-%m")

    _, month_path = _year_month_path(year_month)
    finance_folders = ["薪資表", "租約與合約", "會計資料", "財務報表"]
    index = {"year_month": year_month, "folders": {}, "total_files": 0}

    for folder in finance_folders:
        folder_path = os.path.join(month_path, folder)
        files = []
        if os.path.isdir(folder_path):
            for entry in sorted(os.listdir(folder_path)):
                fp = os.path.join(folder_path, entry)
                if os.path.isfile(fp):
                    files.append({
                        "name": entry,
                        "size": os.path.getsize(fp),
                        "mtime": datetime.fromtimestamp(
                            os.path.getmtime(fp)
                        ).isoformat(),
                    })
        index["folders"][folder] = files
        index["total_files"] += len(files)

    return index


def get_annual_index(year: str | None = None) -> dict:
    """年度索引 — 所有月份 + 年度資料夾"""
    if not year:
        year = str(datetime.now().year)

    year_path = os.path.join(GDRIVE_LOCAL, year)
    index = {"year": year, "months": {}, "annual_folders": {}, "total_files": 0}

    if not os.path.isdir(year_path):
        return index

    for entry in sorted(os.listdir(year_path)):
        entry_path = os.path.join(year_path, entry)
        if not os.path.isdir(entry_path):
            continue

        if entry.endswith("月"):
            # 月份資料夾
            file_count = 0
            for root, dirs, files in os.walk(entry_path):
                file_count += len(files)
            index["months"][entry] = file_count
            index["total_files"] += file_count
        elif entry in ANNUAL_FOLDERS:
            # 年度資料夾
            files = []
            for f in sorted(os.listdir(entry_path)):
                fp = os.path.join(entry_path, f)
                if os.path.isfile(fp):
                    files.append(f)
            index["annual_folders"][entry] = files
            index["total_files"] += len(files)

    return index
