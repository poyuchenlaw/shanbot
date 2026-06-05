#!/usr/bin/env python3
"""shanbot 每週驗收週報 — 單檔多分頁版（含索引頁）"""
import os, sys, argparse
from datetime import datetime, timedelta, date
sys.path.insert(0, "/home/simon/shanbot")
import state_manager as sm
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

GDRIVE_ROOT = "/mnt/h/我的雲端硬碟/小魚資料/團膳公司資料"
HFILL = PatternFill("solid", start_color="4472C4")
HFONT = Font(bold=True, color="FFFFFF")
SUB = PatternFill("solid", start_color="D9E2F3")
DESC = PatternFill("solid", start_color="FFF2CC")  # 說明區黃底
INDEX_FILL = PatternFill("solid", start_color="1F3864")
WARN = PatternFill("solid", start_color="FCE4D6")
OK = PatternFill("solid", start_color="E2EFDA")
BORDER = Border(*[Side(style="thin", color="BFBFBF")]*4)

def hdr_row(ws, row, n):
    for c in range(1, n+1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HFILL; cell.font = HFONT
        cell.alignment = Alignment(horizontal="center"); cell.border = BORDER

def widths(ws, ws_widths):
    for i, w in enumerate(ws_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

def add_desc(ws, ncols, meaning, compare_value):
    """每個 data sheet 開頭 3-5 行說明區（憲法強制）"""
    ws.cell(row=1, column=1, value=f"【本頁意義】{meaning}").font = Font(bold=True, size=12, color="1F3864")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    ws.cell(row=1, column=1).fill = DESC
    ws.cell(row=2, column=1, value=f"【對比價值】{compare_value}").font = Font(italic=True, color="404040")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
    ws.cell(row=2, column=1).fill = DESC
    ws.row_dimensions[1].height = 22
    ws.row_dimensions[2].height = 20

def fetch_week(cid, s, e):
    conn = sm._get_conn()
    rows = conn.execute("SELECT * FROM purchase_staging WHERE company_id=? "
        "AND date(created_at,'localtime') BETWEEN ? AND ? ORDER BY created_at",
        (cid, s, e)).fetchall()
    conn.close(); return [dict(r) for r in rows]

def fetch_carryover(cid, s):
    conn = sm._get_conn()
    rows = conn.execute("SELECT * FROM purchase_staging WHERE company_id=? AND status='pending' "
        "AND date(created_at,'localtime') < ? ORDER BY created_at DESC LIMIT 50",
        (cid, s)).fetchall()
    conn.close(); return [dict(r) for r in rows]

def archived(s): return bool(s.get("gdrive_path") and "/mnt/h" in (s.get("gdrive_path") or ""))

def missing(s):
    m = []
    if not s.get("supplier_name"): m.append("供應商")
    if not s.get("purchase_date"): m.append("日期")
    if not (s.get("total_amount") or 0): m.append("金額")
    if not s.get("invoice_number") and (s.get("total_amount") or 0) >= 500: m.append("發票號碼")
    return m

def build_index(ws, s, e, n_companies, pages):
    """00_索引頁"""
    ws.title = "00_索引"
    ws.cell(row=1, column=1, value=f"小膳 BOT 週報 ｜ {s} ~ {e}").font = Font(bold=True, size=18, color="FFFFFF")
    ws.cell(row=1, column=1).fill = INDEX_FILL
    ws.merge_cells("A1:D1"); ws.row_dimensions[1].height = 30
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")

    ws.cell(row=2, column=1, value=f"產出時間 {datetime.now():%Y-%m-%d %H:%M}  ｜  {n_companies} 家公司  ｜  Cymon 自動產出").font = Font(italic=True, color="595959")
    ws.merge_cells("A2:D2")
    ws.cell(row=3, column=1, value="").fill = PatternFill()  # spacer

    ws.cell(row=4, column=1, value="本份報表怎麼看：").font = Font(bold=True, size=12, color="1F3864")
    intro = [
        "1. 先看『01_跨公司彙總』瞄一眼五家公司本週狀態（哪家進件多、哪家待確認多）",
        "2. 再針對待確認多 / 缺欄位多的公司，點對應分頁看明細",
        "3. 最後看『98_全公司品項明細』『99_全公司待辦』做行動清單",
        "4. 老闆關心的『收款 / 票期 / 預算』在每家公司分頁的最下方，目前 schema 未啟用會明寫提示",
    ]
    for i, line in enumerate(intro, 5):
        ws.cell(row=i, column=1, value=line).alignment = Alignment(wrap_text=True)
        ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=4)

    start = 4 + len(intro) + 2
    ws.cell(row=start, column=1, value="分頁目錄").font = Font(bold=True, size=12, color="1F3864")
    start += 1
    headers = ["#", "分頁名稱", "意義", "對比價值"]
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=start, column=i, value=h)
        c.fill = HFILL; c.font = HFONT; c.border = BORDER
        c.alignment = Alignment(horizontal="center")
    for j, (sheet_name, meaning, compare) in enumerate(pages, 1):
        r = start + j
        ws.cell(row=r, column=1, value=j).border = BORDER
        ws.cell(row=r, column=2, value=sheet_name).border = BORDER
        ws.cell(row=r, column=3, value=meaning).border = BORDER
        ws.cell(row=r, column=3).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=r, column=4, value=compare).border = BORDER
        ws.cell(row=r, column=4).alignment = Alignment(wrap_text=True, vertical="top")

    cross = start + len(pages) + 3
    ws.cell(row=cross, column=1, value="跨分頁對比可以得到什麼資訊").font = Font(bold=True, size=12, color="1F3864")
    compares = [
        ("01 跨公司彙總 × 02-06 各公司分頁", "哪家公司本週 OCR 信心特別低 / 待確認特別多 → 派人重點處理"),
        ("各公司『本週新增』vs『上週遺留 pending』", "若上週遺留 > 本週新增 → 處理速度跟不上進件速度，老闆要催"),
        ("98 全公司品項明細 × 各公司供應商統計", "找出跨公司共用的供應商，可以議價談批量折扣"),
        ("各公司『七、老闆關心』section", "看 5 家是否都同樣缺收款/AR/票期資料 → 確認下階段 M3 schema 補強優先級"),
    ]
    for i, (key, val) in enumerate(compares, 1):
        c = ws.cell(row=cross+i, column=1, value=f"• {key}"); c.font = Font(bold=True); c.alignment = Alignment(vertical="top")
        c2 = ws.cell(row=cross+i, column=2, value=val); c2.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=cross+i, start_column=2, end_row=cross+i, end_column=4)
        ws.row_dimensions[cross+i].height = 30

    widths(ws, [6, 24, 40, 50])

