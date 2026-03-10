"""小膳 Bot — 會計自動化服務

拍照 → OCR → 確認歸檔 → 自動完成所有會計流程：
1. 生成複式分錄（借貸平衡）
2. 更新日記帳 Excel（含所有欄位）
3. 更新月度費用彙總表
4. 維護試算表（驗證借貸平衡）

嚴格遵循複式簿記原則：每筆交易的借方合計 = 貸方合計
"""

import logging
import os
from datetime import datetime

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import state_manager as sm

logger = logging.getLogger("shanbot.accounting")

# GDrive mount path
GDRIVE_BASE = os.environ.get("GDRIVE_MOUNT", "/mnt/h/我的雲端硬碟")
ACCOUNTING_DIR = os.path.join(GDRIVE_BASE, "小膳", "會計帳冊")

# 會計科目對照（進貨分類 → 會計科目）
CATEGORY_ACCOUNT_MAP = {
    "蔬菜": ("5110", "進貨—蔬菜類"),
    "肉類": ("5110", "進貨—肉類"),
    "水產": ("5110", "進貨—水產類"),
    "蛋豆": ("5110", "進貨—蛋豆類"),
    "乾貨": ("5110", "進貨—乾貨類"),
    "調味料": ("5110", "進貨—調味料"),
    "油品": ("5110", "進貨—油品類"),
    "米糧": ("5110", "進貨—米糧類"),
    "other": ("5110", "進貨—其他"),
    "其他": ("5110", "進貨—其他"),
}

# Excel 樣式
_HEADER_FONT = Font(name="微軟正黑體", size=11, bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill(start_color="2E7D32", end_color="2E7D32", fill_type="solid")
_TITLE_FONT = Font(name="微軟正黑體", size=14, bold=True)
_NORMAL_FONT = Font(name="微軟正黑體", size=10)
_MONEY_FMT = '#,##0'
_DATE_FMT = 'YYYY-MM-DD'
_THIN_BORDER = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin"),
)
_CENTER = Alignment(horizontal="center", vertical="center")
_RIGHT = Alignment(horizontal="right", vertical="center")


def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


# =====================================================================
# 1. 分錄生成（複式簿記核心）
# =====================================================================

def generate_journal_entries(staging_id: int) -> list[dict]:
    """根據確認後的 staging 自動生成複式分錄

    採購交易的分錄邏輯：
      借：進貨（按分類）      金額
      借：進項稅額            稅額（如可扣抵）
      貸：現金 / 應付帳款     總金額

    收入交易的分錄邏輯：
      借：現金                金額
      貸：營業收入            金額
      貸：銷項稅額            稅額

    Returns: 生成的分錄列表
    """
    staging = sm.get_staging(staging_id)
    if not staging:
        logger.warning(f"Staging #{staging_id} not found")
        return []

    items = sm.get_purchase_items(staging_id)
    entry_date = staging.get("purchase_date") or datetime.now().strftime("%Y-%m-%d")
    year_month = staging.get("year_month") or entry_date[:7]
    supplier = staging.get("supplier_name") or "未知"
    total_amount = staging.get("total_amount") or 0
    tax_amount = staging.get("tax_amount") or 0
    subtotal = staging.get("subtotal") or (total_amount - tax_amount)
    deduction_code = staging.get("deduction_code") or "1"

    # 清除舊分錄（防重複）
    sm.delete_journal_entries_by_source("purchase", staging_id)

    entries = []

    # === 借方：進貨科目 ===
    total_debit = 0

    if items:
        # 按分類彙總金額
        cat_totals = {}
        for item in items:
            cat = item.get("category") or "other"
            amt = item.get("amount") or 0
            if cat not in cat_totals:
                cat_totals[cat] = 0
            cat_totals[cat] += amt

        items_total = sum(cat_totals.values())

        # 如果品項金額與 subtotal 有差異，按比例調整以確保平衡
        scale = (subtotal / items_total) if items_total > 0 else 1

        for cat, amt in cat_totals.items():
            if amt <= 0:
                continue
            scaled_amt = round(amt * scale, 0)
            code, name = CATEGORY_ACCOUNT_MAP.get(cat, ("5110", "進貨—其他"))
            eid = sm.add_journal_entry(
                entry_date=entry_date, year_month=year_month,
                source_type="purchase", source_id=staging_id,
                description=f"進貨-{supplier}（{cat}）",
                account_code=code, account_name=name,
                debit=scaled_amt, credit=0,
            )
            total_debit += scaled_amt
            entries.append({"id": eid, "side": "debit", "account": name, "amount": scaled_amt})
    else:
        # 沒有明細 → 整筆作為進貨
        eid = sm.add_journal_entry(
            entry_date=entry_date, year_month=year_month,
            source_type="purchase", source_id=staging_id,
            description=f"進貨-{supplier}",
            account_code="5110", account_name="進貨",
            debit=round(subtotal, 0), credit=0,
        )
        total_debit += round(subtotal, 0)
        entries.append({"id": eid, "side": "debit", "account": "進貨", "amount": subtotal})

    # === 借方：進項稅額（可扣抵時）===
    if tax_amount > 0 and deduction_code == "1":
        eid = sm.add_journal_entry(
            entry_date=entry_date, year_month=year_month,
            source_type="purchase", source_id=staging_id,
            description=f"進項稅額-{supplier}",
            account_code="1150", account_name="進項稅額",
            debit=round(tax_amount, 0), credit=0,
        )
        total_debit += round(tax_amount, 0)
        entries.append({"id": eid, "side": "debit", "account": "進項稅額", "amount": tax_amount})

    # === 貸方：現金（= 借方合計，確保借貸平衡）===
    credit_amount = total_debit

    eid = sm.add_journal_entry(
        entry_date=entry_date, year_month=year_month,
        source_type="purchase", source_id=staging_id,
        description=f"付款-{supplier}",
        account_code="1100", account_name="現金",
        debit=0, credit=credit_amount,
    )
    entries.append({"id": eid, "side": "credit", "account": "現金", "amount": credit_amount})

    logger.info(f"Generated {len(entries)} journal entries for staging #{staging_id}")
    return entries


