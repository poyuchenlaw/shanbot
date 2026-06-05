#!/usr/bin/env python3
"""shanbot 月報 — 單檔多分頁版（含索引頁），輸出 1 個 .xlsx"""
import os, sys, argparse
sys.path.insert(0, "/home/simon/shanbot")
import state_manager as sm
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import datetime

# 2026-06-05: 改用 gdrive_service 自動偵測（台中=/mnt/h/我的雲端硬碟/...，VPS rclone=/mnt/h/...）
# 硬編台中路徑致 5 月報表在 VPS 假上雲（rclone VFS 快取）
try:
    from services.gdrive_service import GDRIVE_LOCAL as GDRIVE_ROOT
except Exception:
    GDRIVE_ROOT = "/mnt/h/我的雲端硬碟/小魚資料/團膳公司資料"
HFILL = PatternFill("solid", start_color="4472C4")
HFONT = Font(bold=True, color="FFFFFF")
SUB = PatternFill("solid", start_color="D9E2F3")
DESC = PatternFill("solid", start_color="FFF2CC")
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

def add_desc(ws, ncols, meaning, compare):
    ws.cell(row=1, column=1, value=f"【本頁意義】{meaning}").font = Font(bold=True, size=12, color="1F3864")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    ws.cell(row=1, column=1).fill = DESC
    ws.cell(row=2, column=1, value=f"【對比價值】{compare}").font = Font(italic=True, color="404040")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
    ws.cell(row=2, column=1).fill = DESC
    ws.row_dimensions[1].height = 22; ws.row_dimensions[2].height = 20

def fetch_month(cid, ym):
    conn = sm._get_conn()
    rows = conn.execute("SELECT * FROM purchase_staging WHERE company_id=? AND year_month=? "
        "AND status IN ('confirmed','reported','exported') ORDER BY purchase_date",
        (cid, ym)).fetchall()
    conn.close(); return [dict(r) for r in rows]

def fetch_pending(cid, ym):
    conn = sm._get_conn()
    rows = conn.execute("SELECT * FROM purchase_staging WHERE company_id=? AND year_month=? "
        "AND status='pending' ORDER BY purchase_date",
        (cid, ym)).fetchall()
    conn.close(); return [dict(r) for r in rows]

def build_index(ws, ym, n_cos, pages, summaries):
    ws.title = "00_索引"
    ws.cell(row=1, column=1, value=f"小膳 BOT 月報 ｜ {ym}").font = Font(bold=True, size=18, color="FFFFFF")
    ws.cell(row=1, column=1).fill = INDEX_FILL
    ws.merge_cells("A1:D1"); ws.row_dimensions[1].height = 30
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")

    ws.cell(row=2, column=1, value=f"產出 {datetime.now():%Y-%m-%d %H:%M}  ｜  {n_cos} 家公司  ｜  Cymon 自動產出")
    ws.cell(row=2, column=1).font = Font(italic=True, color="595959")
    ws.merge_cells("A2:D2")

    ws.cell(row=4, column=1, value=f"{ym} 全公司速覽").font = Font(bold=True, size=12, color="1F3864")
    headers = ["公司", "已確認張數", "含稅總額", "待確認", "完成率"]
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=5, column=i, value=h); c.fill = HFILL; c.font = HFONT; c.border = BORDER
        c.alignment = Alignment(horizontal="center")
    r = 6
    for s in summaries:
        ratio = s["conf_n"] / (s["conf_n"] + s["pend_n"]) if (s["conf_n"] + s["pend_n"]) else 0
        ws.cell(row=r, column=1, value=s["c"]).border = BORDER
        ws.cell(row=r, column=2, value=s["conf_n"]).border = BORDER
        ws.cell(row=r, column=3, value=round(s["amt"])).border = BORDER
        ws.cell(row=r, column=4, value=s["pend_n"]).border = BORDER
        ws.cell(row=r, column=5, value=f"{ratio*100:.0f}%").border = BORDER
        if s["pend_n"] > s["conf_n"]: ws.cell(row=r, column=4).fill = WARN
        r += 1

    r += 2
    ws.cell(row=r, column=1, value="分頁目錄").font = Font(bold=True, size=12, color="1F3864"); r += 1
    h2 = ["#","分頁名稱","意義","對比價值"]
    for i, h in enumerate(h2, 1):
        c = ws.cell(row=r, column=i, value=h); c.fill = HFILL; c.font = HFONT; c.border = BORDER
    r += 1
    for j, (sn, mean, cmp) in enumerate(pages, 1):
        ws.cell(row=r, column=1, value=j).border = BORDER
        ws.cell(row=r, column=2, value=sn).border = BORDER
        ws.cell(row=r, column=3, value=mean).border = BORDER
        ws.cell(row=r, column=3).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=r, column=4, value=cmp).border = BORDER
        ws.cell(row=r, column=4).alignment = Alignment(wrap_text=True, vertical="top")
        r += 1

    r += 2
    ws.cell(row=r, column=1, value="跨分頁對比可以得到什麼").font = Font(bold=True, size=12, color="1F3864"); r += 1
    compares = [
        ("01 跨公司彙總 × 各公司分頁", "找出本月哪家進度落後 / 哪家金額異常 → 老闆要追的對象"),
        ("各公司『月度總覽』vs『憑證目錄』", "對帳 — 總覽金額應 = 憑證目錄逐筆加總，差額表示有遺漏"),
        ("98 全公司分類統計", "5 家合併看哪類食材成本最重 → 議價或菜單調整依據"),
        ("99 全公司供應商統計", "全集團對某供應商的總採購量 → 跨公司議價談判素材"),
        ("M3 schema 未啟用提示", "報表內無收款/AR/票期 → 確認下階段補強優先級"),
    ]
    for k, v in compares:
        ws.cell(row=r, column=1, value=f"• {k}").font = Font(bold=True)
        ws.cell(row=r, column=1).alignment = Alignment(vertical="top")
        c2 = ws.cell(row=r, column=2, value=v); c2.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
        ws.row_dimensions[r].height = 28
        r += 1

    widths(ws, [10, 24, 40, 50])

