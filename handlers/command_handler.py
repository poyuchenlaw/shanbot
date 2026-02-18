"""小膳 Bot 主命令路由器"""

import json
import logging
import re
from typing import Optional

import state_manager as sm

logger = logging.getLogger("shanbot.command")


async def handle_text(line_service, text: str, group_id: str,
                      user_id: str, user_name: str, reply_token: str) -> Optional[str]:
    """主路由：文字訊息 → 對應處理"""

    # 1. 檢查對話狀態（state machine）
    state, state_data = sm.get_state(group_id)

    if state == "waiting_confirm":
        return await _handle_confirm_response(text, group_id, state_data)

    if state == "waiting_supplier":
        return await _handle_supplier_response(text, group_id, state_data)

    if state == "waiting_handler":
        return await _handle_handler_response(text, group_id, state_data)

    if state == "waiting_edit":
        return await _handle_edit_response(text, group_id, state_data)

    if state == "waiting_menu_edit":
        from handlers.menu_handler import handle_menu_edit
        return await handle_menu_edit(line_service, text, group_id, state_data)

    if state == "waiting_dish_name":
        from handlers.menu_handler import handle_dish_name
        return await handle_dish_name(line_service, text, group_id, state_data, reply_token)

    if state == "waiting_cost_input":
        from handlers.menu_handler import handle_cost_input
        return await handle_cost_input(line_service, text, group_id, state_data)

    # 2. 確認/修改/捨棄指令
    confirm_match = re.match(r"確認\s*#?(\d+)", text)
    if confirm_match:
        staging_id = int(confirm_match.group(1))
        return await _confirm_staging(staging_id, group_id)

    discard_match = re.match(r"捨棄\s*#?(\d+)", text)
    if discard_match:
        staging_id = int(discard_match.group(1))
        return _discard_staging(staging_id)

    edit_match = re.match(r"修改\s*#?(\d+)", text)
    if edit_match:
        staging_id = int(edit_match.group(1))
        return _start_edit(staging_id, group_id)

    # 3. 指令路由
    text_lower = text.strip()

    # 匯出指令
    export_match = re.match(r"匯出\s*(\d{1,2})-(\d{1,2})月?", text_lower)
    if export_match:
        return await _handle_export(export_match.group(1), export_match.group(2))

    # 統計指令
    if text_lower in ("統計", "報表", "報告"):
        return _show_stats()

    if re.match(r"統計\s*\d{4}-\d{2}", text_lower):
        ym = re.search(r"(\d{4}-\d{2})", text_lower).group(1)
        return _show_monthly_stats(ym)

    # 待處理
    if text_lower in ("待處理", "pending", "待確認"):
        return _show_pending()

    # 供應商管理
    if text_lower == "供應商":
        return _show_suppliers()

    supplier_add = re.match(r"新增供應商\s+(.+?)\s+(\d{8})", text_lower)
    if supplier_add:
        return _add_supplier(supplier_add.group(1), supplier_add.group(2))

    # 行情查詢
    if text_lower in ("行情", "市價", "今日行情"):
        return await _show_market_prices()

    price_match = re.match(r"行情\s+(.+)", text_lower)
    if price_match:
        return await _show_item_price(price_match.group(1))

    # 收入記錄
    income_match = re.match(r"新增收入\s+(\d+[\d,.]*)\s*(.*)", text_lower)
    if income_match:
        return _add_income(income_match.group(1), income_match.group(2))

    # 菜單
    if text_lower in ("菜單", "推薦菜單", "本月菜單"):
        return "請點選下方選單「🍽️ 菜單企劃」使用完整功能"

    # 幫助
    if text_lower in ("help", "指令", "幫助", "使用說明"):
        return _show_help()

    # 不回應一般聊天
    return None


# === 確認/修改/捨棄 ===