def verify_balance(staging_id: int) -> dict:
    """驗證單筆交易的借貸平衡"""
    entries = sm.get_journal_entries_by_source("purchase", staging_id)
    total_debit = sum(e.get("debit", 0) for e in entries)
    total_credit = sum(e.get("credit", 0) for e in entries)
    balanced = abs(total_debit - total_credit) < 1  # 容許 $1 四捨五入差
    return {
        "staging_id": staging_id,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "difference": total_debit - total_credit,
        "balanced": balanced,
        "entry_count": len(entries),
    }


# =====================================================================
# 2. 日記帳 Excel 生成（進銷存明細）
# =====================================================================

def generate_accounting_excel(year_month: str) -> str | None:
    """生成月度會計 Excel（日記帳 + 分類彙總 + 試算表 + 分錄明細）

    Sheet 1: 進貨日記帳（日期/供應商/項目名稱/單價/數量/總價/備註）
    Sheet 2: 月度費用彙總（按供應商 + 按分類）
    Sheet 3: 試算表（各科目借貸合計，驗證平衡）
    Sheet 4: 分錄明細（完整日記帳分錄）

    Returns: Excel 檔案路徑
    """
    out_dir = os.path.join(ACCOUNTING_DIR, year_month)
    _ensure_dir(out_dir)
    filepath = os.path.join(out_dir, f"{year_month}_會計帳冊.xlsx")

    stagings = sm.get_stagings_by_month(year_month)
    journal_entries = sm.get_journal_entries(year_month)
    trial_balance = sm.get_trial_balance(year_month)
    income_rows = sm.get_income_summary(year_month)

    wb = openpyxl.Workbook()

    # --- Sheet 1: 進貨日記帳 ---
    ws1 = wb.active
    ws1.title = "進貨日記帳"
    _write_purchase_journal(ws1, stagings, year_month)

    # --- Sheet 2: 月度費用彙總 ---
    ws2 = wb.create_sheet("月度費用彙總")
    _write_expense_summary(ws2, stagings, year_month)

    # --- Sheet 3: 試算表（借貸平衡驗證）---
    ws3 = wb.create_sheet("試算表")
    _write_trial_balance(ws3, trial_balance, year_month)

    # --- Sheet 4: 分錄明細 ---
    ws4 = wb.create_sheet("分錄明細")
    _write_journal_entries_sheet(ws4, journal_entries, year_month)

    # --- Sheet 5: 收入明細 ---
    if income_rows:
        ws5 = wb.create_sheet("收入明細")
        _write_income_sheet(ws5, income_rows, year_month)

    wb.save(filepath)
    logger.info(f"Accounting Excel generated: {filepath}")

    # 更新月度會計總表
    _update_monthly_accounting(year_month, filepath, journal_entries, income_rows, stagings)

    return filepath


