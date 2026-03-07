"""Postback 路由分發 — 六宮格選單 + 子選單動作"""

import logging
import os
from urllib.parse import parse_qs

import state_manager as sm
from services import flex_builder as fb

logger = logging.getLogger("shanbot.postback")


async def handle_postback(line_service, data_str: str, group_id: str,
                          user_id: str, reply_token: str):
    """主路由：解析 postback data → 分發到子處理器"""
    if not line_service:
        logger.warning("line_service is None, skipping postback")
        return

    params = _parse_data(data_str)

    menu = params.get("menu")
    action = params.get("action")

    # === 六宮格主選單 ===
    if menu:
        flex = _handle_menu(menu)
        if flex:
            line_service.reply_flex(reply_token, _alt_text(menu), flex)
            return

    # === 子動作 ===
    if action == "report":
        await _handle_report(line_service, params, group_id, reply_token)
    elif action == "purchase":
        await _handle_purchase(line_service, params, group_id, reply_token)
    elif action == "menu":
        await _handle_menu_action(line_service, params, group_id, user_id, reply_token)
    elif action == "export":
        _handle_export_select(line_service, params, reply_token)
    elif action == "do_export":
        await _handle_do_export(line_service, params, group_id, reply_token)
    elif action == "confirm":
        await _handle_quick_confirm(line_service, params, group_id, reply_token)
    elif action == "edit":
        _handle_quick_edit(line_service, params, group_id, reply_token)
    elif action == "discard":
        _handle_quick_discard(line_service, params, reply_token)
    elif action == "finance_docs":
        await _handle_finance_docs(line_service, params, group_id, reply_token)
    elif action == "gen_report":
        _handle_gen_report_select(line_service, params, reply_token)
    elif action == "do_gen_report":
        await _handle_do_gen_report(line_service, params, group_id, reply_token)
    elif action == "file_confirm":
        _handle_file_confirm(line_service, params, reply_token)
    elif action == "file_reclassify":
        _handle_file_reclassify(line_service, params, reply_token)
    elif action == "file_set_category":
        _handle_file_set_category(line_service, params, reply_token)
    elif action == "tax_deduction_stats":
        await _handle_tax_deduction_stats(line_service, params, group_id, reply_token)
    elif action == "menu_photo_upload":
        _handle_menu_photo_upload(line_service, group_id, user_id, reply_token)
    elif action == "menu_photo_regenerate":
        _handle_menu_photo_upload(line_service, group_id, user_id, reply_token)
    else:
        logger.warning(f"Unknown postback: {data_str}")


# === 六宮格主選單 ===

def _handle_menu(menu: str) -> dict | None:
    if menu == "camera":
        return fb.build_camera_menu()
    elif menu == "finance":
        return fb.build_finance_menu()
    elif menu == "finance_upload":
        return fb.build_finance_upload_menu()
    elif menu == "purchase":
        pending_count = len(sm.get_pending_stagings())
        return fb.build_purchase_menu(pending_count)
    elif menu == "menu_plan":
        return fb.build_menu_plan_menu()
    elif menu == "export":
        return fb.build_export_menu()
    elif menu == "reports":
        return fb.build_reports_menu()
    elif menu == "guide":
        return fb.build_guide_menu()
    return None


# === 財務報表 ===

async def _handle_report(line_service, params: dict, group_id: str, reply_token: str):
    report_type = params.get("type", "")
    period = params.get("period", "month")
    ym = params.get("ym", "")

    from datetime import datetime
    if not ym:
        ym = datetime.now().strftime("%Y-%m")

    if report_type == "financial_index":
        await _gen_financial_index(line_service, reply_token)
    elif report_type == "expense":
        await _gen_expense_report(line_service, ym, period, reply_token)
    elif report_type == "income":
        await _gen_income_report(line_service, ym, period, reply_token)
    else:
        line_service.reply(reply_token, f"未知報表類型：{report_type}")


async def _gen_financial_index(line_service, reply_token: str):
    """財報索引 — 累計統計"""
    from datetime import datetime
    now = datetime.now()
    ym = now.strftime("%Y-%m")
    stats = sm.get_staging_stats(ym)
    flex = fb.build_stats_flex(ym, stats)
    line_service.reply_flex(reply_token, f"📊 {ym} 財報索引", flex)