def build_cross(ws, summaries, ym):
    ws.title = "01_跨公司彙總"
    add_desc(ws, 8, f"{ym} 五家公司月度橫向對比",
        "首頁看完掃這頁找老闆要追的對象")
    headers = ["公司","已確認張數","含稅總額","未稅","稅額","待確認","發票數","收據數"]
    for i, h in enumerate(headers, 1):
        ws.cell(row=4, column=i, value=h)
    hdr_row(ws, 4, len(headers))
    tot = [0]*7
    for s in summaries:
        ws.append([s["c"], s["conf_n"], round(s["amt"]), round(s["amt"]-s["tax"]),
                   round(s["tax"]), s["pend_n"], s["inv"], s["rec"]])
        for i, v in enumerate([s["conf_n"], round(s["amt"]), round(s["amt"]-s["tax"]),
                                round(s["tax"]), s["pend_n"], s["inv"], s["rec"]]):
            tot[i] += v
    ws.append(["合計"] + tot); rm = ws.max_row
    for c in range(1, 9):
        ws.cell(row=rm, column=c).font = Font(bold=True); ws.cell(row=rm, column=c).fill = SUB
    widths(ws, [12, 12, 14, 12, 10, 10, 10, 10])
    ws.freeze_panes = "A5"

def build_company(ws, sn, c, ym, confirmed, pending):
    ws.title = sn
    add_desc(ws, 7, f"{c['short_name']} {ym} 月度總覽 + 全部憑證",
        f"跟 01 彙總對比{c['short_name']}的相對位置；下方老闆關心面提示")
    sub = sum((x.get("subtotal") or 0) for x in confirmed)
    tax = sum((x.get("tax_amount") or 0) for x in confirmed)
    tot = sum((x.get("total_amount") or 0) for x in confirmed)
    inv = sum(1 for x in confirmed if x.get("invoice_number"))
    rec = len(confirmed) - inv

    ws.cell(row=4, column=1, value="一、月度總覽").font = Font(bold=True, size=11, color="1F3864")
    ws.cell(row=4, column=1).fill = SUB
    ws.merge_cells("A4:C4")
    items = [("已確認張數", len(confirmed)), ("含稅總額", f"{tot:,.0f}"),
             ("未稅小計", f"{sub:,.0f}"), ("進項稅額", f"{tax:,.0f}"),
             ("發票數", inv), ("收據/手寫", rec), ("待確認張數", len(pending))]
    r = 5
    for lab, val in items:
        ws.cell(row=r, column=1, value=lab).border = BORDER
        ws.cell(row=r, column=2, value=val).border = BORDER
        ws.cell(row=r, column=2).alignment = Alignment(horizontal="right")
        r += 1

    r += 1
    ws.cell(row=r, column=1, value="二、老闆關心（缺 schema）").font = Font(bold=True, size=11, color="1F3864")
    ws.cell(row=r, column=1).fill = SUB
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=3); r += 1
    for lab, val in [("應收 / 收款核對", "M3 未啟用"), ("應付 / 票期", "M3 未啟用"), ("預算 vs 實際", "M4 未啟用")]:
        ws.cell(row=r, column=1, value=lab).border = BORDER
        ws.cell(row=r, column=2, value=val).border = BORDER
        ws.cell(row=r, column=2).fill = WARN
        r += 1

    r += 2
    ws.cell(row=r, column=1, value="憑證目錄").font = Font(bold=True, size=12, color="1F3864"); r += 1
    h_list = ["#","日期","供應商","發票號碼","金額","稅額","狀態"]
    for i, h_ in enumerate(h_list, 1):
        ws.cell(row=r, column=i, value=h_)
    hdr_row(ws, r, len(h_list)); r += 1
    for i, x in enumerate(confirmed + pending, 1):
        invoice = f"{(x.get('invoice_prefix') or '').strip()}{(x.get('invoice_number') or '').strip()}".strip()
        ws.cell(row=r, column=1, value=i); ws.cell(row=r, column=2, value=x.get("purchase_date") or "")
        ws.cell(row=r, column=3, value=x.get("supplier_name") or ""); ws.cell(row=r, column=4, value=invoice or "(無)")
        ws.cell(row=r, column=5, value=x.get("total_amount") or 0); ws.cell(row=r, column=6, value=x.get("tax_amount") or 0)
        ws.cell(row=r, column=7, value=x.get("status") or "")
        if x.get("status") == "pending": ws.cell(row=r, column=7).fill = WARN
        elif x.get("status") == "confirmed": ws.cell(row=r, column=7).fill = OK
        r += 1
    if not (confirmed or pending):
        ws.cell(row=r, column=1, value="（本月無資料）").font = Font(italic=True, color="808080")
    widths(ws, [4, 12, 22, 16, 12, 10, 10])