def _write_purchase_journal(ws, stagings: list, year_month: str):
    """Sheet 1: 進貨日記帳明細"""
    # 標題
    ws.merge_cells("A1:H1")
    ws["A1"] = f"進貨日記帳 — {year_month}"
    ws["A1"].font = _TITLE_FONT

    # 欄位標題
    headers = ["日期", "供應商", "項目名稱", "數量", "單位", "單價", "總價", "備註"]
    widths = [12, 16, 20, 8, 6, 10, 12, 20]

    for col_idx, (header, width) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=3, column=col_idx, value=header)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _CENTER
        cell.border = _THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    row = 4
    grand_total = 0

    for staging in stagings:
        items = sm.get_purchase_items(staging["id"])
        supplier = staging.get("supplier_name") or "未知"
        pdate = staging.get("purchase_date") or ""
        notes = staging.get("notes") or ""

        if items:
            for item in items:
                amt = item.get("amount") or 0
                ws.cell(row=row, column=1, value=pdate).font = _NORMAL_FONT
                ws.cell(row=row, column=2, value=supplier).font = _NORMAL_FONT
                ws.cell(row=row, column=3, value=item.get("item_name", "")).font = _NORMAL_FONT
                ws.cell(row=row, column=4, value=item.get("quantity", 0)).font = _NORMAL_FONT
                ws.cell(row=row, column=5, value=item.get("unit", "")).font = _NORMAL_FONT

                price_cell = ws.cell(row=row, column=6, value=item.get("unit_price", 0))
                price_cell.font = _NORMAL_FONT
                price_cell.number_format = _MONEY_FMT
                price_cell.alignment = _RIGHT

                amt_cell = ws.cell(row=row, column=7, value=amt)
                amt_cell.font = _NORMAL_FONT
                amt_cell.number_format = _MONEY_FMT
                amt_cell.alignment = _RIGHT

                ws.cell(row=row, column=8, value=notes).font = _NORMAL_FONT

                for c in range(1, 9):
                    ws.cell(row=row, column=c).border = _THIN_BORDER
                grand_total += amt
                row += 1
        else:
            # 無明細，整筆記錄
            amt = staging.get("total_amount") or 0
            ws.cell(row=row, column=1, value=pdate).font = _NORMAL_FONT
            ws.cell(row=row, column=2, value=supplier).font = _NORMAL_FONT
            ws.cell(row=row, column=3, value="（整筆進貨）").font = _NORMAL_FONT
            ws.cell(row=row, column=4, value="").font = _NORMAL_FONT
            ws.cell(row=row, column=5, value="").font = _NORMAL_FONT
            ws.cell(row=row, column=6, value="").font = _NORMAL_FONT

            amt_cell = ws.cell(row=row, column=7, value=amt)
            amt_cell.font = _NORMAL_FONT
            amt_cell.number_format = _MONEY_FMT
            amt_cell.alignment = _RIGHT

            ws.cell(row=row, column=8, value=notes).font = _NORMAL_FONT
            for c in range(1, 9):
                ws.cell(row=row, column=c).border = _THIN_BORDER
            grand_total += amt
            row += 1

    # 合計列
    row += 1
    ws.cell(row=row, column=6, value="合計").font = Font(name="微軟正黑體", size=11, bold=True)
    total_cell = ws.cell(row=row, column=7, value=grand_total)
    total_cell.font = Font(name="微軟正黑體", size=11, bold=True)
    total_cell.number_format = _MONEY_FMT
    total_cell.alignment = _RIGHT