async def _gen_expense_report(line_service, ym: str, period: str, reply_token: str):
    """費用一覽"""
    if period == "bimonth":
        from datetime import datetime
        now = datetime.now()
        m = now.month
        start_m = m - 1 if m % 2 == 0 else m
        end_m = start_m + 1
        months = [f"{now.year}-{start_m:02d}", f"{now.year}-{end_m:02d}"]
    else:
        months = [ym]

    lines = [f"💰 費用一覽（{', '.join(months)}）", ""]
    grand_total = 0

    for month in months:
        stagings = sm.get_stagings_by_month(month)
        if not stagings:
            lines.append(f"  {month}：無資料")
            continue

        cat_totals = {}
        for s in stagings:
            items = sm.get_purchase_items(s["id"])
            for item in items:
                cat = item.get("category", "其他")
                cat_totals[cat] = cat_totals.get(cat, 0) + (item.get("amount", 0) or 0)

        month_total = sum(cat_totals.values())
        grand_total += month_total
        lines.append(f"📅 {month}（${month_total:,.0f}）")
        for cat, amt in sorted(cat_totals.items(), key=lambda x: -x[1]):
            pct = (amt / month_total * 100) if month_total else 0
            lines.append(f"  • {cat}：${amt:,.0f}（{pct:.0f}%）")
        lines.append("")

    lines.append(f"━━━━━━━━━━")
    lines.append(f"合計：${grand_total:,.0f}")

    line_service.reply(reply_token, "\n".join(lines))


async def _gen_income_report(line_service, ym: str, period: str, reply_token: str):
    """收入一覽"""
    income_data = sm.get_income_summary(ym)
    if not income_data:
        line_service.reply(reply_token,
                           f"📈 {ym} 收入一覽\n\n尚未建立收入資料。\n"
                           "請使用「新增收入 金額 說明」記錄收入。")
        return

    lines = [f"📈 {ym} 收入一覽", ""]
    total = 0
    for entry in income_data:
        amt = entry.get("amount", 0)
        total += amt
        lines.append(f"  • {entry.get('description', '')}：${amt:,.0f}")
    lines.append(f"\n合計：${total:,.0f}")
    line_service.reply(reply_token, "\n".join(lines))


# === 採購管理 ===

async def _handle_purchase(line_service, params: dict, group_id: str, reply_token: str):
    cmd = params.get("cmd", "")

    if cmd == "pending":
        pendings = sm.get_pending_stagings(group_id)
        flex = fb.build_pending_list_flex(pendings)
        line_service.reply_flex(reply_token, f"📝 待處理（{len(pendings)} 筆）", flex)

    elif cmd == "market":
        try:
            from services.market_service import get_market_summary
            from datetime import date
            summary = get_market_summary(date.today())
            if summary:
                lines = ["📊 今日農產品行情", ""]
                for cat, items in summary.items():
                    lines.append(f"【{cat}】")
                    for item in items[:5]:
                        name = item.get("品名", item.get("name", ""))
                        price = item.get("平均價", item.get("avg_price", 0))
                        lines.append(f"  {name}：${price}")
                    lines.append("")
                line_service.reply(reply_token, "\n".join(lines))
            else:
                line_service.reply(reply_token, "暫無今日行情資料，請稍後再試")
        except Exception as e:
            logger.error(f"Market price error: {e}")
            line_service.reply(reply_token, "行情查詢暫時無法使用")

    elif cmd == "suppliers":
        suppliers = sm.get_all_suppliers()
        flex = fb.build_supplier_list_flex(suppliers)
        line_service.reply_flex(reply_token, f"🏪 供應商（{len(suppliers)} 家）", flex)

    elif cmd == "price_compare":
        await _gen_price_compare(line_service, reply_token)

    else:
        line_service.reply(reply_token, "未知的採購指令")


async def _gen_price_compare(line_service, reply_token: str):
    """生成食材價格對照表"""
    comparisons = sm.get_price_comparisons()
    if not comparisons:
        line_service.reply(reply_token, "📦 食材價格對照表\n\n尚無足夠的進貨與市場資料可比較。")
        return
    flex = fb.build_price_compare_flex(comparisons)
    line_service.reply_flex(reply_token, "📦 食材價格對照表", flex)


