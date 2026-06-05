#!/usr/bin/env python3
"""
週報產生器 - W20 (2026-05-11 ~ 2026-05-17)
規格：5 家公司各獨立分頁 + 供應商粒度 + 待確認逐筆標位置
覆蓋 /mnt/h/我的雲端硬碟/小魚資料/_週報/週報_2026-W20_2026-05-11_至_2026-05-17.xlsx
"""

import sqlite3
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import os

DB_PATH  = "/home/simon/shanbot/data/shanbot.db"
OUT_PATH = "/mnt/h/我的雲端硬碟/小魚資料/_週報/週報_2026-W20_2026-05-11_至_2026-05-17.xlsx"

DARK_BLUE   = "1F3864"
MID_BLUE    = "2E5DA3"
LIGHT_BLUE  = "BDD7EE"
PALE_BLUE   = "DEEAF1"
YELLOW_WARN = "FFE699"
RED_WARN    = "FFB3B3"
WHITE       = "FFFFFF"
LIGHT_GREY  = "F2F2F2"
RED_HDR     = "C00000"

def mf(hex_color):
    return PatternFill("solid", fgColor=hex_color)

def mb(style="thin"):
    s = Side(style=style, color="AAAAAA")
    return Border(left=s, right=s, top=s, bottom=s)

def hc(ws, row, col, value, width=None):
    c = ws.cell(row=row, column=col, value=value)
    c.font = Font(bold=True, color=WHITE, size=10, name="微軟正黑體")
    c.fill = mf(DARK_BLUE)
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    c.border = mb()
    if width:
        ws.column_dimensions[get_column_letter(col)].width = width
    return c

def dc(ws, row, col, value, fmt=None, fill_hex=None, center=False):
    c = ws.cell(row=row, column=col, value=value)
    c.font = Font(size=9, name="微軟正黑體")
    if fill_hex:
        c.fill = mf(fill_hex)
    c.alignment = Alignment(horizontal="center" if center else "left", vertical="center")
    c.border = mb()
    if fmt:
        c.number_format = fmt
    return c

def get_companies(conn):
    return conn.execute("SELECT id, short_name, full_name FROM companies ORDER BY id").fetchall()

def get_supplier_data(conn, company_id):
    return conn.execute("""
        SELECT
            COALESCE(CAST(s.id AS TEXT), 'N/A')                         AS sup_id,
            COALESCE(s.name, NULLIF(ps.supplier_name,''), '（未識別）') AS sup_name,
            COUNT(*)                                                      AS cnt,
            ROUND(SUM(COALESCE(ps.subtotal,0)),0)                        AS subtotal,
            ROUND(SUM(COALESCE(ps.tax_amount,0)),0)                      AS tax_amt,
            ROUND(SUM(COALESCE(ps.total_amount,0)),0)                    AS total,
            SUM(CASE WHEN ps.status != 'confirmed' THEN 1 ELSE 0 END)   AS unconfirmed_cnt,
            SUM(CASE WHEN ps.subtotal=0 OR ps.total_amount=0 THEN 1 ELSE 0 END) AS zero_amt_cnt,
            GROUP_CONCAT(DISTINCT ps.status)                             AS statuses
        FROM purchase_staging ps
        LEFT JOIN suppliers s ON ps.supplier_id = s.id
        WHERE ps.company_id = ?
        GROUP BY COALESCE(CAST(s.id AS TEXT), 'N/A'||ps.supplier_name),
                 COALESCE(s.name, NULLIF(ps.supplier_name,''), '（未識別）')
        ORDER BY sup_id, sup_name
    """, (company_id,)).fetchall()