def build_category(ws, by_company, ym):
    ws.title = "98_全公司分類統計"
    add_desc(ws, 5, f"{ym} 五家公司合併按品項分類統計",
        "找出本月哪類食材成本最重 → 議價/菜單調整依據")
    h_list = ["分類","會計科目","筆數","金額","佔比"]
    for i, h_ in enumerate(h_list, 1):
        ws.cell(row=4, column=i, value=h_)
    hdr_row(ws, 4, len(h_list))
    agg = {}
    for sts in by_company.values():
        for s in sts:
            for it in sm.get_purchase_items(s["id"]):
                cat = it.get("category") or "其他"
                a = agg.setdefault(cat, {"n": 0, "amt": 0.0, "code": it.get("account_code") or ""})
                a["n"] += 1; a["amt"] += it.get("amount") or 0
    total = sum(a["amt"] for a in agg.values()) or 1
    r = 5
    for cat, a in sorted(agg.items(), key=lambda x: -x[1]["amt"]):
        ws.cell(row=r, column=1, value=cat); ws.cell(row=r, column=2, value=a["code"])
        ws.cell(row=r, column=3, value=a["n"]); ws.cell(row=r, column=4, value=round(a["amt"]))
        ws.cell(row=r, column=5, value=f"{a['amt']/total*100:.1f}%"); r += 1
    if r == 5:
        ws.cell(row=r, column=1, value="（無品項資料）").font = Font(italic=True, color="808080")
    widths(ws, [16, 12, 8, 14, 10])
    ws.freeze_panes = "A5"

