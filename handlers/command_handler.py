"""小膳 Bot 主命令路由器"""

import json
import logging
import os
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

    if state == "waiting_finance_search":
        return _handle_finance_search(text, group_id)

    if state == "waiting_contract_photo":
        # Text in contract-waiting state — cancel or prompt
        if text.strip() in ("取消", "cancel", "算了"):
            sm.clear_state(group_id)
            return "已取消上傳契約"
        return "📄 請傳送契約照片或 PDF 檔案\n回覆「取消」可取消"

    if state == "waiting_ocr_confirm":
        return await _handle_ocr_confirm_response(text, group_id, state_data)

    if state == "waiting_duplicate_decision":
        return await _handle_duplicate_decision(line_service, text, group_id, user_id, state_data)

    if state == "waiting_final_confirm":
        return await _handle_final_confirm_response(text, group_id, state_data)

    if state == "waiting_archive_info":
        return await _handle_archive_info_response(text, group_id, state_data)

    # 2. 確認/修改/捨棄指令
    confirm_match = re.match(r"確認\s*#?(\d+)", text)
    if confirm_match:
        staging_id = int(confirm_match.group(1))
        return await _confirm_staging(staging_id, group_id)

    discard_match = re.match(r"(?:捨棄|放棄)\s*#?(\d+)", text)
    if discard_match:
        staging_id = int(discard_match.group(1))
        return _discard_staging(staging_id)

    edit_match = re.match(r"修改\s*#?(\d+)", text)
    if edit_match:
        staging_id = int(edit_match.group(1))
        return _start_edit(staging_id, group_id)

    # 最終確認/拒絕指令（從 Flex 按鈕直接觸發）
    final_confirm_match = re.match(r"最終確認\s*#?(\d+)", text)
    if final_confirm_match:
        staging_id = int(final_confirm_match.group(1))
        sm.clear_state(group_id)
        return await _do_final_archive(staging_id, group_id)

    reject_match = re.match(r"拒絕\s*#?(\d+)", text)
    if reject_match:
        staging_id = int(reject_match.group(1))
        sm.clear_state(group_id)
        sm.update_purchase_staging(staging_id, status="discarded")
        return f"❌ 記錄 #{staging_id} 已取消，不予理會"

    # 重複跳過/另存指令（從 Flex 按鈕直接觸發）
    dup_skip_match = re.match(r"重複跳過\s*#?(\d+)", text)
    if dup_skip_match:
        sm.clear_state(group_id)
        return "已跳過，不重複存檔"

    resave_match = re.match(r"另存\s*#?(\S+)", text)
    if resave_match:
        sm.clear_state(group_id)
        return "📸 請重新傳送照片，將另存為新記錄。"

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

    # 索引指令
    if text_lower in ("索引", "報表索引"):
        return await _generate_index()

    if text_lower in ("年度索引",):
        return await _generate_annual_index()

    # === 薪資/人事管理 ===
    if text_lower in ("薪資表", "建立薪資表"):
        return await _handle_salary_template()

    if text_lower in ("員工資料", "建立員工資料", "員工資料表"):
        return await _handle_employee_template()

    if text_lower in ("薪資表完成", "薪資完成"):
        return await _handle_salary_import()

    if text_lower in ("員工清單", "員工列表"):
        return _handle_employee_list()

    if text_lower in ("上傳契約", "傳契約"):
        sm.set_state(group_id, "waiting_contract_photo", {})
        return "📄 請傳送勞動契約照片或 PDF\nAI 將自動辨識員工資料\n回覆「取消」可取消"

    # === 菜單表格 ===
    if text_lower in ("菜單表格", "建立菜單", "菜單模板"):
        return await _handle_menu_template()

    if text_lower in ("菜單完成", "菜單表完成"):
        return await _handle_menu_import()

    # 菜單
    if text_lower in ("菜單", "推薦菜單", "本月菜單"):
        return "請點選下方選單「🍽️ 菜單企劃」使用完整功能"

    # 幫助
    if text_lower in ("help", "指令", "幫助", "使用說明"):
        return _show_help()

    # 不回應一般聊天
    return None


# === 歸檔輔助函數 ===

async def _do_archive(staging_id: int, staging: dict) -> str:
    """GDrive 正式歸檔：重命名 + 收據憑證/ + INDEX.csv

    Returns:
        歸檔結果訊息字串（成功含路徑，失敗或無圖片則空字串）
    """
    if not staging.get("local_image_path"):
        return ""

    try:
        from services.gdrive_service import archive_receipt

        items = sm.get_purchase_items(staging_id)
        ocr_summary = {
            "invoice_number": staging.get("invoice_number", ""),
            "subtotal": staging.get("subtotal", 0),
            "tax_amount": staging.get("tax_amount", 0),
            "items": [{"name": it["item_name"]} for it in items],
        }

        archive_result = await archive_receipt(
            local_path=staging["local_image_path"],
            purchase_date=staging.get("purchase_date", ""),
            supplier_name=staging.get("supplier_name", ""),
            total_amount=staging.get("total_amount", 0),
            staging_id=staging_id,
            ocr_summary=ocr_summary,
        )

        if archive_result.get("gdrive_path"):
            sm.update_purchase_staging(
                staging_id, gdrive_path=archive_result["gdrive_path"]
            )
            logger.info(
                f"#{staging_id} archived to GDrive: {archive_result['gdrive_path']}"
            )
            return (
                f"\n☁️ 已歸檔：{archive_result['filename']}"
                f"\n📂 路徑：{archive_result['gdrive_path']}"
            )
        elif archive_result.get("error"):
            logger.warning(
                f"#{staging_id} archive partial fail: {archive_result['error']}"
            )
    except Exception as e:
        logger.warning(f"GDrive archive skipped for #{staging_id}: {e}")

    return ""


# === 確認/修改/捨棄 ===