# ── 00_索引 ──────────────────────────────────────────────────────────────────
def write_index(wb, companies):
    ws = wb.create_sheet("00_索引")
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:H1")
    t = ws["A1"]
    t.value = "小魚集團 週報 W20 (2026-05-11 ~ 2026-05-17)"
    t.font = Font(bold=True, size=16, color=WHITE, name="微軟正黑體")
    t.fill = mf(DARK_BLUE)
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 36

    notices = [
        ("A2:H2", "L1 大總管：本報告覆蓋 5 家公司本週進貨發票資料，供老闆掌握付款與待確認情況", PALE_BLUE),
        ("A3:H3", "L2 老闆期待：每週一份、5 家各獨立、供應商粒度、待確認逐筆標位置、財務數字可直接對帳", LIGHT_BLUE),
        ("A4:H4", "L3 員工溝通：W20 期間 purchase_date 欄位資料格式異常（部分為 1926-03-01 或 unknown），故改以 DB 全期累計資料呈現並標注。IT 請修正 OCR 日期解析邏輯後下週起可精確篩選。", YELLOW_WARN),
    ]
    for addr, txt, fill in notices:
        ws.merge_cells(addr)
        r = addr.split(":")[0][1:]
        c = ws[f"A{r}"]
        c.value = txt
        c.font = Font(size=10, name="微軟正黑體")
        c.fill = mf(fill)
        c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.row_dimensions[int(r)].height = 28

    ws.row_dimensions[5].height = 8

    hdrs = ["分頁名稱", "意義說明", "對比價值"]
    widths = [28, 55, 42]
    for i, (h, w) in enumerate(zip(hdrs, widths), 1):
        hc(ws, 6, i, h, w)
    ws.row_dimensions[6].height = 20

    sheet_info = [
        ("00_索引",             "本頁——三層對齊宣告 + 8 個分頁目錄",                             "快速定位，說明報告架構"),
        ("01_跨公司彙總",       "5 家公司供應商家數/筆數/未稅/稅/含稅/待確認對照",               "一眼看出哪家進貨最多、哪家待確認最嚴重"),
        ("02_福利社_供應商明細", "升鼎商行(福利社) 各供應商進貨明細（DB 全期）",                  "可對照應付帳款，逐筆核實發票金額"),
        ("03_王凱_供應商明細",   "王凱食品有限公司 各供應商進貨明細（本週 DB 無資料）",            "待 W20 資料補入後自動填入"),
        ("04_台達2廠_供應商明細","升鼎商行(台達2廠) 各供應商進貨明細（DB 全期）",                  "對比 02 可看兩廠同供應商進貨差異"),
        ("05_富燚_供應商明細",   "富燚商行 各供應商進貨明細（本週 DB 無資料）",                    "待 W20 資料補入後自動填入"),
        ("06_台達1廠_供應商明細","升鼎商行(台達1廠) 各供應商進貨明細（本週 DB 無資料）",           "待 W20 資料補入後自動填入"),
        ("07_待確認事項",        "跨 5 家公司所有待確認發票，逐筆標明哪個欄位不確定",               "老闆可直接交辦同仁逐筆補齊"),
        ("08_老闆brief",         "三段式老闆摘要（本週發現/控管要點/下週指示）",                   "最後讀，節省老闆時間"),
    ]

    for i, (name, meaning, value) in enumerate(sheet_info, 7):
        fill_hex = PALE_BLUE if i % 2 == 0 else WHITE
        dc(ws, i, 1, name,    fill_hex=fill_hex)
        dc(ws, i, 2, meaning, fill_hex=fill_hex)
        dc(ws, i, 3, value,   fill_hex=fill_hex)
        ws.row_dimensions[i].height = 18

# ── 01_跨公司彙總 ─────────────────────────────────────────────────────────────
def write_summary(wb, companies, company_data):
    ws = wb.create_sheet("01_跨公司彙總")
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:I1")
    t = ws["A1"]
    t.value = "跨公司彙總 — DB 全期累計（W20 purchase_date 欄位需修正後可切換精確週期）"
    t.font = Font(bold=True, size=12, color=WHITE, name="微軟正黑體")
    t.fill = mf(DARK_BLUE)
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:I2")
    ws["A2"].value = "schema_gap: purchase_date 欄格式異常（含 1926-03-01、unknown），W20 精確篩選待 IT 修正。目前以全期資料替代，供趨勢比較用。"
    ws["A2"].font = Font(size=9, italic=True, name="微軟正黑體")
    ws["A2"].fill = mf(YELLOW_WARN)
    ws["A2"].alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[2].height = 28

    cols    = ["公司代碼","公司簡稱","公司全名","供應商家數","筆數","未稅金額","稅額","含稅金額","待確認筆數"]
    widths  = [10,12,22,12,8,14,12,14,12]
    for i,(h,w) in enumerate(zip(cols,widths),1):
        hc(ws, 3, i, h, w)
    ws.row_dimensions[3].height = 20

    total_sup=total_cnt=total_sub=total_tax=total_tot=total_unc=0
    for ri, (cid, short, full) in enumerate(companies, 4):
        rows = company_data.get(cid, [])
        no_data = len(rows) == 0
        sup_count = len(set(r[0] for r in rows))
        cnt  = sum(r[2] for r in rows)
        sub  = sum(r[3] for r in rows)
        tax  = sum(r[4] for r in rows)
        tot  = sum(r[5] for r in rows)
        unc  = sum(r[6] for r in rows)
        fill = LIGHT_GREY if no_data else (PALE_BLUE if ri%2==0 else WHITE)
        dc(ws,ri,1,cid,   fill_hex=fill, center=True)
        dc(ws,ri,2,short, fill_hex=fill)
        dc(ws,ri,3,full,  fill_hex=fill)
        if no_data:
            dc(ws,ri,4,"本週無資料",fill_hex=fill,center=True)
            ws.merge_cells(f"D{ri}:I{ri}")
        else:
            for ci,v in enumerate([sup_count,cnt,sub,tax,tot,unc],4):
                dc(ws,ri,ci,v,fmt='#,##0',fill_hex=fill,center=True)
        ws.row_dimensions[ri].height = 18
        total_sup+=sup_count; total_cnt+=cnt; total_sub+=sub
        total_tax+=tax; total_tot+=tot; total_unc+=unc

    r = len(companies)+4
    for ci,v in enumerate(["","合計","",total_sup,total_cnt,total_sub,total_tax,total_tot,total_unc],1):
        c = ws.cell(row=r, column=ci, value=v)
        c.font = Font(bold=True, size=10, name="微軟正黑體", color=WHITE)
        c.fill = mf(MID_BLUE)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = mb()
        if ci>=4: c.number_format='#,##0'
    ws.row_dimensions[r].height = 20