def build_cross_company(ws, summaries, s, e):
    ws.title = "01_跨公司彙總"
    add_desc(ws, 8,
        f"五家公司本週（{s}~{e}）進件、確認、待辦的橫向對比",
        "對比各公司表現，找出本週重點處理對象（待確認多/低信心多/上週遺留多的）")
    headers = ["公司","收件張數","已確認","待確認","含稅金額","缺欄位","低信心 OCR","上週遺留"]
    r0 = 4
    for i, h in enumerate(headers, 1):
        ws.cell(row=r0, column=i, value=h)
    hdr_row(ws, r0, len(headers))
    tot = [0]*7
    for x in summaries:
        ws.append([x["c"], x["n"], x["conf"], x["pend"], round(x["amt"]), x["mf"], x["low"], x["cr"]])
        for i, v in enumerate([x["n"], x["conf"], x["pend"], round(x["amt"]), x["mf"], x["low"], x["cr"]]):
            tot[i] += v
    ws.append(["合計"] + tot); rmax = ws.max_row
    for c in range(1, 9):
        ws.cell(row=rmax, column=c).font = Font(bold=True); ws.cell(row=rmax, column=c).fill = SUB
    widths(ws, [12,10,10,10,14,10,12,12])
    ws.freeze_panes = "A5"