async def _confirm_staging(staging_id: int, group_id: str) -> str:
    """第一步確認：顯示最終確認 Flex（二次確認流程）"""
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

    # 進入二次確認：設定 waiting_final_confirm 狀態
    items = sm.get_purchase_items(staging_id)
    sm.set_state(group_id, "waiting_final_confirm", {"staging_id": staging_id})

    # 嘗試回覆 Flex，fallback 到文字
    try:
        from services.ocr_service import build_final_confirm_flex
        flex = build_final_confirm_flex(staging_id, staging, items)
        # 返回文字提示，由呼叫端判斷（Flex 需要 line_service，這裡先返回文字）
    except Exception as e:
        logger.warning(f"build_final_confirm_flex error: {e}")

    return (
        f"📋 最終確認 #{staging_id}\n"
        f"供應商：{staging['supplier_name']}\n"
        f"日期：{staging['purchase_date']}\n"
        f"金額：${staging['total_amount']:,.0f}\n"
        f"品項數：{len(items)} 項\n\n"
        f"回覆「最終確認 #{staging_id}」確認歸檔\n"
        f"回覆「拒絕 #{staging_id}」不予理會"
    )


async def _do_final_archive(staging_id: int, group_id: str) -> str:
    """最終歸檔：實際執行確認 + 價格更新 + GDrive 歸檔
    若關鍵歸檔資訊不完整，先發問確認再歸檔。
    """
    staging = sm.get_staging(staging_id)
    if not staging:
        return f"找不到記錄 #{staging_id}"
    if staging["status"] != "pending":
        return f"記錄 #{staging_id} 已是 {staging['status']} 狀態"

    # === 歸檔前檢查：資訊不完整就發問 ===
    missing = []
    supplier = staging.get("supplier_name") or ""
    purchase_date = staging.get("purchase_date") or ""
    total = staging.get("total_amount") or 0
    year_month = staging.get("year_month") or ""

    if not supplier or supplier in ("unknown", "未知", ""):
        missing.append("供應商名稱")
    if not purchase_date or purchase_date == "未知":
        missing.append("採購日期")
    if not total or total == 0:
        missing.append("金額")

    if missing:
        sm.set_state(group_id, "waiting_archive_info", {
            "staging_id": staging_id,
            "missing_fields": missing,
        })
        fields_str = "、".join(missing)
        return (
            f"⚠️ 歸檔資訊不完整，需要補充以下資訊：\n"
            f"缺少：{fields_str}\n\n"
            f"請直接輸入，例如：\n"
            + ("  供應商：XX行\n" if "供應商名稱" in missing else "")
            + ("  日期：2026-03-09\n" if "採購日期" in missing else "")
            + ("  金額：3500\n" if "金額" in missing else "")
            + f"\n或回覆「放棄」取消歸檔"
        )

    # === 資訊完整，正式歸檔 ===
    return await _execute_archive(staging_id, staging, group_id)