# === 菜單企劃 ===

async def _handle_menu_action(line_service, params: dict, group_id: str,
                              user_id: str, reply_token: str):
    cmd = params.get("cmd", "")

    if cmd == "view_current":
        await _view_current_menu(line_service, reply_token)
    elif cmd == "edit":
        sm.set_state(group_id, "waiting_menu_edit", {})
        line_service.reply(reply_token,
                           "✏️ 菜單編輯模式\n\n"
                           "請輸入菜單內容，格式：\n"
                           "  週一午：紅燒肉、炒青菜、蛋花湯\n"
                           "  週二午：三杯雞、燙空心菜、味噌湯\n\n"
                           "輸入「完成菜單」結束編輯")
    elif cmd == "gen_image":
        sm.set_state(group_id, "waiting_dish_name", {})
        line_service.reply(reply_token,
                           "🎨 菜色圖片生成\n\n"
                           "請輸入一道菜名（例如：糖醋排骨）：")
    elif cmd == "cost_calc":
        sm.set_state(group_id, "waiting_cost_input", {})
        line_service.reply(reply_token,
                           "🧮 食材成本試算\n\n"
                           "請輸入菜名或食材清單：\n"
                           "例如：三杯雞\n"
                           "或：雞腿 2斤、九層塔 0.5斤、麻油 0.2瓶")
    else:
        line_service.reply(reply_token, "未知的菜單指令")


async def _view_current_menu(line_service, reply_token: str):
    """查看本月菜單"""
    from datetime import datetime
    now = datetime.now()
    ym = now.strftime("%Y-%m")

    menus = sm.get_menu_schedule(ym)
    if not menus:
        line_service.reply(reply_token,
                           f"🍽️ {ym} 菜單\n\n"
                           "尚未建立本月菜單。\n"
                           "點「編輯菜單」開始規劃！")
        return

    lines = [f"🍽️ {ym} 菜單", ""]
    for m in menus:
        recipe_name = m.get("recipe_name", m.get("slot", ""))
        sdate = m.get("schedule_date", "")
        lines.append(f"  {sdate} | {m.get('meal_type', '')} | {recipe_name}")

    line_service.reply(reply_token, "\n".join(lines))


# === 匯出中心 ===

def _handle_export_select(line_service, params: dict, reply_token: str):
    """顯示期間選擇器"""
    export_type = params.get("type", "monthly")
    flex = fb.build_export_period_picker(export_type)
    line_service.reply_flex(reply_token, f"📤 選擇匯出期間", flex)