def _write_expense_summary(ws, stagings: list, year_month: str):
    """Sheet 2: 月度費用彙總（按供應商 + 按分類）"""
    ws.merge_cells("A1:D1")
    ws["A1"] = f"月度費用彙總 — {year_month}"
    ws["A1"].font = _TITLE_FONT

    # --- 按供應商彙總 ---
    ws.cell(row=3, column=1, value="【按供應商彙總】").font = Font(
        name="微軟正黑體", size=11, bold=True)

    headers_s = ["供應商", "筆數", "金額", "稅額"]
    for col_idx, h in enumerate(headers_s, 1):
        cell = ws.cell(row=4, column=col_idx, value=h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _CENTER
        cell.border = _THIN_BORDER
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 8
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 12

    supplier_totals = {}
    for s in stagings:
        name = s.get("supplier_name") or "未知"
        if name not in supplier_totals:
            supplier_totals[name] = {"count": 0, "amount": 0, "tax": 0}
        supplier_totals[name]["count"] += 1
        supplier_totals[name]["amount"] += s.get("total_amount") or 0
        supplier_totals[name]["tax"] += s.get("tax_amount") or 0

    row = 5
    for name, data in sorted(supplier_totals.items(), key=lambda x: -x[1]["amount"]):
        ws.cell(row=row, column=1, value=name).font = _NORMAL_FONT
        ws.cell(row=row, column=2, value=data["count"]).font = _NORMAL_FONT
        c = ws.cell(row=row, column=3, value=data["amount"])
        c.font = _NORMAL_FONT
        c.number_format = _MONEY_FMT
        c.alignment = _RIGHT
        t = ws.cell(row=row, column=4, value=data["tax"])
        t.font = _NORMAL_FONT
        t.number_format = _MONEY_FMT
        t.alignment = _RIGHT
        for col in range(1, 5):
            ws.cell(row=row, column=col).border = _THIN_BORDER
        row += 1

    # --- 按分類彙總 ---
    row += 2
    ws.cell(row=row, column=1, value="【按分類彙總】").font = Font(
        name="微軟正黑體", size=11, bold=True)
    row += 1

    headers_c = ["分類", "金額", "佔比"]
    for col_idx, h in enumerate(headers_c, 1):
        cell = ws.cell(row=row, column=col_idx, value=h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _CENTER
        cell.border = _THIN_BORDER

    cat_totals = {}
    total_amount = 0
    for s in stagings:
        items = sm.get_purchase_items(s["id"])
        for item in items:
            cat = item.get("category") or "其他"
            amt = item.get("amount") or 0
            cat_totals[cat] = cat_totals.get(cat, 0) + amt
            total_amount += amt

    row += 1
    for cat, amt in sorted(cat_totals.items(), key=lambda x: -x[1]):
        pct = (amt / total_amount * 100) if total_amount > 0 else 0
        ws.cell(row=row, column=1, value=cat).font = _NORMAL_FONT
        c = ws.cell(row=row, column=2, value=amt)
        c.font = _NORMAL_FONT
        c.number_format = _MONEY_FMT
        c.alignment = _RIGHT
        p = ws.cell(row=row, column=3, value=f"{pct:.1f}%")
        p.font = _NORMAL_FONT
        p.alignment = _RIGHT
        for col in range(1, 4):
            ws.cell(row=row, column=col).border = _THIN_BORDER
        row += 1


def _write_trial_balance(ws, trial_balance: list, year_month: str):
    """Sheet 3: 試算表（借貸平衡驗證）"""
    ws.merge_cells("A1:E1")
    ws["A1"] = f"試算表 — {year_month}"
    ws["A1"].font = _TITLE_FONT

    headers = ["科目代碼", "科目名稱", "借方合計", "貸方合計", "餘額"]
    widths = [12, 20, 14, 14, 14]

    for col_idx, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=3, column=col_idx, value=h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _CENTER
        cell.border = _THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = w

    row = 4
    sum_debit = 0
    sum_credit = 0

    for tb in trial_balance:
        ws.cell(row=row, column=1, value=tb["account_code"]).font = _NORMAL_FONT
        ws.cell(row=row, column=2, value=tb["account_name"]).font = _NORMAL_FONT

        d = ws.cell(row=row, column=3, value=tb["total_debit"])
        d.font = _NORMAL_FONT
        d.number_format = _MONEY_FMT
        d.alignment = _RIGHT

        c = ws.cell(row=row, column=4, value=tb["total_credit"])
        c.font = _NORMAL_FONT
        c.number_format = _MONEY_FMT
        c.alignment = _RIGHT

        b = ws.cell(row=row, column=5, value=tb["balance"])
        b.font = _NORMAL_FONT
        b.number_format = _MONEY_FMT
        b.alignment = _RIGHT

        for col in range(1, 6):
            ws.cell(row=row, column=col).border = _THIN_BORDER

        sum_debit += tb["total_debit"]
        sum_credit += tb["total_credit"]
        row += 1

    # 合計
    row += 1
    ws.cell(row=row, column=2, value="合計").font = Font(name="微軟正黑體", size=11, bold=True)
    sd = ws.cell(row=row, column=3, value=sum_debit)
    sd.font = Font(name="微軟正黑體", size=11, bold=True)
    sd.number_format = _MONEY_FMT
    sd.alignment = _RIGHT

    sc = ws.cell(row=row, column=4, value=sum_credit)
    sc.font = Font(name="微軟正黑體", size=11, bold=True)
    sc.number_format = _MONEY_FMT
    sc.alignment = _RIGHT

    diff = sum_debit - sum_credit
    diff_cell = ws.cell(row=row, column=5, value=diff)
    diff_cell.font = Font(name="微軟正黑體", size=11, bold=True,
                          color="FF0000" if abs(diff) > 0.5 else "008000")
    diff_cell.number_format = _MONEY_FMT
    diff_cell.alignment = _RIGHT

    # 平衡驗證標記
    row += 2
    balanced = abs(diff) < 1
    status = "✅ 借貸平衡" if balanced else "❌ 借貸不平衡！差額 ${:,.0f}".format(diff)
    ws.cell(row=row, column=1, value=status).font = Font(
        name="微軟正黑體", size=12, bold=True,
        color="008000" if balanced else "FF0000")


def _write_journal_entries_sheet(ws, entries: list, year_month: str):
    """Sheet 4: 分錄明細"""
    ws.merge_cells("A1:G1")
    ws["A1"] = f"分錄明細（日記帳）— {year_month}"
    ws["A1"].font = _TITLE_FONT

    headers = ["日期", "摘要", "科目代碼", "科目名稱", "借方", "貸方", "來源"]
    widths = [12, 24, 10, 16, 12, 12, 10]

    for col_idx, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=3, column=col_idx, value=h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _CENTER
        cell.border = _THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = w

    row = 4
    for e in entries:
        ws.cell(row=row, column=1, value=e.get("entry_date", "")).font = _NORMAL_FONT
        ws.cell(row=row, column=2, value=e.get("description", "")).font = _NORMAL_FONT
        ws.cell(row=row, column=3, value=e.get("account_code", "")).font = _NORMAL_FONT
        ws.cell(row=row, column=4, value=e.get("account_name", "")).font = _NORMAL_FONT

        d = ws.cell(row=row, column=5, value=e.get("debit", 0) or "")
        d.font = _NORMAL_FONT
        if e.get("debit"):
            d.number_format = _MONEY_FMT
        d.alignment = _RIGHT

        c = ws.cell(row=row, column=6, value=e.get("credit", 0) or "")
        c.font = _NORMAL_FONT
        if e.get("credit"):
            c.number_format = _MONEY_FMT
        c.alignment = _RIGHT

        source = f"{e.get('source_type', '')}#{e.get('source_id', '')}"
        ws.cell(row=row, column=7, value=source).font = _NORMAL_FONT

        for col in range(1, 8):
            ws.cell(row=row, column=col).border = _THIN_BORDER
        row += 1


def _write_income_sheet(ws, income_rows: list, year_month: str):
    """Sheet 5: 收入明細"""
    ws.merge_cells("A1:E1")
    ws["A1"] = f"收入明細 — {year_month}"
    ws["A1"].font = _TITLE_FONT

    headers = ["日期", "說明", "來源", "金額", "備註"]
    widths = [12, 24, 12, 14, 16]

    for col_idx, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=3, column=col_idx, value=h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _CENTER
        cell.border = _THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = w

    row = 4
    total = 0
    for inc in income_rows:
        ws.cell(row=row, column=1, value=inc.get("income_date", "")).font = _NORMAL_FONT
        ws.cell(row=row, column=2, value=inc.get("description", "")).font = _NORMAL_FONT
        ws.cell(row=row, column=3, value=inc.get("source", "")).font = _NORMAL_FONT
        a = ws.cell(row=row, column=4, value=inc.get("amount", 0))
        a.font = _NORMAL_FONT
        a.number_format = _MONEY_FMT
        a.alignment = _RIGHT
        ws.cell(row=row, column=5, value="").font = _NORMAL_FONT
        for col in range(1, 6):
            ws.cell(row=row, column=col).border = _THIN_BORDER
        total += inc.get("amount", 0)
        row += 1

    row += 1
    ws.cell(row=row, column=3, value="合計").font = Font(name="微軟正黑體", size=11, bold=True)
    t = ws.cell(row=row, column=4, value=total)
    t.font = Font(name="微軟正黑體", size=11, bold=True)
    t.number_format = _MONEY_FMT
    t.alignment = _RIGHT


def _update_monthly_accounting(year_month: str, excel_path: str,
                               journal_entries: list, income_rows: list,
                               stagings: list):
    """更新月度會計總表"""
    total_income = sum(r.get("amount", 0) for r in income_rows)
    total_expense = sum(s.get("total_amount", 0) for s in stagings)
    total_tax = sum(s.get("tax_amount", 0) for s in stagings)
    net_profit = total_income - total_expense

    sm.upsert_monthly_accounting(
        year_month,
        total_income=total_income,
        total_expense=total_expense,
        total_tax=total_tax,
        net_profit=net_profit,
        journal_count=len(journal_entries),
        excel_path=excel_path,
    )


# =====================================================================
# 3. 歸檔後一鍵會計（主入口）
# =====================================================================

def process_after_archive(staging_id: int) -> str:
    """歸檔後自動完成所有會計流程

    Called from command_handler._execute_archive() after confirm.
    1. 生成分錄
    2. 驗證借貸平衡
    3. 更新月度 Excel

    Returns: 會計處理結果摘要
    """
    staging = sm.get_staging(staging_id)
    if not staging:
        return ""

    year_month = staging.get("year_month") or datetime.now().strftime("%Y-%m")

    try:
        # Step 1: 生成分錄
        entries = generate_journal_entries(staging_id)

        # Step 2: 驗證借貸平衡
        balance = verify_balance(staging_id)

        # Step 3: 更新月度 Excel
        excel_path = None
        try:
            excel_path = generate_accounting_excel(year_month)
        except Exception as e:
            logger.warning(f"Excel generation failed (non-fatal): {e}")

        # 回覆摘要
        parts = [f"\n📊 會計：{len(entries)} 筆分錄"]
        if balance["balanced"]:
            parts.append("✅ 借貸平衡")
        else:
            parts.append(f"⚠️ 差額 ${balance['difference']:,.0f}")
        if excel_path:
            parts.append(f"📁 帳冊已更新")

        return " | ".join(parts)

    except Exception as e:
        logger.error(f"Accounting process failed for staging #{staging_id}: {e}")
        return f"\n⚠️ 會計處理異常：{e}"


# =====================================================================
# 4. 月度報表快捷
# =====================================================================

def get_monthly_report_text(year_month: str) -> str:
    """取得月度會計文字摘要（LINE 回覆用）"""
    summary = sm.get_journal_summary(year_month)
    accounting = sm.get_monthly_accounting(year_month)
    stagings = sm.get_stagings_by_month(year_month)

    lines = [f"📊 {year_month} 會計摘要", ""]

    # 支出
    total_expense = sum(s.get("total_amount", 0) for s in stagings)
    total_tax = sum(s.get("tax_amount", 0) for s in stagings)
    lines.append(f"📦 進貨支出：${total_expense:,.0f}（{len(stagings)} 筆）")
    lines.append(f"💰 進項稅額：${total_tax:,.0f}")

    # 收入
    income_rows = sm.get_income_summary(year_month)
    total_income = sum(r.get("amount", 0) for r in income_rows)
    if total_income > 0:
        lines.append(f"💵 營業收入：${total_income:,.0f}")
        lines.append(f"📈 淨利：${total_income - total_expense:,.0f}")

    # 分錄
    lines.append(f"\n📝 分錄：{summary['count']} 筆")
    if summary["count"] > 0:
        status = "✅ 借貸平衡" if summary["balanced"] else "❌ 不平衡"
        lines.append(f"   借方合計：${summary['total_debit']:,.0f}")
        lines.append(f"   貸方合計：${summary['total_credit']:,.0f}")
        lines.append(f"   {status}")

    # Excel 路徑
    if accounting and accounting.get("excel_path"):
        lines.append(f"\n📁 帳冊：會計帳冊/{year_month}/")

    return "\n".join(lines)