def build_company(ws, sheet_name, c, s, e, st, cr):
    ws.title = sheet_name
    add_desc(ws, 7,
        f"{c['short_name']} 本週驗收摘要 + 收據明細 + 老闆關心面",
        f"跟『01_跨公司彙總』對比，看{c['short_name']}相對其他 4 家的位置；下方老闆關心面提示缺哪些 schema")

    n = len(st)
    conf = sum(1 for x in st if x["status"]=="confirmed")
    pend = sum(1 for x in st if x["status"]=="pending")
    tot = sum((x.get("total_amount") or 0) for x in st)
    tax = sum((x.get("tax_amount") or 0) for x in st)
    sub = tot - tax
    h = sum(1 for x in st if (x.get("ocr_confidence") or 0) >= 80)
    mid = sum(1 for x in st if 60 <= (x.get("ocr_confidence") or 0) < 80)
    low = sum(1 for x in st if (x.get("ocr_confidence") or 0) < 60)
    arc = sum(1 for x in st if archived(x))
    inv = sum(1 for x in st if x.get("invoice_number"))
    mf = sum(1 for x in st if missing(x))

    sections = [
        ("一、本週收件", [("收到憑證張數", n), ("已確認", conf), ("待確認", pend)]),
        ("二、金額", [("含稅總額", f"{tot:,.0f}"), ("未稅小計", f"{sub:,.0f}"), ("進項稅額", f"{tax:,.0f}")]),
        ("三、發票/收據", [("有發票號碼", inv), ("收據/手寫", n - inv)]),
        ("四、OCR 品質", [("高信心 (≥80)", h), ("中信心 (60-80)", mid), ("低信心 (<60)", low)]),
        ("五、歸檔與索引", [("已歸檔到 GDrive", arc), ("缺欄位張數", mf)]),
        ("六、上週遺留", [("跨週未確認 pending", len(cr))]),
        ("七、老闆關心（缺 schema 提示）", [
            ("應收帳款 / 收款核對", "（M3 未啟用）"),
            ("應付帳款 / 票期預警", "（M3 未啟用）"),
            ("預算 vs 實際", "（M4 未啟用）"),
        ]),
    ]
    row = 4
    for title, items in sections:
        ws.cell(row=row, column=1, value=title).font = Font(bold=True, size=11, color="1F3864")
        ws.cell(row=row, column=1).fill = SUB
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3); row += 1
        for label, val in items:
            ws.cell(row=row, column=1, value=label).border = BORDER
            vc = ws.cell(row=row, column=2, value=val); vc.border = BORDER
            vc.alignment = Alignment(horizontal="right")
            if isinstance(val, int) and val > 0 and ("待" in label or "缺" in label or "低信心" in label or "跨週" in label):
                vc.fill = WARN
            row += 1
        row += 1

    # 收據明細表（同分頁下方）
    ws.cell(row=row, column=1, value="收據明細").font = Font(bold=True, size=12, color="1F3864"); row += 1
    h_list = ["#","ID","建立日","採購日","供應商","發票號碼","含稅金額","OCR","狀態","缺欄位"]
    for i, h_ in enumerate(h_list, 1):
        ws.cell(row=row, column=i, value=h_)
    hdr_row(ws, row, len(h_list)); row += 1
    for i, x in enumerate(st, 1):
        invoice = f"{(x.get('invoice_prefix') or '').strip()}{(x.get('invoice_number') or '').strip()}".strip()
        m_ = ",".join(missing(x)) or "—"
        ws.cell(row=row, column=1, value=i)
        ws.cell(row=row, column=2, value=x["id"])
        ws.cell(row=row, column=3, value=(x.get("created_at") or "")[:10])
        ws.cell(row=row, column=4, value=x.get("purchase_date") or "")
        ws.cell(row=row, column=5, value=x.get("supplier_name") or "")
        ws.cell(row=row, column=6, value=invoice)
        ws.cell(row=row, column=7, value=x.get("total_amount") or 0)
        ws.cell(row=row, column=8, value=round(x.get("ocr_confidence") or 0, 1))
        ws.cell(row=row, column=9, value=x.get("status") or "")
        ws.cell(row=row, column=10, value=m_)
        if (x.get("ocr_confidence") or 0) < 60: ws.cell(row=row, column=8).fill = WARN
        if x.get("status") == "pending": ws.cell(row=row, column=9).fill = WARN
        elif x.get("status") == "confirmed": ws.cell(row=row, column=9).fill = OK
        if m_ != "—": ws.cell(row=row, column=10).fill = WARN
        row += 1
    if not st:
        ws.cell(row=row, column=1, value="（本週無進件）").font = Font(italic=True, color="808080")
    widths(ws, [4, 6, 12, 12, 22, 16, 12, 9, 10, 22])