async def _execute_archive(staging_id: int, staging: dict, group_id: str) -> str:
    """實際執行歸檔（資訊已完整時呼叫）"""
    sm.confirm_staging(staging_id)

    # 更新食材價格
    items = sm.get_purchase_items(staging_id)
    for item in items:
        if item.get("ingredient_id"):
            sm.update_ingredient_price(item["ingredient_id"], item["unit_price"])

    # GDrive 正式歸檔
    gdrive_note = await _do_archive(staging_id, staging)

    sm.clear_state(group_id)
    return (
        f"✅ 記錄 #{staging_id} 已確認歸檔\n"
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
    """進入修改模式 — 主動偵測缺失欄位，用對話引導補齊"""
    staging = sm.get_staging(staging_id)
    if not staging:
        return f"找不到記錄 #{staging_id}"

    items = sm.get_purchase_items(staging_id)

    # 偵測哪些欄位缺失或不確定
    missing_fields = _detect_missing_fields(staging, items)

    sm.set_state(group_id, "waiting_edit", {
        "staging_id": staging_id,
        "missing_fields": missing_fields,  # 追蹤待補欄位
        "current_asking": None,             # 目前正在問的欄位
    })

    if missing_fields:
        # 有缺失 → 直接用對話方式問第一個問題
        return _build_guided_prompt(staging_id, staging, items, missing_fields)
    else:
        # 資料都有 → 顯示目前內容，讓使用者自由修改
        return _build_edit_summary(staging_id, staging, items)


def _detect_missing_fields(staging: dict, items: list) -> list:
    """偵測缺失或不確定的欄位，回傳待補清單"""
    missing = []

    supplier = staging.get("supplier_name") or ""
    if not supplier or supplier in ("unknown", "未知", ""):
        missing.append("supplier")

    purchase_date = staging.get("purchase_date") or ""
    if not purchase_date or purchase_date == "未知":
        missing.append("date")

    total = staging.get("total_amount") or 0
    if not total or total == 0:
        missing.append("total")

    if not items:
        missing.append("items")

    return missing


def _build_guided_prompt(staging_id: int, staging: dict, items: list,
                         missing_fields: list) -> str:
    """根據缺失欄位，組裝對話式引導提問"""
    lines = [f"✏️ 記錄 #{staging_id} 有些資訊我辨識不出來，需要你幫忙補充：", ""]

    # 顯示已有的資訊
    has_info = []
    supplier = staging.get("supplier_name") or ""
    if supplier and supplier not in ("unknown", "未知"):
        has_info.append(f"  供應商：{supplier}")
    date = staging.get("purchase_date") or ""
    if date and date != "未知":
        has_info.append(f"  日期：{date}")
    total = staging.get("total_amount") or 0
    if total:
        has_info.append(f"  總額：${total:,.0f}")
    if items:
        has_info.append(f"  品項：{len(items)} 項")

    if has_info:
        lines.append("目前辨識到的：")
        lines.extend(has_info)
        lines.append("")

    # 用自然的語氣問第一個缺失項目
    q = _get_question_for_field(missing_fields[0])
    lines.append(q)

    if len(missing_fields) > 1:
        remaining = len(missing_fields) - 1
        lines.append(f"（還有 {remaining} 項需要補充）")

    return "\n".join(lines)


def _get_question_for_field(field: str) -> str:
    """針對各欄位產生自然的提問語句"""
    questions = {
        "supplier": "👉 廠商是誰？（直接打廠商名稱就好）",
        "date": "👉 這是哪一天買的？（例如：3/10 或 2026-03-10）",
        "total": "👉 總金額是多少？（直接打數字就好）",
        "items": "👉 買了什麼項目？（例如：高麗菜5斤350、雞蛋2箱1200，用逗號隔開）",
    }
    return questions.get(field, "👉 請補充資訊")


def _build_edit_summary(staging_id: int, staging: dict, items: list) -> str:
    """顯示完整資訊摘要，供使用者自由修改"""
    lines = [f"✏️ 記錄 #{staging_id} 目前內容：", ""]
    lines.append(f"供應商：{staging['supplier_name']}")
    lines.append(f"日期：{staging['purchase_date']}")
    lines.append(f"總額：${staging['total_amount']:,.0f}")
    lines.append("")
    if items:
        lines.append("品項清單：")
        for i, item in enumerate(items, 1):
            lines.append(f"  {i}. {item['item_name']} {item['quantity']}{item['unit']} "
                         f"@${item['unit_price']:,.0f} = ${item['amount']:,.0f}")
        lines.append("")
    lines.append("直接說要改什麼，或回覆「同意」確認")
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


_OCR_CONFIRM_WORDS = {"ok", "好", "對", "確認", "同意", "沒問題", "正確", "是", "yes", "可以", "👍"}
_OCR_REJECT_WORDS = {"不對", "錯了", "修改", "不正確", "重來"}


async def _handle_ocr_confirm_response(text: str, group_id: str, state_data: dict) -> str:
    """處理 OCR 確認狀態的簡易回覆"""
    staging_id = state_data.get("staging_id")
    if not staging_id:
        sm.clear_state(group_id)
        return "狀態異常，請重新操作"

    staging = sm.get_staging(staging_id)
    if not staging or staging["status"] != "pending":
        sm.clear_state(group_id)
        return f"記錄 #{staging_id} 已處理"

    normalized = text.strip().lower()

    # 確認（含原有 "確認 #123" 格式）
    if normalized in _OCR_CONFIRM_WORDS or re.match(r"確認\s*#?\d+", normalized):
        sm.clear_state(group_id)
        return await _confirm_staging(staging_id, group_id)

    # 修改
    if normalized in _OCR_REJECT_WORDS or re.match(r"修改\s*#?\d+", normalized):
        sm.clear_state(group_id)
        return _start_edit(staging_id, group_id)

    # 放棄/捨棄
    if normalized in ("捨棄", "放棄", "丟掉", "不要") or re.match(r"(?:捨棄|放棄)\s*#?\d+", normalized):
        sm.clear_state(group_id)
        return _discard_staging(staging_id)

    # 不認識 → 提示（不清除狀態）
    return (f"📋 記錄 #{staging_id} 等待確認中\n"
            "回覆「正確」或「OK」確認\n"
            "回覆「修改」進入修改模式\n"
            "回覆「放棄」捨棄此筆")


async def _handle_archive_info_response(text: str, group_id: str, state_data: dict) -> str:
    """處理歸檔資訊補充回應（供應商/日期/金額缺失時發問）"""
    staging_id = state_data.get("staging_id")
    if not staging_id:
        sm.clear_state(group_id)
        return "找不到對應的記錄"

    normalized = text.strip()

    # 放棄
    if normalized in ("放棄", "取消", "算了"):
        sm.clear_state(group_id)
        return _discard_staging(staging_id)

    staging = sm.get_staging(staging_id)
    if not staging:
        sm.clear_state(group_id)
        return f"找不到記錄 #{staging_id}"

    missing = state_data.get("missing_fields", [])
    updated = {}

    # 嘗試解析使用者輸入的補充資訊
    for line in normalized.replace("，", "\n").replace(",", "\n").split("\n"):
        line = line.strip()
        if not line:
            continue

        # 供應商
        sup_m = re.match(r"(?:供應商|廠商|店家)[：:=]?\s*(.+)", line)
        if sup_m:
            updated["supplier_name"] = sup_m.group(1).strip()
            continue

        # 日期
        date_m = re.match(r"(?:日期|時間)[：:=]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})", line)
        if date_m:
            updated["purchase_date"] = date_m.group(1).replace("/", "-")
            d = updated["purchase_date"]
            updated["year_month"] = d[:7]
            continue

        # 金額
        amt_m = re.match(r"(?:金額|總額|合計)[：:=]?\s*\$?(\d[\d,]*)", line)
        if amt_m:
            updated["total_amount"] = int(amt_m.group(1).replace(",", ""))
            continue

        # 如果只輸入一項且只缺一項，直接對應
        if len(missing) == 1:
            if "供應商名稱" in missing:
                updated["supplier_name"] = line
            elif "採購日期" in missing:
                date_try = re.match(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", line)
                if date_try:
                    updated["purchase_date"] = date_try.group(1).replace("/", "-")
                    updated["year_month"] = updated["purchase_date"][:7]
            elif "金額" in missing:
                amt_try = re.match(r"\$?(\d[\d,]*)", line)
                if amt_try:
                    updated["total_amount"] = int(amt_try.group(1).replace(",", ""))

    if not updated:
        fields_str = "、".join(missing)
        return (
            f"我沒有辨識到有效的補充資訊\n"
            f"仍然缺少：{fields_str}\n"
            f"請輸入，例如：供應商：XX行\n"
            f"或回覆「放棄」取消歸檔"
        )

    # 套用更新
    sm.update_purchase_staging(staging_id, **updated)
    staging = sm.get_staging(staging_id)  # reload

    # 重新檢查是否還有缺少
    still_missing = []
    if not (staging.get("supplier_name") or "") or staging["supplier_name"] in ("unknown", "未知"):
        still_missing.append("供應商名稱")
    if not (staging.get("purchase_date") or "") or staging["purchase_date"] == "未知":
        still_missing.append("採購日期")
    if not staging.get("total_amount"):
        still_missing.append("金額")

    if still_missing:
        sm.set_state(group_id, "waiting_archive_info", {
            "staging_id": staging_id,
            "missing_fields": still_missing,
        })
        fields_str = "、".join(still_missing)
        return f"👍 已更新！但還缺少：{fields_str}\n請繼續補充，或回覆「放棄」取消"

    # 全部補齊 → 正式歸檔
    return await _execute_archive(staging_id, staging, group_id)


async def _handle_final_confirm_response(text: str, group_id: str, state_data: dict) -> str:
    """處理最終確認狀態的回應"""
    staging_id = state_data.get("staging_id")
    if not staging_id:
        sm.clear_state(group_id)
        return "狀態異常，請重新操作"

    normalized = text.strip()

    # 最終確認 → 實際歸檔
    if re.match(r"最終確認\s*#?\d*", normalized) or normalized.lower() in ("最終確認", "確認歸檔", "確認"):
        sm.clear_state(group_id)
        return await _do_final_archive(staging_id, group_id)

    # 拒絕 → 標記 discarded
    if re.match(r"拒絕\s*#?\d*", normalized) or normalized in ("拒絕", "不要", "取消", "不予理會"):
        sm.clear_state(group_id)
        sm.update_purchase_staging(staging_id, status="discarded")
        return f"❌ 記錄 #{staging_id} 已取消，不予理會"

    return (
        f"📋 記錄 #{staging_id} 等待最終確認\n"
        f"回覆「最終確認」確認歸檔\n"
        f"回覆「拒絕」不予理會"
    )


async def _handle_duplicate_decision(line_service, text: str, group_id: str,
                                      user_id: str, state_data: dict) -> str:
    """處理重複圖片決策"""
    normalized = text.strip()

    # 重複跳過
    if normalized.startswith("重複跳過") or normalized in ("跳過", "相同內容"):
        sm.clear_state(group_id)
        return "已跳過，不重複存檔"

    # 另存新檔 → 重新觸發完整照片處理流程
    if normalized.startswith("另存") or normalized in ("另存新檔", "新檔"):
        message_id = state_data.get("message_id", "")
        sm.clear_state(group_id)
        return (
            "📸 請重新傳送照片，將另存為新記錄。\n"
            "（重新上傳一次即可）"
        )

    return (
        "⚠️ 偵測到重複圖片\n"
        "回覆「重複跳過」跳過不存\n"
        "回覆「另存」另存新檔"
    )


def _handle_finance_search(text: str, group_id: str) -> str:
    """處理財務文件搜尋（waiting_finance_search 狀態）"""
    keyword = text.strip()
    sm.clear_state(group_id)

    if not keyword:
        return "請輸入搜尋關鍵字"

    docs = sm.search_financial_documents(keyword)
    if not docs:
        return f"🔍 找不到包含「{keyword}」的財務文件"

    lines = [f"🔍 搜尋「{keyword}」找到 {len(docs)} 筆文件", ""]
    for doc in docs[:10]:
        status_icon = "✅" if doc.get("status") == "confirmed" else "⏳"
        lines.append(
            f"  {status_icon} #{doc['id']} | {doc.get('filename', '')} | "
            f"{doc.get('doc_category', '')} | {doc.get('year_month', '')}"
        )
    if len(docs) > 10:
        lines.append(f"  ... 還有 {len(docs) - 10} 筆")

    return "\n".join(lines)


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
    """處理經手人姓名填寫 → 進入二次確認"""
    staging_id = state_data.get("staging_id")
    handler_name = text.strip()
    if not handler_name:
        return "請輸入經手人姓名"

    sm.update_purchase_staging(staging_id, handler_name=handler_name)
    sm.clear_state(group_id)

    # 進入二次確認流程
    staging = sm.get_staging(staging_id)
    items = sm.get_purchase_items(staging_id)
    sm.set_state(group_id, "waiting_final_confirm", {"staging_id": staging_id})

    return (
        f"✅ 經手人已設定：{handler_name}\n\n"
        f"📋 最終確認 #{staging_id}\n"
        f"供應商：{staging['supplier_name']}\n"
        f"金額：${staging['total_amount']:,.0f}\n"
        f"品項數：{len(items)} 項\n\n"
        f"回覆「最終確認」確認歸檔\n"
        f"回覆「拒絕」不予理會"
    )


async def _handle_edit_response(text: str, group_id: str, state_data: dict) -> str:
    """處理修改回應 — 對話式引導 + 自然語言智慧比對"""
    staging_id = state_data.get("staging_id")
    missing_fields = state_data.get("missing_fields", [])

    # 同意/正確 → 確認
    if text.strip().lower() in ("同意", "正確", "ok", "好", "確認", "沒問題", "yes"):
        sm.clear_state(group_id)
        return await _confirm_staging(staging_id, group_id)

    # 放棄
    if text.strip() in ("放棄", "取消", "算了"):
        sm.clear_state(group_id)
        return _discard_staging(staging_id)

    # 取得目前記錄
    staging = sm.get_staging(staging_id)
    if not staging:
        sm.clear_state(group_id)
        return "狀態異常，請重新操作"

    items = sm.get_purchase_items(staging_id)
    user_input = text.strip()

    # === 先嘗試明確格式（key=value 或「供應商是XXX」）— 不管引導模式 ===
    explicit_changes = _parse_edit_local(user_input)
    if explicit_changes:
        for change in explicit_changes:
            _apply_single_change(staging_id, staging, items, change)
        staging = sm.get_staging(staging_id)
        items = sm.get_purchase_items(staging_id)
        still_missing = _detect_missing_fields(staging, items)
        if still_missing:
            sm.set_state(group_id, "waiting_edit", {
                "staging_id": staging_id, "missing_fields": still_missing,
            })
            q = _get_question_for_field(still_missing[0])
            return f"✅ 已更新！\n\n接下來：\n{q}"
        sm.set_state(group_id, "waiting_edit", {
            "staging_id": staging_id, "missing_fields": [],
        })
        return _build_edit_summary(staging_id, staging, items)

    # === 對話引導模式：如果有待補欄位，嘗試將回答對應到當前問題 ===
    if missing_fields:
        applied_guided = _try_guided_answer(staging_id, staging, user_input, missing_fields)

        if applied_guided:
            # 成功補上 → 移除已補的欄位
            remaining = [f for f in missing_fields if f not in applied_guided]

            # 重新載入
            staging = sm.get_staging(staging_id)
            items = sm.get_purchase_items(staging_id)

            if remaining:
                # 還有下一題 → 繼續問
                sm.set_state(group_id, "waiting_edit", {
                    "staging_id": staging_id,
                    "missing_fields": remaining,
                })
                q = _get_question_for_field(remaining[0])
                applied_str = "、".join(applied_guided)
                return f"👍 已補上{applied_str}！\n\n接下來：\n{q}"
            else:
                # 全部補齊 → 顯示完整結果，問要不要確認
                sm.set_state(group_id, "waiting_edit", {
                    "staging_id": staging_id,
                    "missing_fields": [],
                })
                return _build_edit_summary(staging_id, staging, items)

    # === 自由修改模式：用正則 + LLM 智慧比對 ===
    changes = _parse_edit_local(user_input)
    if not changes:
        changes = await _parse_edit_with_llm(staging, items, user_input)

    if changes is None:
        if missing_fields:
            q = _get_question_for_field(missing_fields[0])
            return f"我沒聽懂，可以再說一次嗎？\n\n{q}"
        return "我不太確定你要修改什麼，可以再說清楚一點嗎？"

    # 套用修改
    applied = []
    for change in changes:
        result = _apply_single_change(staging_id, staging, items, change)
        if result:
            applied.append(result)

    if not applied:
        if missing_fields:
            q = _get_question_for_field(missing_fields[0])
            return f"我沒有辨識到修改內容，再試一次？\n\n{q}"
        return "我不太確定你要修改什麼，可以再說清楚一點嗎？"

    # 重新讀取
    staging = sm.get_staging(staging_id)
    items = sm.get_purchase_items(staging_id)

    # 檢查是否還有缺失
    still_missing = _detect_missing_fields(staging, items)

    if still_missing:
        sm.set_state(group_id, "waiting_edit", {
            "staging_id": staging_id,
            "missing_fields": still_missing,
        })
        lines = ["✅ 已修改："]
        for a in applied:
            lines.append(f"  • {a}")
        lines.append("")
        q = _get_question_for_field(still_missing[0])
        lines.append(f"接下來：\n{q}")
        return "\n".join(lines)

    # 全部完整 → 顯示摘要
    sm.set_state(group_id, "waiting_edit", {
        "staging_id": staging_id,
        "missing_fields": [],
    })
    lines = ["✅ 已修改："]
    for a in applied:
        lines.append(f"  • {a}")
    lines.append("")
    lines.append(_build_edit_summary(staging_id, staging, items))
    return "\n".join(lines)


def _try_guided_answer(staging_id: int, staging: dict, user_input: str,
                       missing_fields: list) -> list:
    """嘗試將使用者回答對應到引導問題的欄位，回傳已成功填入的欄位名稱"""
    filled = []
    current_field = missing_fields[0] if missing_fields else None

    if current_field == "supplier":
        # 使用者直接回答廠商名稱
        name = user_input.strip()
        # 清除可能的前綴
        name = re.sub(r"^(?:廠商|供應商|店家)[是為：:=]?\s*", "", name).strip()
        if name and len(name) <= 50:
            sm.update_purchase_staging(staging_id, supplier_name=name)
            filled.append("supplier")

    elif current_field == "date":
        # 嘗試解析日期
        date_input = re.sub(r"^(?:日期|時間)[是為：:=]?\s*", "", user_input).strip()
        parsed = _parse_date_input(date_input)
        if parsed:
            sm.update_purchase_staging(staging_id, purchase_date=parsed, year_month=parsed[:7])
            filled.append("date")

    elif current_field == "total":
        # 嘗試解析金額
        amt_input = re.sub(r"^(?:總額|金額|合計)[是為：:=]?\s*", "", user_input).strip()
        amt_m = re.match(r"\$?(\d[\d,]*)", amt_input)
        if amt_m:
            amount = int(amt_m.group(1).replace(",", ""))
            if amount > 0:
                sm.update_purchase_staging(staging_id, total_amount=amount)
                filled.append("total")

    elif current_field == "items":
        # 嘗試解析品項（簡單格式：品名數量金額，用逗號分隔）
        items_text = re.sub(r"^(?:項目|品項|買了)[是為：:=]?\s*", "", user_input).strip()
        parsed_items = _parse_items_input(staging_id, items_text)
        if parsed_items:
            filled.append("items")

    return filled


def _parse_date_input(text: str) -> str | None:
    """解析各種日期格式"""
    # YYYY-MM-DD or YYYY/MM/DD
    m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # M/D or MM/DD (assume current year)
    m = re.match(r"(\d{1,2})[-/](\d{1,2})$", text)
    if m:
        from datetime import datetime
        year = datetime.now().year
        return f"{year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"

    # 今天、昨天
    from datetime import datetime, timedelta
    if text in ("今天", "今日"):
        return datetime.now().strftime("%Y-%m-%d")
    if text in ("昨天", "昨日"):
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    return None


def _parse_items_input(staging_id: int, text: str) -> bool:
    """解析品項文字輸入，存入 purchase_items 表"""
    # 格式：品名數量金額，用逗號/頓號分隔
    # 例如：「高麗菜5斤350、雞蛋2箱1200」
    parts = re.split(r"[,，、;；\n]", text)
    added = 0
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 嘗試解析：品名 + 數量 + 單位 + 金額
        m = re.match(r"(.+?)\s*(\d+\.?\d*)\s*(斤|公斤|kg|箱|包|顆|個|份|把|束|袋|瓶|罐|盒|打)?\s*[,，]?\s*\$?(\d+)", part)
        if m:
            name = m.group(1).strip()
            qty = float(m.group(2))
            unit = m.group(3) or ""
            amount = int(m.group(4))
            unit_price = amount / qty if qty else amount
            sm.add_purchase_item(staging_id, item_name=name, quantity=qty,
                                 unit=unit, unit_price=unit_price, amount=amount)
            added += 1
        else:
            # 退而求其次：只有品名和金額
            m2 = re.match(r"(.+?)\s*\$?(\d+)$", part)
            if m2:
                name = m2.group(1).strip()
                amount = int(m2.group(2))
                sm.add_purchase_item(staging_id, item_name=name, quantity=1,
                                     unit="", unit_price=amount, amount=amount)
                added += 1

    return added > 0


def _parse_edit_local(user_input: str) -> list | None:
    """本地正則解析 — 處理 key=value 格式和簡單模式，作為 LLM 前的快速 fallback"""
    changes = []

    # 相容舊格式：供應商=xxx, 日期=xxx, 總額=xxx
    if user_input.startswith("供應商="):
        new_val = user_input[4:].strip()
        if new_val:
            changes.append({"field": "supplier_name", "new": new_val})
    elif user_input.startswith("日期="):
        new_val = user_input[3:].strip()
        if new_val:
            changes.append({"field": "purchase_date", "new": new_val})
    elif user_input.startswith("總額="):
        new_val = user_input[3:].strip().replace(",", "")
        try:
            changes.append({"field": "total_amount", "new": float(new_val)})
        except ValueError:
            pass

    # 簡單模式：「供應商是XXX」「日期改成XXX」「總額應該是XXX」
    if not changes:
        m = re.match(r"供應商[是改為]+\s*(.+)", user_input)
        if m:
            changes.append({"field": "supplier_name", "new": m.group(1).strip()})

    if not changes:
        m = re.match(r"日期[是改為]+\s*(.+)", user_input)
        if m:
            changes.append({"field": "purchase_date", "new": m.group(1).strip()})

    if not changes:
        m = re.match(r"總額[是應該改為]+\s*(\d[\d,.]*)", user_input)
        if m:
            try:
                changes.append({"field": "total_amount", "new": float(m.group(1).replace(",", ""))})
            except ValueError:
                pass

    return changes if changes else None


async def _parse_edit_with_llm(staging: dict, items: list, user_input: str) -> list | None:
    """用 LLM 解析使用者自然語言修改意圖，回傳 changes list 或 None"""
    from services.llm_service import chat as llm_chat

    # 組裝目前資料摘要
    item_lines = []
    for i, item in enumerate(items, 1):
        item_lines.append(
            f"  {i}. item_name={item['item_name']}, quantity={item['quantity']}, "
            f"unit={item['unit']}, unit_price={item['unit_price']}, amount={item['amount']}"
        )
    items_text = "\n".join(item_lines) if item_lines else "  （無品項）"

    prompt = (
        f"以下是一筆採購 OCR 辨識結果：\n"
        f"supplier_name={staging['supplier_name']}\n"
        f"purchase_date={staging['purchase_date']}\n"
        f"total_amount={staging['total_amount']}\n"
        f"品項：\n{items_text}\n\n"
        f"使用者說：「{user_input}」\n\n"
        f"請判斷使用者想修改什麼。回傳純 JSON（不要 markdown），格式：\n"
        f'{{"changes": [...]}}\n'
        f"每個 change 物件可以是：\n"
        f'  修改表頭：{{"field": "supplier_name"|"purchase_date"|"total_amount", "new": 新值}}\n'
        f'  修改品項：{{"field": "item", "item_name": "原品名（模糊匹配即可）", '
        f'"attribute": "item_name"|"quantity"|"unit"|"unit_price"|"amount", "new": 新值}}\n'
        f"數字值請用數字型別，不要用字串。\n"
        f"如果無法判斷，回傳 {{}}"
    )

    system = (
        "你是採購記錄修改助手。只回傳 JSON，不要任何其他文字。"
        "根據使用者的口語表達，對比 OCR 辨識結果，判斷要修改的欄位和新值。"
        "使用者可能用口語（例如「花菜是150不是160」表示要把花菜的金額從160改成150）。"
    )

    result = llm_chat(prompt, system=system, max_tokens=500, timeout=20)
    if not result:
        logger.warning("LLM edit parse failed: no response")
        return None

    # 解析 JSON
    try:
        # 清理可能的 markdown 包裝
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]  # remove first ``` line
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        data = json.loads(cleaned)
        changes = data.get("changes", [])
        if not changes:
            return None
        return changes
    except (json.JSONDecodeError, AttributeError) as e:
        logger.warning(f"LLM edit parse JSON error: {e}, raw={result[:200]}")
        return None


def _apply_single_change(staging_id: int, staging: dict, items: list,
                         change: dict) -> str | None:
    """套用單一修改，回傳描述字串或 None"""
    field = change.get("field", "")

    # 表頭修改
    if field == "supplier_name":
        new_val = str(change.get("new", "")).strip()
        if new_val:
            sm.update_purchase_staging(staging_id, supplier_name=new_val)
            return f"供應商 → {new_val}"

    elif field == "purchase_date":
        new_val = str(change.get("new", "")).strip()
        if new_val:
            sm.update_purchase_staging(staging_id, purchase_date=new_val)
            return f"日期 → {new_val}"

    elif field == "total_amount":
        try:
            new_total = float(change.get("new", 0))
            new_tax = round(new_total / 1.05 * 0.05)
            new_subtotal = new_total - new_tax
            sm.update_purchase_staging(staging_id,
                                       total_amount=new_total,
                                       subtotal=new_subtotal,
                                       tax_amount=new_tax)
            return f"總額 → ${new_total:,.0f}"
        except (ValueError, TypeError):
            return None

    # 品項修改
    elif field == "item":
        target_name = str(change.get("item_name", "")).strip()
        attribute = change.get("attribute", "")
        new_val = change.get("new")

        if not target_name or not attribute or new_val is None:
            return None

        # 模糊匹配品項
        matched_item = _fuzzy_match_item(items, target_name)
        if not matched_item:
            return None

        item_id = matched_item["id"]

        # 套用品項級修改
        update_kwargs = {}
        desc = ""

        if attribute == "item_name":
            update_kwargs["item_name"] = str(new_val)
            desc = f"{matched_item['item_name']} 品名 → {new_val}"
        elif attribute == "quantity":
            try:
                update_kwargs["quantity"] = float(new_val)
                desc = f"{matched_item['item_name']} 數量 → {new_val}"
            except (ValueError, TypeError):
                return None
        elif attribute == "unit":
            update_kwargs["unit"] = str(new_val)
            desc = f"{matched_item['item_name']} 單位 → {new_val}"
        elif attribute == "unit_price":
            try:
                update_kwargs["unit_price"] = float(new_val)
                desc = f"{matched_item['item_name']} 單價 → ${float(new_val):,.0f}"
            except (ValueError, TypeError):
                return None
        elif attribute == "amount":
            try:
                update_kwargs["amount"] = float(new_val)
                desc = f"{matched_item['item_name']} 金額 → ${float(new_val):,.0f}"
            except (ValueError, TypeError):
                return None
        else:
            return None

        if update_kwargs:
            sm.update_purchase_item(item_id, **update_kwargs)
            return desc

    return None


def _fuzzy_match_item(items: list, target_name: str) -> dict | None:
    """模糊匹配品項名稱"""
    target = target_name.strip().lower()
    # 精確匹配
    for item in items:
        if item["item_name"].strip().lower() == target:
            return item
    # 包含匹配
    for item in items:
        name = item["item_name"].strip().lower()
        if target in name or name in target:
            return item
    return None


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


async def _generate_index() -> str:
    """生成當月總覽索引"""
    from datetime import datetime
    ym = datetime.now().strftime("%Y-%m")
    try:
        from services.gdrive_service import update_master_index
        csv_path = update_master_index(ym)
        if csv_path:
            # 計算檔案數
            import csv as csv_module
            count = 0
            try:
                with open(csv_path, "r", encoding="utf-8-sig") as f:
                    reader = csv_module.DictReader(f)
                    rows = list(reader)
                    count = len(rows)
                    # 統計各類別
                    cats = {}
                    for r in rows:
                        cat = r.get("類別", "其他")
                        cats[cat] = cats.get(cat, 0) + 1
            except Exception:
                pass

            lines = [f"📑 {ym} 總覽索引已更新", f"共 {count} 個檔案", ""]
            if cats:
                for cat, cnt in sorted(cats.items()):
                    lines.append(f"  📂 {cat}：{cnt} 個")
            lines.append(f"\n📁 {csv_path}")
            return "\n".join(lines)
        else:
            return f"⚠️ {ym} 無資料可索引"
    except Exception as e:
        logger.error(f"Generate index error: {e}", exc_info=True)
        return f"索引生成失敗：{str(e)}"


async def _generate_annual_index() -> str:
    """生成年度總覽索引"""
    from datetime import datetime
    year = str(datetime.now().year)
    try:
        from services.gdrive_service import generate_annual_index
        csv_path = generate_annual_index(year)
        if csv_path:
            import csv as csv_module
            count = 0
            try:
                with open(csv_path, "r", encoding="utf-8-sig") as f:
                    count = sum(1 for _ in csv_module.DictReader(f))
            except Exception:
                pass
            return (
                f"📑 {year} 年度總覽索引已更新\n"
                f"共 {count} 個檔案\n"
                f"📁 {csv_path}"
            )
        else:
            return f"⚠️ {year} 年無資料可索引"
    except Exception as e:
        logger.error(f"Generate annual index error: {e}", exc_info=True)
        return f"年度索引生成失敗：{str(e)}"


# === 薪資/人事管理 handler ===

async def _handle_salary_template() -> str:
    """建立薪資表模板"""
    from datetime import datetime
    try:
        from services.salary_service import generate_salary_template
        ym = datetime.now().strftime("%Y-%m")
        filepath = generate_salary_template(ym)
        return (
            f"✅ 薪資表模板已建立\n"
            f"📅 月份：{ym}\n"
            f"📁 路徑：{filepath}\n\n"
            f"請到 Google Drive 開啟 Excel 檔案填寫\n"
            f"填完後回覆「薪資表完成」匯入系統"
        )
    except Exception as e:
        logger.error(f"Salary template error: {e}", exc_info=True)
        return f"建立薪資表失敗：{str(e)}"


async def _handle_employee_template() -> str:
    """建立員工資料表模板"""
    try:
        from services.salary_service import generate_employee_template
        filepath = generate_employee_template()
        return (
            f"✅ 員工資料表已建立\n"
            f"📁 路徑：{filepath}\n\n"
            f"請到 Google Drive 開啟 Excel 檔案填寫員工資料"
        )
    except Exception as e:
        logger.error(f"Employee template error: {e}", exc_info=True)
        return f"建立員工資料表失敗：{str(e)}"


async def _handle_salary_import() -> str:
    """匯入已填寫的薪資表"""
    from datetime import datetime
    try:
        from services.salary_service import import_salary_from_sheet
        from services.gdrive_service import GDRIVE_LOCAL

        ym = datetime.now().strftime("%Y-%m")
        parts = ym.split("-")
        year = parts[0]
        month = f"{int(parts[1]):02d}月"
        filepath = os.path.join(GDRIVE_LOCAL, year, month, "薪資表", f"薪資表_{ym}.xlsx")

        if not os.path.exists(filepath):
            return (
                f"找不到薪資表檔案\n"
                f"預期路徑：{filepath}\n\n"
                f"請先輸入「薪資表」建立模板，填寫後再回覆「薪資表完成」"
            )

        result = import_salary_from_sheet(filepath, ym)

        lines = [f"📊 薪資表匯入完成 — {ym}", ""]
        lines.append(f"✅ 匯入 {result['count']} 人")
        if result['count'] > 0:
            lines.append(f"💰 應發合計：${result['total_gross']:,.0f}")
            lines.append(f"💵 實發合計：${result['total_net']:,.0f}")
        if result['errors']:
            lines.append("")
            lines.append("⚠️ 錯誤：")
            for err in result['errors']:
                lines.append(f"  • {err}")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Salary import error: {e}", exc_info=True)
        return f"匯入薪資表失敗：{str(e)}"


def _handle_employee_list() -> str:
    """列出所有在職員工"""
    employees = sm.list_employees(status="active")
    if not employees:
        return (
            "📭 尚未建立員工資料\n\n"
            "建立方式：\n"
            "  1. 輸入「員工資料」建立 Excel 模板\n"
            "  2. 輸入「上傳契約」用 AI 辨識契約"
        )

    from services.salary_service import mask_id_number
    lines = [f"👥 在職員工（{len(employees)} 人）", ""]
    for emp in employees:
        id_masked = mask_id_number(emp.get("id_number", ""))
        salary = emp.get("base_salary", 0) or 0
        lines.append(
            f"  #{emp['id']} {emp['name']} | {emp.get('position', '-')} | "
            f"底薪 ${salary:,} | {id_masked}"
        )
    return "\n".join(lines)


async def handle_contract_upload(image_path: str, group_id: str) -> str:
    """處理契約圖片上傳 — 解析 + 建檔 + 歸檔

    Called from main.py _handle_image() when state is waiting_contract_photo.
    """
    sm.clear_state(group_id)

    try:
        from services.salary_service import (
            parse_contract_image, create_employee_folder, archive_contract, mask_id_number
        )

        # 1. Gemini VLM 解析契約
        result = parse_contract_image(image_path)
        if not result or not result.get("name"):
            return "❌ 無法辨識契約內容，請確認圖片清晰度\n可重新輸入「上傳契約」再試"

        name = result.get("name", "").strip()
        id_number = result.get("id_number", "")
        position = result.get("position", "")
        department = result.get("department", "")
        base_salary = result.get("base_salary", 0)
        hire_date = result.get("hire_date", "")

        # 2. 建立員工記錄
        emp_data = {"name": name, "status": "active"}
        if id_number:
            emp_data["id_number"] = id_number
        if position:
            emp_data["position"] = position
        if department:
            emp_data["department"] = department
        if base_salary:
            try:
                emp_data["base_salary"] = int(float(base_salary))
            except (ValueError, TypeError):
                pass
        if hire_date:
            emp_data["hire_date"] = hire_date

        emp_id = sm.add_employee(**emp_data)

        # 3. 建立 GDrive 資料夾 + 歸檔契約
        folder_path = create_employee_folder(name)
        contract_path = archive_contract(image_path, name)
        sm.update_employee(emp_id, contract_gdrive_path=contract_path)

        # 4. 組裝回覆
        id_masked = mask_id_number(id_number)
        lines = ["✅ 契約辨識完成，已建立員工資料", ""]
        lines.append(f"👤 姓名：{name}")
        if id_masked:
            lines.append(f"🆔 身分證：{id_masked}")
        if position:
            lines.append(f"💼 職稱：{position}")
        if department:
            lines.append(f"🏢 部門：{department}")
        if base_salary:
            lines.append(f"💰 底薪：${int(float(base_salary)):,}")
        if hire_date:
            lines.append(f"📅 到職日：{hire_date}")
        lines.append("")
        lines.append(f"📂 資料夾：{folder_path}")
        lines.append(f"📄 契約：{contract_path}")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Contract upload error: {e}", exc_info=True)
        return f"❌ 契約處理失敗：{str(e)}\n可重新輸入「上傳契約」再試"


async def _handle_menu_template() -> str:
    """建立菜單排程模板"""
    from datetime import datetime
    try:
        from services.salary_service import generate_menu_template
        ym = datetime.now().strftime("%Y-%m")
        filepath = generate_menu_template(ym)
        return (
            f"✅ 菜單排程表已建立\n"
            f"📅 月份：{ym}\n"
            f"📁 路徑：{filepath}\n\n"
            f"請到 Google Drive 開啟 Excel 填寫菜單\n"
            f"填完後回覆「菜單完成」匯入系統"
        )
    except Exception as e:
        logger.error(f"Menu template error: {e}", exc_info=True)
        return f"建立菜單表格失敗：{str(e)}"


async def _handle_menu_import() -> str:
    """匯入已填寫的菜單表"""
    from datetime import datetime
    try:
        from services.salary_service import parse_menu_excel
        from services.gdrive_service import GDRIVE_LOCAL

        ym = datetime.now().strftime("%Y-%m")
        parts = ym.split("-")
        year = parts[0]
        month = f"{int(parts[1]):02d}月"
        filepath = os.path.join(GDRIVE_LOCAL, year, month, "菜單企劃", f"菜單_{ym}.xlsx")

        if not os.path.exists(filepath):
            return (
                f"找不到菜單檔案\n"
                f"預期路徑：{filepath}\n\n"
                f"請先輸入「菜單表格」建立模板，填寫後再回覆「菜單完成」"
            )

        records = parse_menu_excel(filepath)
        if not records:
            return "菜單表格是空的，請先填寫菜色後再匯入"

        # Import to DB
        imported = 0
        for rec in records:
            try:
                sm.add_menu_schedule(
                    schedule_date=rec["date"],
                    slot=rec["slot"],
                    meal_type=rec["meal_type"],
                )
                imported += 1
            except Exception as e:
                logger.warning(f"Menu import row error: {e}")

        # Summary by date
        dates = sorted(set(r["date"] for r in records))
        lunch_count = sum(1 for r in records if r["meal_type"] == "lunch")
        dinner_count = sum(1 for r in records if r["meal_type"] == "dinner")

        return (
            f"✅ 菜單匯入完成 — {ym}\n"
            f"📅 涵蓋 {len(dates)} 天\n"
            f"🍱 午餐菜色 {lunch_count} 道\n"
            f"🍽️ 晚餐菜色 {dinner_count} 道\n"
            f"📊 共 {len(records)} 筆記錄"
        )
    except Exception as e:
        logger.error(f"Menu import error: {e}", exc_info=True)
        return f"匯入菜單失敗：{str(e)}"


def _show_help() -> str:
    """顯示使用說明"""
    return (
        "🍳 小膳 Bot v2.5 使用說明\n"
        "━━━━━━━━━━━━━━\n"
        "\n"
        "💡 點選下方「📋 小膳功能選單」\n"
        "   即可使用六宮格圖形介面！\n"
        "\n"
        "📸 拍照記帳\n"
        "  直接拍照上傳收據/對帳單\n"
        "\n"
        "📋 採購管理\n"
        "  確認 #1 / 修改 #1 / 放棄 #1\n"
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
        "👥 人事薪資\n"
        "  薪資表 → 建立薪資表模板\n"
        "  員工資料 → 建立員工資料表\n"
        "  上傳契約 → AI 辨識勞動契約\n"
        "  員工清單 → 查看在職員工\n"
        "  薪資表完成 → 匯入薪資資料\n"
        "\n"
        "🍽️ 菜單\n"
        "  菜單表格 → 建立菜單排程\n"
        "  菜單完成 → 匯入菜單資料\n"
        "\n"
        "help → 顯示此說明"
    )