async def _confirm_staging(staging_id: int, group_id: str) -> str:
    """確認採購記錄"""
    staging = sm.get_staging(staging_id)
    if not staging:
        return f"找不到記錄 #{staging_id}"
    if staging["status"] != "pending":
        return f"記錄 #{staging_id} 已是 {staging['status']} 狀態"

    # 檢查菜市場採購是否需要經手人
    supplier = sm.get_supplier(supplier_id=staging.get("supplier_id"))
    if supplier and not supplier.get("has_uniform_invoice") and not staging.get("handler_name"):
        sm.set_state(group_id, "waiting_handler", {"staging_id": staging_id})
        return (
            f"記錄 #{staging_id} 的供應商「{staging['supplier_name']}」是菜市場攤商，"
            "稅法要求填寫經手人姓名。\n"
            "請輸入經手人姓名（例如：王小美）："
        )

    sm.confirm_staging(staging_id)

    # 更新食材價格
    items = sm.get_purchase_items(staging_id)
    for item in items:
        if item.get("ingredient_id"):
            sm.update_ingredient_price(item["ingredient_id"], item["unit_price"])

    # 複製收據到 GDrive 採購單據/
    gdrive_note = ""
    if staging.get("local_image_path"):
        try:
            from services.gdrive_service import upload_file, _year_month_path, GDRIVE_LOCAL
            import os
            ym = staging.get("year_month", "")
            if ym:
                _, month_path = _year_month_path(ym)
                dest_dir = os.path.join(month_path, "採購單據")
                os.makedirs(dest_dir, exist_ok=True)
                supplier = staging.get("supplier_name", "unknown")[:20]
                basename = os.path.basename(staging["local_image_path"])
                dest = os.path.join(dest_dir, f"{supplier}_{basename}")
                import shutil
                shutil.copy2(staging["local_image_path"], dest)
                rel = os.path.relpath(dest, GDRIVE_LOCAL)
                gdrive_note = f"\n☁️ 已歸檔：{rel}"
        except Exception as e:
            logging.getLogger("shanbot.command").warning(f"GDrive copy skipped: {e}")

    return (
        f"✅ 記錄 #{staging_id} 已確認\n"
        f"供應商：{staging['supplier_name']}\n"
        f"金額：${staging['total_amount']:,.0f}\n"
        f"歸屬月份：{staging['year_month']}"
        f"{gdrive_note}"
    )


def _discard_staging(staging_id: int) -> str:
    """捨棄採購記錄"""
    staging = sm.get_staging(staging_id)
    if not staging:
        return f"找不到記錄 #{staging_id}"
    sm.update_purchase_staging(staging_id, status="discarded")
    return f"❌ 記錄 #{staging_id} 已捨棄"


def _start_edit(staging_id: int, group_id: str) -> str:
    """進入修改模式"""
    staging = sm.get_staging(staging_id)
    if not staging:
        return f"找不到記錄 #{staging_id}"

    sm.set_state(group_id, "waiting_edit", {"staging_id": staging_id})
    items = sm.get_purchase_items(staging_id)

    lines = [f"✏️ 修改記錄 #{staging_id}", ""]
    lines.append(f"供應商：{staging['supplier_name']}")
    lines.append(f"日期：{staging['purchase_date']}")
    lines.append(f"總額：${staging['total_amount']:,.0f}")
    lines.append("")
    lines.append("品項清單：")
    for i, item in enumerate(items, 1):
        lines.append(f"  {i}. {item['item_name']} {item['quantity']}{item['unit']} "
                     f"@${item['unit_price']:,.0f} = ${item['amount']:,.0f}")
    lines.append("")
    lines.append("請輸入要修改的內容，格式：")
    lines.append("  供應商=新名稱")
    lines.append("  日期=2026-03-15")
    lines.append("  總額=5000")
    lines.append("  品項1=高麗菜 10kg @35 =350")
    lines.append("或輸入「完成修改」結束")

    return "\n".join(lines)


# === 狀態回應 ===

async def _handle_confirm_response(text: str, group_id: str, state_data: dict) -> str:
    """處理確認狀態的回應"""
    staging_id = state_data.get("staging_id")
    if not staging_id:
        sm.clear_state(group_id)
        return "狀態異常，請重新操作"

    if text.strip() in ("確認", "是", "ok", "OK", "yes"):
        sm.clear_state(group_id)
        return await _confirm_staging(staging_id, group_id)
    elif text.strip() in ("捨棄", "否", "no"):
        sm.clear_state(group_id)
        return _discard_staging(staging_id)
    else:
        return "請回覆「確認」或「捨棄」"


async def _handle_supplier_response(text: str, group_id: str, state_data: dict) -> str:
    """處理供應商名稱確認"""
    staging_id = state_data.get("staging_id")
    supplier_name = text.strip()
    if not supplier_name:
        return "請輸入供應商名稱"

    sm.update_purchase_staging(staging_id, supplier_name=supplier_name)

    # 嘗試匹配已知供應商
    supplier = sm.get_supplier(name=supplier_name)
    if supplier:
        sm.update_purchase_staging(
            staging_id,
            supplier_id=supplier["id"],
            supplier_tax_id=supplier.get("tax_id", ""),
        )

    sm.clear_state(group_id)
    return f"✅ 已設定供應商為「{supplier_name}」\n請確認記錄 #{staging_id} 或輸入「確認 #{staging_id}」"