def build_supplier(ws, by_company, ym):
    ws.title = "99_全公司供應商統計"
    add_desc(ws, 5, f"{ym} 五家公司合併按供應商統計",
        "跨公司全集團對某供應商總採購量 → 議價談判素材")
    h_list = ["供應商","出現公司","張數","含稅金額","佔比"]
    for i, h_ in enumerate(h_list, 1):
        ws.cell(row=4, column=i, value=h_)
    hdr_row(ws, 4, len(h_list))
    agg = {}
    for cname, sts in by_company.items():
        for s in sts:
            nm = s.get("supplier_name") or "（未填）"
            a = agg.setdefault(nm, {"n": 0, "amt": 0.0, "cos": set()})
            a["n"] += 1; a["amt"] += s.get("total_amount") or 0
            a["cos"].add(cname)
    total = sum(a["amt"] for a in agg.values()) or 1
    r = 5
    for nm, a in sorted(agg.items(), key=lambda x: -x[1]["amt"]):
        ws.cell(row=r, column=1, value=nm); ws.cell(row=r, column=2, value="、".join(sorted(a["cos"])))
        ws.cell(row=r, column=3, value=a["n"]); ws.cell(row=r, column=4, value=round(a["amt"]))
        ws.cell(row=r, column=5, value=f"{a['amt']/total*100:.1f}%"); r += 1
    if r == 5:
        ws.cell(row=r, column=1, value="（無供應商資料）").font = Font(italic=True, color="808080")
    widths(ws, [22, 28, 8, 14, 10])
    ws.freeze_panes = "A5"

def run_month(ym, out_dir):
    sm.init_db()
    conn = sm._get_conn()
    cos = [dict(r) for r in conn.execute("SELECT * FROM companies WHERE is_active=1 ORDER BY id").fetchall()]
    conn.close()

    print(f"=== 月報 {ym} ｜ {len(cos)} 家 ｜ 單檔多分頁 ===")
    wb = Workbook(); wb.remove(wb.active)
    summaries = []
    by_confirmed = {}
    for c in cos:
        conf = fetch_month(c["id"], ym); pend = fetch_pending(c["id"], ym)
        by_confirmed[c["short_name"]] = conf
        amt = sum((x.get("total_amount") or 0) for x in conf)
        tax = sum((x.get("tax_amount") or 0) for x in conf)
        inv = sum(1 for x in conf if x.get("invoice_number"))
        summaries.append({"c": c["short_name"], "conf_n": len(conf), "pend_n": len(pend),
                          "amt": amt, "tax": tax, "inv": inv, "rec": len(conf) - inv,
                          "conf_data": conf, "pend_data": pend})

    pages = [("00_索引","目錄頁","—"), ("01_跨公司彙總","五家月度對比","掃這頁找老闆要追的對象")]
    for i, c in enumerate(cos, 1):
        pages.append((f"{i+1:02d}_{c['short_name']}",
                      f"{c['short_name']} {ym} 月度總覽 + 憑證目錄 + 老闆關心面",
                      f"跟 01 對比 {c['short_name']} 的相對位置"))
    pages.append(("98_全公司分類統計", f"{ym} 五家合併品項分類", "看哪類食材最重→議價/菜單依據"))
    pages.append(("99_全公司供應商統計", f"{ym} 五家合併供應商", "跨公司議價談判素材"))

    build_index(wb.create_sheet(), ym, len(cos), pages, summaries)
    build_cross(wb.create_sheet(), summaries, ym)
    for i, (c, s) in enumerate(zip(cos, summaries), 1):
        build_company(wb.create_sheet(), f"{i+1:02d}_{c['short_name']}", c, ym,
                      s["conf_data"], s["pend_data"])
    build_category(wb.create_sheet(), by_confirmed, ym)
    build_supplier(wb.create_sheet(), by_confirmed, ym)

    os.makedirs(out_dir, exist_ok=True)
    fp = os.path.join(out_dir, f"小膳月報_{ym}.xlsx")
    wb.save(fp)
    print(f"✅ {fp}")
    print(f"   分頁數 {len(wb.sheetnames)}：{wb.sheetnames}")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("year_month")
    p.add_argument("--out-dir", default=os.path.join(GDRIVE_ROOT, "_月報彙總"))
    a = p.parse_args()
    run_month(a.year_month, a.out_dir)