async def _handle_do_export(line_service, params: dict, group_id: str, reply_token: str):
    """實際執行匯出"""
    export_type = params.get("type", "")
    period = params.get("period", "")

    if not period:
        line_service.reply(reply_token, "請指定匯出期間")
        return

    try:
        path = None

        if export_type == "monthly":
            from services.report_service import generate_monthly_report
            path = generate_monthly_report(period)
            if path:
                gdrive_rel = await _upload_export_to_gdrive(path, "monthly", period)
                gdrive_note = f"\n☁️ 已同步：{gdrive_rel}" if gdrive_rel else ""
                line_service.reply(reply_token, f"✅ 月報表已生成\n📁 {path}{gdrive_note}")
            else:
                line_service.reply(reply_token, f"⚠️ {period} 無可匯出的資料")

        elif export_type == "annual":
            from services.report_service import generate_annual_report
            year = period[:4]
            path = generate_annual_report(year)
            if path:
                gdrive_rel = await _upload_export_to_gdrive(path, "annual", year)
                gdrive_note = f"\n☁️ 已同步：{gdrive_rel}" if gdrive_rel else ""
                line_service.reply(reply_token, f"✅ 年報表已生成\n📁 {path}{gdrive_note}")
            else:
                line_service.reply(reply_token, f"⚠️ {year} 年無可匯出的資料")

        elif export_type == "mof_txt":
            from services.tax_export_service import validate_before_export, export_mof_txt
            ok, errors = validate_before_export(period)
            if not ok:
                line_service.reply(reply_token,
                                   "⚠️ 匯出前驗證未通過：\n" +
                                   "\n".join(f"  ❌ {e}" for e in errors))
                return
            output_dir = f"/home/simon/shanbot/data/exports/{period}"
            path = export_mof_txt(period, output_dir)
            if path:
                gdrive_rel = await _upload_export_to_gdrive(path, "mof_txt", period)
                gdrive_note = f"\n☁️ 已同步：{gdrive_rel}" if gdrive_rel else ""
                line_service.reply(reply_token, f"✅ 稅務申報檔已生成\n📁 {path}{gdrive_note}")
            else:
                line_service.reply(reply_token, "⚠️ 匯出失敗")

        elif export_type == "accounting":
            from services.tax_export_service import export_winton_excel
            output_dir = f"/home/simon/shanbot/data/exports/{period}"
            path = export_winton_excel(period, output_dir)
            if path:
                gdrive_rel = await _upload_export_to_gdrive(path, "accounting", period)
                gdrive_note = f"\n☁️ 已同步：{gdrive_rel}" if gdrive_rel else ""
                line_service.reply(reply_token, f"✅ 會計匯出已生成\n📁 {path}{gdrive_note}")
            else:
                line_service.reply(reply_token, "⚠️ 匯出失敗")

        elif export_type == "handler_cert":
            from services.tax_export_service import export_handler_cert
            output_dir = f"/home/simon/shanbot/data/exports/{period}"
            path = export_handler_cert(period, output_dir)
            if path:
                gdrive_rel = await _upload_export_to_gdrive(path, "handler_cert", period)
                gdrive_note = f"\n☁️ 已同步：{gdrive_rel}" if gdrive_rel else ""
                line_service.reply(reply_token, f"✅ 經手人憑證已生成\n📁 {path}{gdrive_note}")
            else:
                line_service.reply(reply_token, "⚠️ 無需經手人憑證的記錄")

        else:
            line_service.reply(reply_token, f"未知的匯出類型：{export_type}")

    except Exception as e:
        logger.error(f"Export error: {e}", exc_info=True)
        line_service.reply(reply_token, f"匯出發生錯誤：{str(e)}")


async def _upload_export_to_gdrive(local_path: str, export_type: str, period: str) -> str | None:
    """上傳匯出檔案到 GDrive，回傳相對路徑"""
    try:
        from services.gdrive_service import upload_export
        return await upload_export(local_path, export_type, period)
    except Exception as e:
        logger.warning(f"GDrive export upload skipped: {e}")
        return None


# === 快速確認/修改/捨棄 (from pending list flex) ===

async def _handle_quick_confirm(line_service, params: dict, group_id: str, reply_token: str):
    staging_id = int(params.get("id", 0))
    if not staging_id:
        line_service.reply(reply_token, "無效的記錄編號")
        return
    staging = sm.get_staging(staging_id)
    if not staging:
        line_service.reply(reply_token, f"找不到記錄 #{staging_id}")
        return
    if staging["status"] != "pending":
        line_service.reply(reply_token, f"記錄 #{staging_id} 已是 {staging['status']} 狀態")
        return

    # 檢查經手人
    supplier = sm.get_supplier(supplier_id=staging.get("supplier_id"))
    if supplier and not supplier.get("has_uniform_invoice") and not staging.get("handler_name"):
        sm.set_state(group_id, "waiting_handler", {"staging_id": staging_id})
        line_service.reply(reply_token,
                           f"記錄 #{staging_id} 需填寫經手人姓名：")
        return

    sm.confirm_staging(staging_id)
    items = sm.get_purchase_items(staging_id)
    for item in items:
        if item.get("ingredient_id"):
            sm.update_ingredient_price(item["ingredient_id"], item["unit_price"])

    # GDrive 正式歸檔（共用 command_handler 的輔助函數）
    from handlers.command_handler import _do_archive
    gdrive_note = await _do_archive(staging_id, staging)

    line_service.reply(reply_token,
                       f"✅ #{staging_id} 已確認\n"
                       f"供應商：{staging['supplier_name']}\n"
                       f"金額：${staging['total_amount']:,.0f}"
                       f"{gdrive_note}")