async def _handle_handler_response(text: str, group_id: str, state_data: dict) -> str:
    """處理經手人姓名填寫"""
    staging_id = state_data.get("staging_id")
    handler_name = text.strip()
    if not handler_name:
        return "請輸入經手人姓名"

    sm.update_purchase_staging(staging_id, handler_name=handler_name)
    sm.confirm_staging(staging_id)
    sm.clear_state(group_id)

    staging = sm.get_staging(staging_id)
    return (
        f"✅ 記錄 #{staging_id} 已確認\n"
        f"經手人：{handler_name}\n"
        f"金額：${staging['total_amount']:,.0f}"
    )


async def _handle_edit_response(text: str, group_id: str, state_data: dict) -> str:
    """處理修改回應"""
    staging_id = state_data.get("staging_id")

    if text.strip() in ("完成修改", "完成", "結束"):
        sm.clear_state(group_id)
        staging = sm.get_staging(staging_id)
        return (
            f"✅ 修改完成。記錄 #{staging_id}\n"
            f"總額：${staging['total_amount']:,.0f}\n"
            f"請輸入「確認 #{staging_id}」來確認此筆記錄"
        )

    # 解析修改指令
    if text.startswith("供應商="):
        new_name = text[4:].strip()
        sm.update_purchase_staging(staging_id, supplier_name=new_name)
        return f"已修改供應商為「{new_name}」"
    elif text.startswith("日期="):
        new_date = text[3:].strip()
        sm.update_purchase_staging(staging_id, purchase_date=new_date)
        return f"已修改日期為 {new_date}"
    elif text.startswith("總額="):
        try:
            new_total = float(text[3:].strip().replace(",", ""))
            new_tax = round(new_total / 1.05 * 0.05)
            new_subtotal = new_total - new_tax
            sm.update_purchase_staging(staging_id,
                                       total_amount=new_total,
                                       subtotal=new_subtotal,
                                       tax_amount=new_tax)
            return f"已修改總額為 ${new_total:,.0f}（未稅 ${new_subtotal:,.0f} + 稅 ${new_tax:,.0f}）"
        except ValueError:
            return "金額格式錯誤，請輸入數字"

    return "格式不正確。請使用「供應商=名稱」、「日期=YYYY-MM-DD」、「總額=金額」或「完成修改」"


# === 匯出 ===

async def _handle_export(start_month: str, end_month: str) -> str:
    """處理匯出指令"""
    from datetime import datetime
    year = datetime.now().year
    start = int(start_month)
    end = int(end_month)

    # 計算稅期
    if start % 2 == 0:
        start -= 1
    tax_period = f"{year}-{start:02d}-{end:02d}"

    try:
        from services.tax_export_service import validate_before_export, export_mof_txt, \
            export_winton_excel, export_handler_cert

        # 驗證
        ok, errors = validate_before_export(tax_period)
        if not ok:
            return "⚠️ 匯出前驗證未通過：\n" + "\n".join(f"  ❌ {e}" for e in errors)

        # 匯出三種格式
        output_dir = f"/home/simon/shanbot/data/exports/{tax_period}"
        results = []

        txt_path = export_mof_txt(tax_period, output_dir)
        if txt_path:
            results.append(f"✅ MOF TXT: {txt_path}")

        excel_path = export_winton_excel(tax_period, output_dir)
        if excel_path:
            results.append(f"✅ 文中 Excel: {excel_path}")

        cert_path = export_handler_cert(tax_period, output_dir)
        if cert_path:
            results.append(f"✅ 經手人證明: {cert_path}")

        if not results:
            return "⚠️ 匯出失敗，請檢查是否有已確認的記錄"

        return f"📦 {tax_period} 稅務匯出完成\n\n" + "\n".join(results)

    except ImportError:
        return "稅務匯出模組尚未安裝"
    except Exception as e:
        logger.error(f"Export error: {e}", exc_info=True)
        return f"匯出發生錯誤：{str(e)}"


# === 查詢 ===

def _show_stats() -> str:
    """顯示整體統計"""
    from datetime import datetime
    ym = datetime.now().strftime("%Y-%m")
    return _show_monthly_stats(ym)