# ── 無資料分頁 ────────────────────────────────────────────────────────────────
def write_no_data_sheet(wb, sheet_name, short, full, cid):
    ws = wb.create_sheet(sheet_name)
    ws.sheet_view.showGridLines = False
    ws.merge_cells("A1:H1")
    t = ws["A1"]
    t.value = f"{short}（{full}）— W20 供應商明細"
    t.font = Font(bold=True, size=12, color=WHITE, name="微軟正黑體")
    t.fill = mf(DARK_BLUE)
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:H4")
    ws["A2"].value = (
        f"本週（W20：2026-05-11 ~ 2026-05-17）DB 內 company_id={cid} 無 purchase_staging 資料。\n"
        "請確認：① 發票尚未上傳 ② 或本週該廠無進貨 ③ 或 purchase_date 欄位需補正。\n"
        "資料補入後重跑報告即可自動填入。"
    )
    ws["A2"].font = Font(size=11, name="微軟正黑體")
    ws["A2"].fill = mf(YELLOW_WARN)
    ws["A2"].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[2].height = 60

    cols   = ["供應商編號","供應商名稱","筆數","未稅金額","稅額","含稅金額","未確認標記(V/X)","備註"]
    widths = [12,26,8,14,12,14,16,30]
    for i,(h,w) in enumerate(zip(cols,widths),1):
        hc(ws, 5, i, h, w)
    for row in range(6,11):
        for col in range(1,9):
            dc(ws,row,col,"",fill_hex=LIGHT_GREY)
        ws.row_dimensions[row].height = 16
    return ws

# ── 公司明細分頁 ──────────────────────────────────────────────────────────────
def write_company_sheet(wb, sheet_name, short, full, cid, rows):
    ws = wb.create_sheet(sheet_name)
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:H1")
    t = ws["A1"]
    t.value = f"{short}（{full}）— 供應商明細（DB 全期，company_id={cid}）"
    t.font = Font(bold=True, size=12, color=WHITE, name="微軟正黑體")
    t.fill = mf(DARK_BLUE)
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:H2")
    ws["A2"].value = "注意：purchase_date 格式異常，以 DB 全期累計呈現。IT 修正日期欄後下週起可精確區間篩選。"
    ws["A2"].font = Font(size=9, italic=True, name="微軟正黑體")
    ws["A2"].fill = mf(YELLOW_WARN)
    ws["A2"].alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[2].height = 20

    cols   = ["供應商編號","供應商名稱","筆數","未稅金額","稅額","含稅金額","未確認標記(V/X)","備註（狀態）"]
    widths = [12,26,8,14,12,14,14,28]
    for i,(h,w) in enumerate(zip(cols,widths),1):
        hc(ws, 3, i, h, w)
    ws.row_dimensions[3].height = 20

    total_cnt=total_sub=total_tax=total_tot=total_unc=0
    for ri, row in enumerate(rows, 4):
        sup_id, sup_name, cnt, sub, tax, tot, unc_cnt, zero_cnt, statuses = row
        mark = "X" if unc_cnt > 0 else "V"
        fill = RED_WARN if mark=="X" else (PALE_BLUE if ri%2==0 else WHITE)
        dc(ws,ri,1,sup_id,    fill_hex=fill, center=True)
        dc(ws,ri,2,sup_name,  fill_hex=fill)
        dc(ws,ri,3,cnt,       fill_hex=fill, center=True)
        dc(ws,ri,4,sub,       fmt='#,##0', fill_hex=fill, center=True)
        dc(ws,ri,5,tax,       fmt='#,##0', fill_hex=fill, center=True)
        dc(ws,ri,6,tot,       fmt='#,##0', fill_hex=fill, center=True)
        dc(ws,ri,7,mark,      fill_hex=fill, center=True)
        note = f"待確認:{unc_cnt}筆" if unc_cnt>0 else "已確認"
        if zero_cnt>0: note += f" | 零金額:{zero_cnt}筆"
        dc(ws,ri,8,note, fill_hex=fill)
        ws.row_dimensions[ri].height = 16
        total_cnt+=cnt; total_sub+=sub; total_tax+=tax; total_tot+=tot; total_unc+=unc_cnt

    r = len(rows)+4
    for ci,v in enumerate(["","合計",total_cnt,total_sub,total_tax,total_tot,"",""],1):
        c = ws.cell(row=r, column=ci, value=v)
        c.font = Font(bold=True, size=10, color=WHITE, name="微軟正黑體")
        c.fill = mf(MID_BLUE)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = mb()
        if ci in (3,4,5,6): c.number_format='#,##0'
    ws.row_dimensions[r].height = 20
    return ws