def _handle_quick_edit(line_service, params: dict, group_id: str, reply_token: str):
    staging_id = int(params.get("id", 0))
    staging = sm.get_staging(staging_id)
    if not staging:
        line_service.reply(reply_token, f"找不到記錄 #{staging_id}")
        return
    sm.set_state(group_id, "waiting_edit", {"staging_id": staging_id})
    line_service.reply(reply_token,
                       f"✏️ 修改模式 #{staging_id}\n"
                       "格式：供應商=名稱 / 日期=YYYY-MM-DD / 總額=金額\n"
                       "輸入「完成修改」結束")


def _handle_quick_discard(line_service, params: dict, reply_token: str):
    staging_id = int(params.get("id", 0))
    staging = sm.get_staging(staging_id)
    if not staging:
        line_service.reply(reply_token, f"找不到記錄 #{staging_id}")
        return
    sm.update_purchase_staging(staging_id, status="discarded")
    line_service.reply(reply_token, f"❌ #{staging_id} 已捨棄")


# === 財務文件管理 ===

async def _handle_finance_docs(line_service, params: dict, group_id: str, reply_token: str):
    """處理財務文件相關動作"""
    cmd = params.get("cmd", "")
    from datetime import datetime
    ym = datetime.now().strftime("%Y-%m")

    if cmd == "list":
        docs = sm.get_financial_documents(year_month=ym)
        flex = fb.build_finance_doc_list_flex(docs, ym)
        line_service.reply_flex(reply_token, f"📂 {ym} 文件清單", flex)

    elif cmd == "search":
        sm.set_state(group_id, "waiting_finance_search", {})
        line_service.reply(reply_token,
                           "🔍 搜尋財務文件\n\n"
                           "請輸入關鍵字（檔名或分類）：")

    elif cmd == "confirm_month":
        docs = sm.get_financial_documents(year_month=ym)
        confirmed_count = 0
        for doc in docs:
            if doc.get("status") != "confirmed":
                sm.update_financial_document(
                    doc["id"], status="confirmed",
                    confirmed_at=datetime.now().isoformat(),
                )
                confirmed_count += 1
        total = len(docs)
        line_service.reply(reply_token,
                           f"✅ {ym} 財務資料確認完成\n"
                           f"本月共 {total} 件文件\n"
                           f"本次確認 {confirmed_count} 件")

    elif cmd == "summary":
        summary = sm.get_financial_doc_summary(ym)
        flex = fb.build_finance_doc_summary_flex(summary)
        line_service.reply_flex(reply_token, f"📊 {ym} 文件統計", flex)

    else:
        line_service.reply(reply_token, "未知的文件指令")


def _handle_file_confirm(line_service, params: dict, reply_token: str):
    """確認文件分類"""
    doc_id = int(params.get("id", 0))
    if not doc_id:
        line_service.reply(reply_token, "無效的文件編號")
        return
    from datetime import datetime
    sm.update_financial_document(
        doc_id, status="confirmed",
        confirmed_at=datetime.now().isoformat(),
    )
    line_service.reply(reply_token, f"✅ 文件 #{doc_id} 分類已確認")


def _handle_file_reclassify(line_service, params: dict, reply_token: str):
    """顯示分類選擇 Flex"""
    doc_id = int(params.get("id", 0))
    if not doc_id:
        line_service.reply(reply_token, "無效的文件編號")
        return
    flex = fb.build_file_reclassify_flex(doc_id)
    line_service.reply_flex(reply_token, f"🏷️ 修改分類 #{doc_id}", flex)


def _handle_file_set_category(line_service, params: dict, reply_token: str):
    """設定文件分類"""
    doc_id = int(params.get("id", 0))
    category = params.get("cat", "")
    if not doc_id or not category:
        line_service.reply(reply_token, "無效的操作")
        return
    category_labels = {
        "revenue": "收入循環", "expenditure": "支出循環",
        "payroll": "人力資源循環", "production": "生產循環",
        "financing": "融資循環", "investment": "投資循環",
        "fixed_asset": "固定資產循環", "general": "一般循環",
    }
    label = category_labels.get(category, category)
    sm.update_financial_document(doc_id, doc_category=category)
    line_service.reply(reply_token, f"🏷️ 文件 #{doc_id} 已改為：{label}")


# === 四大報表生成 ===