def _show_monthly_stats(year_month: str) -> str:
    """顯示月度統計"""
    stats = sm.get_staging_stats(year_month)
    total = stats.get("total", 0) or 0
    pending = stats.get("pending", 0) or 0
    confirmed = stats.get("confirmed", 0) or 0
    exported = stats.get("exported", 0) or 0
    amount = stats.get("total_amount", 0) or 0
    tax = stats.get("total_tax", 0) or 0

    lines = [
        f"📊 {year_month} 統計",
        f"📝 總記錄：{total} 筆",
        f"  ⏳ 待確認：{pending}",
        f"  ✅ 已確認：{confirmed}",
        f"  📦 已匯出：{exported}",
        f"💰 總金額：${amount:,.0f}",
        f"🧾 進項稅額：${tax:,.0f}",
    ]
    return "\n".join(lines)


def _show_pending() -> str:
    """顯示待處理記錄"""
    pendings = sm.get_pending_stagings()
    if not pendings:
        return "📭 目前沒有待處理的記錄"

    lines = [f"⏳ 待處理記錄：{len(pendings)} 筆", ""]
    for p in pendings[:10]:
        lines.append(
            f"  #{p['id']} | {p['purchase_date']} | "
            f"{p['supplier_name'] or '未知'} | ${p['total_amount']:,.0f}"
        )
    if len(pendings) > 10:
        lines.append(f"  ... 還有 {len(pendings) - 10} 筆")
    return "\n".join(lines)


def _show_suppliers() -> str:
    """顯示供應商列表"""
    suppliers = sm.get_all_suppliers()
    if not suppliers:
        return "📭 尚未建立供應商資料\n新增方式：「新增供應商 名稱 統一編號」"

    lines = [f"🏪 供應商列表（{len(suppliers)} 家）", ""]
    for s in suppliers:
        invoice_mark = "📄" if s.get("has_uniform_invoice") else "📝"
        lines.append(f"  {invoice_mark} {s['name']} | {s.get('tax_id', '無統編')}")
    return "\n".join(lines)


def _add_income(amount_str: str, description: str) -> str:
    """新增收入記錄"""
    from datetime import datetime
    try:
        amount = float(amount_str.replace(",", ""))
    except ValueError:
        return "金額格式錯誤，請輸入數字"
    ym = datetime.now().strftime("%Y-%m")
    today = datetime.now().strftime("%Y-%m-%d")
    sm.add_income(ym, amount, description.strip(), income_date=today)
    return f"✅ 已記錄收入 ${amount:,.0f}\n說明：{description.strip() or '（無）'}\n歸屬月份：{ym}"


def _add_supplier(name: str, tax_id: str) -> str:
    """新增供應商"""
    sid = sm.upsert_supplier(name, tax_id=tax_id)
    return f"✅ 已新增供應商：{name}（統一編號：{tax_id}）"


async def _show_market_prices() -> str:
    """顯示今日行情摘要"""
    try:
        from services.market_service import get_today_summary
        summary = await get_today_summary()
        return summary or "暫無行情資料"
    except ImportError:
        return "行情模組尚未安裝"


async def _show_item_price(item_name: str) -> str:
    """查詢特定食材行情"""
    try:
        from services.market_service import get_item_price_info
        info = await get_item_price_info(item_name)
        return info or f"找不到「{item_name}」的行情資料"
    except ImportError:
        return "行情模組尚未安裝"


def _show_help() -> str:
    """顯示使用說明"""
    return (
        "🍳 小膳 Bot v2.0 使用說明\n"
        "━━━━━━━━━━━━━━\n"
        "\n"
        "💡 點選下方「📋 小膳功能選單」\n"
        "   即可使用六宮格圖形介面！\n"
        "\n"
        "📸 拍照記帳\n"
        "  直接拍照上傳收據/對帳單\n"
        "\n"
        "📋 採購管理\n"
        "  確認 #1 / 修改 #1 / 捨棄 #1\n"
        "  待處理 → 待確認記錄\n"
        "\n"
        "📊 統計查詢\n"
        "  統計 → 本月 / 統計 2026-03\n"
        "  行情 → 市場行情 / 行情 高麗菜\n"
        "\n"
        "🏪 供應商\n"
        "  供應商 / 新增供應商 名稱 統一編號\n"
        "\n"
        "💵 收入\n"
        "  新增收入 50000 團膳合約\n"
        "\n"
        "📦 匯出\n"
        "  匯出 1-2月 → 營業稅資料\n"
        "\n"
        "help → 顯示此說明"
    )