# ── 07_待確認事項 ─────────────────────────────────────────────────────────────
def write_unconfirmed(wb, companies, company_data):
    ws = wb.create_sheet("07_待確認事項")
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:J1")
    t = ws["A1"]
    t.value = "待確認事項彙總（DB 全期，逐筆標明待確認位置）"
    t.font = Font(bold=True, size=13, color=WHITE, name="微軟正黑體")
    t.fill = mf(RED_HDR)
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:J2")
    ws["A2"].value = "待確認位置說明：逐筆列出具體是哪個欄位需人工補齊（供應商編號/名稱/金額/狀態）。紅底=高優先，黃底=中優先。"
    ws["A2"].font = Font(size=9, italic=True, name="微軟正黑體")
    ws["A2"].fill = mf(YELLOW_WARN)
    ws["A2"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[2].height = 20

    cols   = ["公司代碼","公司簡稱","供應商編號","供應商名稱","涉及筆數","待確認金額(含稅)","待確認位置","具體說明","優先級","處理人"]
    widths = [10,12,12,26,10,18,26,42,10,12]
    for i,(h,w) in enumerate(zip(cols,widths),1):
        hc(ws, 3, i, h, w)
    ws.row_dimensions[3].height = 20

    cur = 4
    total_items = 0
    for cid, short, full in companies:
        rows = company_data.get(cid, [])
        for row in rows:
            sup_id, sup_name, cnt, sub, tax, tot, unc_cnt, zero_cnt, statuses = row
            if unc_cnt == 0:
                continue

            issues = []
            if sup_id == 'N/A':
                issues.append("供應商編號（未對應 suppliers 表）")
            if sup_name in ('（未識別）','','null','unknown',None):
                issues.append("供應商名稱（空白或未識別）")
            if zero_cnt > 0:
                issues.append(f"金額（{zero_cnt} 筆含稅金額為 0）")
            if 'pending' in (statuses or ''):
                issues.append("發票狀態（pending 未審核）")
            if not issues:
                issues.append("發票狀態（非 confirmed）")

            location = " | ".join(issues)
            detail   = f"供應商:{sup_name} | 狀態:{statuses} | 待確認:{unc_cnt}筆 共 {tot:,.0f} 元"
            priority = "高" if (zero_cnt>0 or sup_id=='N/A') else "中"
            fill     = RED_WARN if priority=="高" else YELLOW_WARN

            dc(ws,cur,1,cid,       fill_hex=fill,center=True)
            dc(ws,cur,2,short,     fill_hex=fill)
            dc(ws,cur,3,str(sup_id),fill_hex=fill,center=True)
            dc(ws,cur,4,sup_name,  fill_hex=fill)
            dc(ws,cur,5,unc_cnt,   fill_hex=fill,center=True)
            dc(ws,cur,6,tot,       fmt='#,##0',fill_hex=fill,center=True)
            dc(ws,cur,7,location,  fill_hex=fill)
            dc(ws,cur,8,detail,    fill_hex=fill)
            dc(ws,cur,9,priority,  fill_hex=fill,center=True)
            dc(ws,cur,10,"",       fill_hex=WHITE)
            ws.row_dimensions[cur].height = 22
            cur += 1
            total_items += 1

    if total_items == 0:
        ws.merge_cells("A4:J4")
        ws["A4"].value = "本週無待確認事項"
        ws["A4"].font = Font(bold=True, size=12, name="微軟正黑體")
        ws["A4"].fill = mf(LIGHT_BLUE)
        ws["A4"].alignment = Alignment(horizontal="center", vertical="center")

    return ws, total_items

# ── 08_老闆brief ──────────────────────────────────────────────────────────────
def write_boss_brief(wb, companies, company_data, unc_count):
    ws = wb.create_sheet("08_老闆brief")
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:E1")
    t = ws["A1"]
    t.value = "老闆週報摘要 — W20 (2026-05-11 ~ 2026-05-17)"
    t.font = Font(bold=True, size=14, color=WHITE, name="微軟正黑體")
    t.fill = mf(DARK_BLUE)
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 36

    total_tot  = sum(sum(r[5] for r in rows) for rows in company_data.values())
    active_cos = sum(1 for rows in company_data.values() if rows)

    sections = [
        ("本週發現",
         f"DB 內有進貨記錄的公司共 {active_cos} 家（福利社、台達2廠）。"
         f"另外 3 家（王凱、富燚、台達1廠）本週 purchase_staging 無資料，請確認是否本週無進貨或發票未上傳。"
         f"累計含稅進貨金額（DB 全期）：{total_tot:,.0f} 元。"
         f"待確認供應商分組共 {unc_count} 組，其中高優先（零金額或無供應商編號）需優先處理。"),
        ("控管要點",
         "① 金額為 0 的筆數偏多（圻逸食品、詠源順等），請確認 OCR 是否未擷取到金額，需人工補填。\n"
         "② 供應商名稱未匹配 suppliers 表的筆數多（suppliers 表僅 13 筆），建議補建常用前 20 家供應商主表。\n"
         "③ purchase_date 欄位格式異常（含 1926-03-01、unknown 等），影響週報精確篩選，IT 請優先修正 OCR 日期解析邏輯。"),
        ("下週指示",
         "① 同仁本週五前確認所有 status=pending 發票，confirm 入帳。\n"
         "② IT 修正 purchase_date 日期格式（應為 YYYY-MM-DD），下週報告起可精確 W21 篩選。\n"
         "③ 補建供應商主表：前 20 家常用供應商 ID 對應補齊，減少 N/A 筆數。"),
    ]

    row = 3
    for title, content in sections:
        ws.merge_cells(f"A{row}:E{row}")
        h = ws.cell(row=row, column=1, value=title)
        h.font = Font(bold=True, size=12, color=WHITE, name="微軟正黑體")
        h.fill = mf(MID_BLUE)
        h.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[row].height = 24
        row += 1

        ws.merge_cells(f"A{row}:E{row}")
        c = ws.cell(row=row, column=1, value=content)
        c.font = Font(size=11, name="微軟正黑體")
        c.fill = mf(PALE_BLUE)
        c.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        ws.row_dimensions[row].height = 80
        row += 2

    for col in "ABCDE":
        ws.column_dimensions[col].width = 55 if col=="A" else 12

# ── 主程式 ────────────────────────────────────────────────────────────────────
def main():
    conn = sqlite3.connect(DB_PATH)
    companies = get_companies(conn)

    company_data = {}
    for cid, short, full in companies:
        company_data[cid] = get_supplier_data(conn, cid)
    conn.close()

    wb = openpyxl.Workbook()
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]

    write_index(wb, companies)
    write_summary(wb, companies, company_data)

    sheet_map = [
        (1, "02_福利社_供應商明細",  "福利社",  "升鼎商行"),
        (2, "03_王凱_供應商明細",    "王凱",    "王凱食品有限公司"),
        (3, "04_台達2廠_供應商明細", "台達2廠", "升鼎商行"),
        (4, "05_富燚_供應商明細",    "富燚",    "富燚商行"),
        (5, "06_台達1廠_供應商明細", "台達1廠", "升鼎商行"),
    ]
    for cid, sname, short, full in sheet_map:
        rows = company_data.get(cid, [])
        if rows:
            write_company_sheet(wb, sname, short, full, cid, rows)
        else:
            write_no_data_sheet(wb, sname, short, full, cid)

    _, unc_count = write_unconfirmed(wb, companies, company_data)
    write_boss_brief(wb, companies, company_data, unc_count)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    wb.save(OUT_PATH)
    print(f"[OK] Saved: {OUT_PATH}")
    print(f"Sheets: {wb.sheetnames}")
    print(f"Companies with data: {sum(1 for r in company_data.values() if r)}/5")
    print(f"Unconfirmed groups: {unc_count}")

if __name__ == "__main__":
    main()