def _handle_gen_report_select(line_service, params: dict, reply_token: str):
    """顯示報表期間選擇"""
    report_type = params.get("type", "")
    flex = fb.build_report_period_picker(report_type)
    line_service.reply_flex(reply_token, "📊 選擇報表期間", flex)


async def _handle_do_gen_report(line_service, params: dict, group_id: str, reply_token: str):
    """實際生成四大報表"""
    report_type = params.get("type", "")
    period = params.get("period", "")

    if not period:
        line_service.reply(reply_token, "請指定報表期間")
        return

    type_labels = {
        "balance_sheet": "資產負債表",
        "income_statement": "損益表",
        "cash_flow": "現金流量表",
        "equity_changes": "權益變動表",
    }
    label = type_labels.get(report_type, report_type)

    try:
        from services.financial_report_service import (
            generate_balance_sheet, generate_income_statement,
            generate_cash_flow, generate_equity_changes,
        )

        generators = {
            "balance_sheet": generate_balance_sheet,
            "income_statement": generate_income_statement,
            "cash_flow": generate_cash_flow,
            "equity_changes": generate_equity_changes,
        }

        gen_func = generators.get(report_type)
        if not gen_func:
            line_service.reply(reply_token, f"未知的報表類型：{report_type}")
            return

        path = gen_func(period)
        if path:
            # 上傳到 GDrive 財務報表資料夾
            gdrive_note = ""
            try:
                from services.gdrive_service import upload_financial_doc
                gdrive_rel = await upload_financial_doc(
                    path, period[:7], "report", os.path.basename(path)
                )
                if gdrive_rel:
                    gdrive_note = f"\n☁️ 已同步：{gdrive_rel}"
            except Exception as e:
                logger.warning(f"GDrive upload skipped: {e}")

            line_service.reply(reply_token,
                               f"✅ {label}已生成\n"
                               f"📅 期間：{period}\n"
                               f"📁 {path}{gdrive_note}")
        else:
            line_service.reply(reply_token,
                               f"⚠️ {period} 無足夠資料生成{label}")

    except Exception as e:
        logger.error(f"Report generation error: {e}", exc_info=True)
        line_service.reply(reply_token, f"生成{label}時發生錯誤：{str(e)}")


# === 扣抵分析 ===

async def _handle_tax_deduction_stats(line_service, params: dict, group_id: str, reply_token: str):
    """顯示扣抵分析 Flex"""
    from datetime import datetime
    ym = params.get("ym", datetime.now().strftime("%Y-%m"))
    stats = sm.get_deduction_stats(year_month=ym)
    if stats.get("total_count", 0) == 0:
        line_service.reply(reply_token, f"🧾 {ym} 扣抵分析\n\n尚無已確認的進項記錄。")
        return
    flex = fb.build_tax_deduction_summary_flex(stats)
    line_service.reply_flex(reply_token, f"🧾 {ym} 扣抵分析", flex)


# === 菜單照片上傳 ===

def _handle_menu_photo_upload(line_service, group_id: str, user_id: str, reply_token: str):
    """設定等待菜色照片上傳狀態"""
    sm.set_state(group_id, "waiting_menu_photo", {"user_id": user_id})
    line_service.reply(reply_token,
                       "📸 菜色行銷海報\n\n"
                       "請上傳一張菜色實拍照片，小膳會：\n"
                       "1️⃣ AI 分析菜色（菜名、食材、擺盤）\n"
                       "2️⃣ 生成棚拍質感增強圖\n"
                       "3️⃣ 撰寫行銷文案 + hashtags\n\n"
                       "📷 請直接傳照片給我！")


# === 工具函數 ===

def _parse_data(data_str: str) -> dict:
    """解析 postback data 字串為 dict"""
    parsed = parse_qs(data_str, keep_blank_values=True)
    return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}


def _alt_text(menu: str) -> str:
    labels = {
        "camera": "📸 拍照記帳",
        "finance": "📊 財務報表",
        "finance_upload": "📁 財務資料提供和確認",
        "purchase": "🛒 採購管理",
        "menu_plan": "🍽️ 菜單企劃",
        "export": "📤 匯出中心",
        "reports": "📊 報表生成",
        "guide": "❓ 使用說明",
    }
    return labels.get(menu, "小膳選單")