def build_items_all(ws, by_company):
    ws.title = "98_全公司品項明細"
    add_desc(ws, 9,
        "五家公司本週所有採購品項橫向展開（一個品項一列，含公司歸屬）",
        "跟各公司分頁對比：找出跨公司共用供應商 / 找出單價異常品項 → 議價或審計依據")
    h_list = ["公司","staging_id","採購日","供應商","品名","數量","單位","金額","會計科目"]
    for i, h_ in enumerate(h_list, 1):
        ws.cell(row=4, column=i, value=h_)
    hdr_row(ws, 4, len(h_list))
    r = 5
    for cname, sts in by_company.items():
        for s in sts:
            for it in sm.get_purchase_items(s["id"]):
                ws.cell(row=r, column=1, value=cname)
                ws.cell(row=r, column=2, value=s["id"])
                ws.cell(row=r, column=3, value=s.get("purchase_date") or "")
                ws.cell(row=r, column=4, value=s.get("supplier_name") or "")
                ws.cell(row=r, column=5, value=it.get("item_name") or "")
                ws.cell(row=r, column=6, value=it.get("quantity") or 0)
                ws.cell(row=r, column=7, value=it.get("unit") or "")
                ws.cell(row=r, column=8, value=it.get("amount") or 0)
                ws.cell(row=r, column=9, value=it.get("account_code") or "")
                r += 1
    if r == 5:
        ws.cell(row=r, column=1, value="（本週五家公司皆無品項記錄）").font = Font(italic=True, color="808080")
    widths(ws, [10, 8, 12, 22, 28, 8, 8, 12, 10])
    ws.freeze_panes = "A5"

