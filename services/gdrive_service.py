"""Google Drive 本地同步檔案操作（v2.2 — 結構化資料夾管理 + 掛載 fallback）"""

import json
import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("shanbot.gdrive")

_GDRIVE_PRIMARY = os.environ.get(
    "GDRIVE_LOCAL", "/mnt/h/我的雲端硬碟/小魚資料/團膳公司資料"
)
_GDRIVE_STAGING = "/home/simon/shanbot/data/gdrive_staging"

# --- 掛載可用性檢查 ---
_USING_STAGING = False


def _check_gdrive_available() -> bool:
    """檢查 GDrive 路徑是否可寫（H: 磁碟已掛載且 Google Drive 同步中）"""
    try:
        # 先檢查 /mnt/h 是否有內容（空目錄 = 未掛載）
        mnt_h = "/mnt/h"
        if os.path.isdir(mnt_h) and not os.listdir(mnt_h):
            return False
        # 嘗試在目標路徑建立測試目錄
        os.makedirs(_GDRIVE_PRIMARY, exist_ok=True)
        test_file = os.path.join(_GDRIVE_PRIMARY, ".shanbot_write_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return True
    except (OSError, PermissionError):
        return False


def _resolve_gdrive_path() -> str:
    """決定使用真正 GDrive 路徑或暫存路徑"""
    global _USING_STAGING
    if _check_gdrive_available():
        _USING_STAGING = False
        logger.info(f"[GDrive] 使用真實路徑: {_GDRIVE_PRIMARY}")
        return _GDRIVE_PRIMARY
    else:
        _USING_STAGING = True
        os.makedirs(_GDRIVE_STAGING, exist_ok=True)
        logger.warning(
            f"[GDrive] H: 磁碟未掛載或不可寫，使用暫存路徑: {_GDRIVE_STAGING}"
            " — 請確認 Windows 端 Google Drive 已啟動並掛載 H:"
        )
        return _GDRIVE_STAGING


GDRIVE_LOCAL = _resolve_gdrive_path()


def is_using_staging() -> bool:
    """供外部查詢是否正在使用暫存路徑"""
    return _USING_STAGING

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
    """建立年/月/類別資料夾結構，回傳月路徑

    啟動時會重新檢查 GDrive 掛載狀態，若掛載恢復則自動切回真實路徑。
    """
    global GDRIVE_LOCAL, _USING_STAGING

    # 每次呼叫重新檢查掛載狀態（可能 Windows 端後來才啟動 Google Drive）
    new_path = _resolve_gdrive_path()
    if new_path != GDRIVE_LOCAL:
        logger.info(f"[GDrive] 路徑切換: {GDRIVE_LOCAL} → {new_path}")
        GDRIVE_LOCAL = new_path

    if _USING_STAGING:
        logger.warning(
            "[GDrive] init_folder_structure: 使用暫存路徑，"
            "檔案不會同步到 Google Drive，待 H: 掛載後需手動搬移"
        )

    if not year_month:
        year_month = datetime.now().strftime("%Y-%m")

    year_path, month_path = _year_month_path(year_month)

    # 月份子資料夾
    for folder in MONTHLY_FOLDERS:
        os.makedirs(os.path.join(month_path, folder), exist_ok=True)

    # 年度子資料夾
    for folder in ANNUAL_FOLDERS:
        os.makedirs(os.path.join(year_path, folder), exist_ok=True)

    # 放置命名規則說明檔（讓使用者在資料夾裡就能看到命名邏輯）
    readme_path = os.path.join(month_path, "命名規則說明.txt")
    if not os.path.exists(readme_path):
        try:
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(
                    "【小膳系統 — 檔案命名規則說明】\n"
                    "================================\n\n"
                    "📁 資料夾結構：\n"
                    "  {年}/{月}月/\n"
                    "    ├── 收據憑證/{供應商名稱}/    ← 按供應商分類\n"
                    "    ├── 採購單據/\n"
                    "    ├── 月報表/\n"
                    "    ├── 稅務匯出/\n"
                    "    ├── 菜單企劃/\n"
                    "    ├── 薪資表/\n"
                    "    ├── 租約與合約/\n"
                    "    ├── 會計資料/\n"
                    "    ├── 財務報表/\n"
                    "    └── INDEX_總覽.csv          ← 全月檔案索引\n\n"
                    "📄 收據/憑證檔名格式：\n"
                    "  YYMMDD_供應商名稱_金額_#流水號.jpg\n"
                    "  例：260309_好鮮水產行_3500_#42.jpg\n\n"
                    "📊 薪資表檔名格式：\n"
                    "  薪資表_YYYY-MM.xlsx\n\n"
                    "📋 菜單檔名格式：\n"
                    "  菜單_YYYY-MM.xlsx\n\n"
                    "📑 報表檔名格式：\n"
                    "  {報表類型}_{YYYY-MM}.xlsx\n\n"
                    "🔍 INDEX_總覽.csv 包含本月所有歸檔檔案的索引\n"
                    "🔍 年度索引在 {年}/INDEX_年度總覽.csv\n\n"
                    "💡 如需修改歸檔位置，直接在資料夾中移動檔案即可\n"
                    "   系統不會自動移回，但 INDEX 不會自動更新\n"
                    "   可在 LINE 輸入「索引」重新產生索引\n"
                )
        except Exception as e:
            logger.warning(f"Failed to create naming readme: {e}")

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
    safe_supplier = re.sub(r'[\\/:*?"<>|\s]', '_', supplier or "unknown")[:20]
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


async def archive_receipt(
    local_path: str,
    purchase_date: str,
    supplier_name: str,
    total_amount: float,
    staging_id: int,
    ocr_summary: dict | None = None,
) -> dict:
    """確認後的正式歸檔：重命名 + 存 GDrive + 寫 INDEX.csv

    Args:
        local_path: 本地圖片路徑
        purchase_date: 'YYYY-MM-DD'
        supplier_name: 供應商名稱
        total_amount: 總金額
        staging_id: 暫存記錄 ID
        ocr_summary: OCR 摘要（可選），含 items / invoice_number / subtotal / tax_amount

    Returns:
        {"gdrive_path": "...", "filename": "...", "index_row": {...}}
    """
    if not ocr_summary:
        ocr_summary = {}

    # 1. 重命名：YYMMDD_供應商名_金額_#staging_id.ext
    try:
        date_parts = purchase_date.split("-")
        yy = date_parts[0][2:]  # 2026 -> 26
        mm = date_parts[1]
        dd = date_parts[2]
        date_prefix = f"{yy}{mm}{dd}"
    except (IndexError, AttributeError):
        date_prefix = datetime.now().strftime("%y%m%d")

    safe_supplier = re.sub(r'[\\/:*?"<>|\s]', '_', supplier_name or "unknown")[:20]
    amount_str = f"{int(total_amount)}" if total_amount else "0"
    ext = os.path.splitext(local_path)[1] or ".jpg"
    new_filename = f"{date_prefix}_{safe_supplier}_{amount_str}_#{staging_id}{ext}"

    # 2. 計算目標路徑：{年}/{月}月/收據憑證/{供應商}/
    year_month = purchase_date[:7] if purchase_date and len(purchase_date) >= 7 else datetime.now().strftime("%Y-%m")
    _, month_path = _year_month_path(year_month)
    dest_dir = os.path.join(month_path, "收據憑證", safe_supplier)
    os.makedirs(dest_dir, exist_ok=True)

    dest_path = os.path.join(dest_dir, new_filename)

    # 3. 複製檔案
    try:
        shutil.copy2(local_path, dest_path)
        rel_path = os.path.relpath(dest_path, GDRIVE_LOCAL)
        logger.info(f"Receipt archived: {local_path} -> {dest_path}")
    except Exception as e:
        logger.error(f"archive_receipt copy failed: {e}")
        return {"gdrive_path": None, "filename": new_filename, "index_row": {}, "error": str(e)}

    # 4. 更新 INDEX.csv
    index_row = {
        "日期": purchase_date,
        "供應商": supplier_name or "",
        "發票號碼": ocr_summary.get("invoice_number", ""),
        "品項數": len(ocr_summary.get("items", [])),
        "未稅金額": ocr_summary.get("subtotal", 0),
        "稅額": ocr_summary.get("tax_amount", 0),
        "總金額": total_amount,
        "檔案名稱": new_filename,
        "歸檔時間": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "來源": f"staging#{staging_id}",
    }

    try:
        _append_index_csv(dest_dir, index_row)
    except Exception as e:
        logger.warning(f"INDEX.csv update failed: {e}")

    # 5. 更新月度總覽索引
    try:
        update_master_index(year_month)
    except Exception as e:
        logger.warning(f"Master index update failed: {e}")

    return {
        "gdrive_path": rel_path,
        "filename": new_filename,
        "index_row": index_row,
    }


def _append_index_csv(folder_path: str, row: dict):
    """追加一行到 INDEX.csv（不存在則建立含標題行）"""
    import csv

    csv_path = os.path.join(folder_path, "INDEX.csv")
    headers = ["日期", "供應商", "發票號碼", "品項數", "未稅金額",
               "稅額", "總金額", "檔案名稱", "歸檔時間", "來源"]

    file_exists = os.path.exists(csv_path)

    with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    logger.info(f"INDEX.csv updated: {csv_path} (+1 row)")


def update_master_index(year_month: str | None = None) -> str:
    """掃描月份所有子資料夾，生成 INDEX_總覽.csv

    Args:
        year_month: 如 '2026-03'，預設為本月

    Returns:
        INDEX_總覽.csv 的完整路徑
    """
    import csv

    if not year_month:
        year_month = datetime.now().strftime("%Y-%m")

    _, month_path = _year_month_path(year_month)

    if not os.path.isdir(month_path):
        logger.warning(f"update_master_index: {month_path} not found")
        return ""

    csv_path = os.path.join(month_path, "INDEX_總覽.csv")
    headers = ["類別", "子分類", "檔案名稱", "日期", "大小", "建立時間"]
    rows = []

    for folder in MONTHLY_FOLDERS:
        folder_path = os.path.join(month_path, folder)
        if not os.path.isdir(folder_path):
            continue

        # 掃描子資料夾（供應商等）和直接的檔案
        for root, dirs, files in os.walk(folder_path):
            for fname in sorted(files):
                if fname == "INDEX.csv" or fname == "INDEX_總覽.csv":
                    continue
                fp = os.path.join(root, fname)
                rel_to_category = os.path.relpath(root, folder_path)
                subcategory = rel_to_category if rel_to_category != "." else ""

                try:
                    stat = os.stat(fp)
                    size_kb = f"{stat.st_size / 1024:.1f}KB"
                    ctime = datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M")
                    # 嘗試從檔名解析日期
                    date_match = re.match(r"(\d{6})_", fname)
                    file_date = ""
                    if date_match:
                        d = date_match.group(1)
                        file_date = f"20{d[:2]}-{d[2:4]}-{d[4:6]}"
                except Exception:
                    size_kb = "?"
                    ctime = "?"
                    file_date = ""

                rows.append({
                    "類別": folder,
                    "子分類": subcategory,
                    "檔案名稱": fname,
                    "日期": file_date,
                    "大小": size_kb,
                    "建立時間": ctime,
                })

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    logger.info(f"Master index updated: {csv_path} ({len(rows)} files)")
    return csv_path


def generate_annual_index(year: str | None = None) -> str:
    """彙整全年各月 INDEX_總覽，生成 INDEX_年度總覽.csv

    Args:
        year: 如 '2026'，預設為今年

    Returns:
        INDEX_年度總覽.csv 的完整路徑
    """
    import csv

    if not year:
        year = str(datetime.now().year)

    year_path = os.path.join(GDRIVE_LOCAL, year)
    if not os.path.isdir(year_path):
        logger.warning(f"generate_annual_index: {year_path} not found")
        return ""

    csv_path = os.path.join(year_path, "INDEX_年度總覽.csv")
    headers = ["月份", "類別", "子分類", "檔案名稱", "日期", "大小", "建立時間"]
    rows = []

    # 掃描所有月份資料夾
    for entry in sorted(os.listdir(year_path)):
        if not entry.endswith("月"):
            continue
        month_path = os.path.join(year_path, entry)
        if not os.path.isdir(month_path):
            continue

        # 先嘗試更新該月的 master index
        month_num = entry.replace("月", "").zfill(2)
        ym = f"{year}-{month_num}"
        try:
            update_master_index(ym)
        except Exception:
            pass

        # 讀取月度 INDEX_總覽.csv
        monthly_csv = os.path.join(month_path, "INDEX_總覽.csv")
        if os.path.exists(monthly_csv):
            try:
                with open(monthly_csv, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        rows.append({
                            "月份": entry,
                            "類別": row.get("類別", ""),
                            "子分類": row.get("子分類", ""),
                            "檔案名稱": row.get("檔案名稱", ""),
                            "日期": row.get("日期", ""),
                            "大小": row.get("大小", ""),
                            "建立時間": row.get("建立時間", ""),
                        })
            except Exception as e:
                logger.warning(f"Read monthly index failed for {entry}: {e}")

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    logger.info(f"Annual index generated: {csv_path} ({len(rows)} files)")
    return csv_path


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