def build_todo_all(ws, by_company_st, by_company_cr):
    ws.title = "99_全公司待辦"
    add_desc(ws, 7,
        "全公司本週待辦事項集合（缺欄位 / OCR 低信心 / 未歸檔 / 上週遺留）",
        "跨公司同類待辦放一起 → 小魚一張清單跑完全部公司，比 5 個分頁切換高效")
    h_list = ["公司","待辦類型","ID","建立日","供應商","金額","說明"]
    for i, h_ in enumerate(h_list, 1):
        ws.cell(row=4, column=i, value=h_)
    hdr_row(ws, 4, len(h_list))
    r = 5
    def add(cname, k, s, note):
        nonlocal r
        ws.cell(row=r, column=1, value=cname)
        ws.cell(row=r, column=2, value=k)
        ws.cell(row=r, column=3, value=s["id"])
        ws.cell(row=r, column=4, value=(s.get("created_at") or "")[:10])
        ws.cell(row=r, column=5, value=s.get("supplier_name") or "(未填)")
        ws.cell(row=r, column=6, value=s.get("total_amount") or 0)
        ws.cell(row=r, column=7, value=note)
        r += 1
    for cname, st in by_company_st.items():
        for s in st:
            m_ = missing(s)
            if m_: add(cname, "缺欄位", s, f"需補：{'、'.join(m_)}")
            if (s.get("ocr_confidence") or 0) < 60: add(cname, "OCR 低信心", s, "建議人工檢查")
            if not archived(s): add(cname, "未歸檔", s, "GDrive 路徑為空")
    for cname, cr in by_company_cr.items():
        for s in cr:
            add(cname, "上週遺留", s, f"自 {s.get('created_at','')[:10]} 起未確認")
    if r == 5:
        ws.cell(row=r, column=1, value="（本週全公司無待辦）").font = Font(italic=True, color="808080")
    widths(ws, [10, 12, 6, 12, 22, 12, 50])
    ws.freeze_panes = "A5"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("start", nargs="?"); p.add_argument("end", nargs="?")
    p.add_argument("--out-dir", default=os.path.join(GDRIVE_ROOT, "_週報彙總"))
    a = p.parse_args()
    today = date.today()
    e_d = date.fromisoformat(a.end) if a.end else today
    s_d = date.fromisoformat(a.start) if a.start else e_d - timedelta(days=6)
    s, e = s_d.isoformat(), e_d.isoformat()

    sm.init_db()
    conn = sm._get_conn()
    cos = [dict(r) for r in conn.execute("SELECT * FROM companies WHERE is_active=1 ORDER BY id").fetchall()]
    conn.close()

    print(f"=== 週報 {s} ~ {e} ｜ {len(cos)} 家 ｜ 單檔多分頁 ===")
    wb = Workbook()
    # 暫存 sheet (later remove)
    wb.remove(wb.active)

    summaries = []
    by_st = {}; by_cr = {}
    pages = []  # (sheet_name, meaning, compare)

    for idx, c in enumerate(cos, 2):  # 02 開始
        st = fetch_week(c["id"], s, e); cr = fetch_carryover(c["id"], s)
        by_st[c["short_name"]] = st; by_cr[c["short_name"]] = cr
        summaries.append({"c": c["short_name"], "n": len(st),
            "conf": sum(1 for x in st if x["status"]=="confirmed"),
            "pend": sum(1 for x in st if x["status"]=="pending"),
            "amt": sum((x.get("total_amount") or 0) for x in st),
            "mf": sum(1 for x in st if missing(x)),
            "low": sum(1 for x in st if (x.get("ocr_confidence") or 0) < 60),
            "cr": len(cr)})

    page_specs = [
        ("00_索引", "目錄頁，告訴讀者每個分頁的意義以及彼此比較可得到什麼", "—"),
        ("01_跨公司彙總", "五家公司本週橫向對比表（張數/確認/金額/待辦）", "首頁看完先掃這頁，2 秒判斷哪家是本週重點"),
    ]
    for i, c in enumerate(cos, 1):
        sn = f"{i+1:02d}_{c['short_name']}"
        page_specs.append((sn, f"{c['short_name']} 本週驗收摘要 + 收據明細 + 老闆關心面缺 schema 提示", f"跟 01 彙總對比{c['short_name']}的相對位置"))
    page_specs.append(("98_全公司品項明細", "本週全部品項橫向展開（含公司歸屬）", "跨公司找共用供應商或單價異常"))
    page_specs.append(("99_全公司待辦", "全公司本週待辦合併（缺欄位/低信心/未歸檔/上週遺留）", "小魚一張清單跑完全公司"))

    idx_ws = wb.create_sheet()
    build_index(idx_ws, s, e, len(cos), page_specs)
    cross_ws = wb.create_sheet()
    build_cross_company(cross_ws, summaries, s, e)
    for i, c in enumerate(cos, 1):
        ws = wb.create_sheet()
        build_company(ws, f"{i+1:02d}_{c['short_name']}", c, s, e, by_st[c["short_name"]], by_cr[c["short_name"]])
    items_ws = wb.create_sheet()
    build_items_all(items_ws, by_st)
    todo_ws = wb.create_sheet()
    build_todo_all(todo_ws, by_st, by_cr)

    os.makedirs(a.out_dir, exist_ok=True)
    fp = os.path.join(a.out_dir, f"小膳週報_{s}_{e}.xlsx")
    wb.save(fp)
    print(f"✅ {fp}")
    print(f"   分頁數：{len(wb.sheetnames)}")
    print(f"   分頁列表：{wb.sheetnames}")

if __name__ == "__main__":
    main()
