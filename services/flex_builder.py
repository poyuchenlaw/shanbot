"""Flex Message 模板工廠 — 六宮格子選單 + 報表卡片"""

import logging
from datetime import datetime

logger = logging.getLogger("shanbot.flex")


# === 色彩常數 ===
COLOR_PRIMARY = "#06C755"     # LINE 綠
COLOR_SECONDARY = "#8B5E3C"   # 暖咖啡
COLOR_BG_WARM = "#FFF8F0"     # 米白
COLOR_BG_HEADER = "#F5EDE3"   # 淡棕
COLOR_TEXT = "#333333"
COLOR_TEXT_SUB = "#888888"
COLOR_RED = "#DD2E44"
COLOR_BLUE = "#1A73E8"


def _header_box(title: str, emoji: str = "") -> dict:
    """共用表頭"""
    return {
        "type": "box", "layout": "vertical",
        "backgroundColor": COLOR_BG_HEADER,
        "paddingAll": "16px",
        "contents": [{
            "type": "text",
            "text": f"{emoji} {title}" if emoji else title,
            "weight": "bold", "size": "lg", "color": COLOR_TEXT,
        }],
    }


def _action_button(label: str, data: str, color: str = COLOR_PRIMARY,
                   display_text: str = "", style: str = "primary") -> dict:
    """共用按鈕"""
    action = {"type": "postback", "label": label, "data": data}
    if display_text:
        action["displayText"] = display_text
    return {
        "type": "button", "style": style, "color": color,
        "height": "sm", "action": action,
    }


def _step_row(num: str, title: str, desc: str) -> dict:
    """引導步驟列"""
    return {
        "type": "box", "layout": "horizontal", "spacing": "md",
        "margin": "md",
        "contents": [
            {
                "type": "box", "layout": "vertical",
                "width": "28px", "height": "28px",
                "cornerRadius": "14px",
                "backgroundColor": COLOR_PRIMARY,
                "justifyContent": "center", "alignItems": "center",
                "flex": 0,
                "contents": [
                    {"type": "text", "text": num, "size": "xs",
                     "color": "#FFFFFF", "align": "center"},
                ],
            },
            {
                "type": "box", "layout": "vertical", "flex": 5,
                "contents": [
                    {"type": "text", "text": title,
                     "size": "sm", "weight": "bold", "color": COLOR_TEXT},
                    {"type": "text", "text": desc,
                     "size": "xs", "color": COLOR_TEXT_SUB, "wrap": True},
                ],
            },
        ],
    }


def _camera_button(label: str) -> dict:
    return {
        "type": "button", "style": "primary", "color": COLOR_PRIMARY,
        "height": "sm",
        "action": {"type": "camera", "label": label},
    }


def _camera_roll_button(label: str) -> dict:
    return {
        "type": "button", "style": "primary", "color": COLOR_SECONDARY,
        "height": "sm",
        "action": {"type": "cameraRoll", "label": label},
    }


# ========================================================
#  格子 1: 📸 拍照記帳
# ========================================================

def build_camera_menu() -> dict:
    """📸 拍照記帳 — 3 卡 Carousel：拍照訣竅 → 辨識流程 → 開始拍照"""
    return {
        "type": "carousel",
        "contents": [
            _camera_card_tips(),
            _camera_card_flow(),
            _camera_card_action(),
        ],
    }


def _camera_card_tips() -> dict:
    """Card 1: 拍照訣竅 — 如何拍出高辨識率的照片"""
    tips = [
        ("💡", "光線充足", "避免陰影遮蔽文字，自然光最佳"),
        ("📐", "平放桌面", "收據平放，鏡頭正對，避免透視歪斜"),
        ("🔍", "對焦清晰", "等對焦完成（框變綠）再按快門"),
        ("📏", "四角入鏡", "收據四個角都要拍進去，不要裁切"),
        ("🖐️", "穩定拍攝", "雙手持穩手機，避免晃動模糊"),
    ]
    tip_rows = []
    for emoji, title, desc in tips:
        tip_rows.append({
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "margin": "sm",
            "contents": [
                {"type": "text", "text": emoji, "size": "sm", "flex": 0},
                {
                    "type": "box", "layout": "vertical", "flex": 5,
                    "contents": [
                        {"type": "text", "text": title,
                         "size": "sm", "weight": "bold", "color": COLOR_TEXT},
                        {"type": "text", "text": desc,
                         "size": "xs", "color": COLOR_TEXT_SUB, "wrap": True},
                    ],
                },
            ],
        })
    return {
        "type": "bubble", "size": "mega",
        "header": _header_box("拍照訣竅", "📸"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text",
                 "text": "拍得好，辨識率更高！掌握以下 5 個訣竅：",
                 "size": "sm", "color": COLOR_TEXT, "wrap": True,
                 "weight": "bold"},
                {"type": "separator", "margin": "md"},
                *tip_rows,
                {"type": "separator", "margin": "md"},
                {"type": "text",
                 "text": "手寫收據也能辨識，但印刷體準確率更高",
                 "size": "xxs", "color": COLOR_TEXT_SUB, "wrap": True,
                 "margin": "sm"},
            ],
        },
    }


def _camera_card_flow() -> dict:
    """Card 2: 辨識流程 — 拍完之後會發生什麼"""
    return {
        "type": "bubble", "size": "mega",
        "header": _header_box("辨識流程", "🤖"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "paddingAll": "16px",
            "contents": [
                {"type": "text",
                 "text": "拍照後，小膳會自動完成以下流程：",
                 "size": "sm", "color": COLOR_TEXT, "wrap": True,
                 "weight": "bold"},
                {"type": "separator", "margin": "md"},
                _step_row("1", "AI 辨識", "自動辨識供應商、日期、品項、金額、統編"),
                _step_row("2", "信心度判定", "🟢 高信心度：直接顯示結果\n🟡 中信心度：標記需確認欄位\n🔴 低信心度：建議重新拍照"),
                _step_row("3", "不清楚？追問", "如果辨識有問題，小膳會告訴你哪裡不清楚，並建議怎麼補拍"),
                _step_row("4", "確認入帳", "確認辨識結果，一鍵入帳！也可手動修改"),
                {"type": "separator", "margin": "md"},
                {"type": "text",
                 "text": "辨識結果會自動備份到雲端 📁",
                 "size": "xs", "color": COLOR_PRIMARY, "wrap": True,
                 "margin": "sm"},
            ],
        },
    }


def _camera_card_action() -> dict:
    """Card 3: 開始拍照 — 相機/相簿按鈕"""
    return {
        "type": "bubble", "size": "mega",
        "header": _header_box("開始拍照", "📷"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "paddingAll": "16px",
            "contents": [
                {"type": "text",
                 "text": "準備好了嗎？選擇拍照方式：",
                 "size": "sm", "color": COLOR_TEXT, "wrap": True,
                 "weight": "bold"},
                {"type": "separator", "margin": "md"},
                {
                    "type": "box", "layout": "vertical", "spacing": "md",
                    "margin": "lg",
                    "contents": [
                        _camera_button("📷 開啟相機拍照"),
                        _camera_roll_button("🖼️ 從相簿選取照片"),
                    ],
                },
                {"type": "separator", "margin": "lg"},
                {"type": "text",
                 "text": "也可以直接傳照片給小膳，不用按按鈕！",
                 "size": "xs", "color": COLOR_TEXT_SUB, "wrap": True,
                 "margin": "md", "align": "center"},
                {"type": "box", "layout": "vertical", "margin": "md",
                 "spacing": "xs",
                 "contents": [
                     {"type": "text", "text": "⚠️ 拍照前確認清單：",
                      "size": "xs", "color": COLOR_SECONDARY,
                      "weight": "bold"},
                     {"type": "text",
                      "text": "✓ 光線充足  ✓ 收據平放  ✓ 四角入鏡  ✓ 對焦清晰",
                      "size": "xxs", "color": COLOR_TEXT_SUB, "wrap": True},
                 ]},
            ],
        },
    }


# ========================================================
#  格子 2: 📁 財務資料提供和確認（v2.2 Carousel 4 卡）
# ========================================================

def build_finance_upload_menu() -> dict:
    return {
        "type": "carousel",
        "contents": [
            _finance_upload_card_intro(),
            _finance_upload_card_upload(),
            _finance_upload_card_list(),
            _finance_upload_card_confirm(),
        ],
    }


def _finance_upload_card_intro() -> dict:
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("財務資料提供和確認", "📁"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "上傳會計文件，小膳自動分類歸檔！",
                 "size": "sm", "color": COLOR_TEXT, "wrap": True, "weight": "bold"},
                {"type": "separator", "margin": "md"},
                _step_row("1", "上傳文件", "傳 Excel 或 PDF 給小膳"),
                _step_row("2", "自動分類", "依檔名自動歸入八大循環分類"),
                _step_row("3", "確認歸檔", "確認分類，文件同步到雲端"),
                {"type": "separator", "margin": "md"},
                {"type": "text", "text": "👉 直接傳 Excel/PDF 給小膳即可",
                 "size": "xs", "color": COLOR_PRIMARY, "align": "center",
                 "margin": "md"},
            ],
        },
    }


def _finance_upload_card_upload() -> dict:
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("上傳文件", "📋"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "支援格式：Excel (.xlsx/.xls)、PDF",
                 "size": "sm", "color": COLOR_TEXT, "wrap": True},
                {"type": "separator", "margin": "md"},
                {"type": "text", "text": "八大循環分類：",
                 "size": "xs", "weight": "bold", "color": COLOR_TEXT, "margin": "sm"},
                {"type": "text", "text": "• 薪資表 → 人力資源循環",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "text", "text": "• 租約/合約 → 一般/收入循環",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "text", "text": "• 採購單 → 支出循環",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "text", "text": "• 折舊表 → 固定資產循環",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "separator", "margin": "md"},
                {"type": "text",
                 "text": "💡 直接傳檔案給小膳，會自動偵測分類！",
                 "size": "xs", "color": COLOR_PRIMARY, "wrap": True,
                 "margin": "sm"},
            ],
        },
    }


def _finance_upload_card_list() -> dict:
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("已上傳文件", "📂"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "查看已上傳的文件和分類",
                 "size": "sm", "color": COLOR_TEXT, "wrap": True},
                {"type": "text", "text": "• 本月所有財務文件清單",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "text", "text": "• 按循環分類瀏覽",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "text", "text": "• 搜尋特定文件",
                 "size": "xs", "color": COLOR_TEXT_SUB},
            ],
        },
        "footer": {
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "paddingAll": "12px",
            "contents": [
                _action_button("📂 查看本月文件",
                               "action=finance_docs&cmd=list",
                               display_text="📂 本月文件"),
                _action_button("🔍 搜尋文件",
                               "action=finance_docs&cmd=search",
                               color=COLOR_SECONDARY,
                               display_text="🔍 搜尋文件"),
            ],
        },
    }


def _finance_upload_card_confirm() -> dict:
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("勾稽與確認", "✅"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "確認文件完整性",
                 "size": "sm", "color": COLOR_TEXT, "wrap": True},
                {"type": "text", "text": "• 確認本月所有文件已齊全",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "text", "text": "• 查看各循環文件統計",
                 "size": "xs", "color": COLOR_TEXT_SUB},
            ],
        },
        "footer": {
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "paddingAll": "12px",
            "contents": [
                _action_button("✅ 確認本月資料",
                               "action=finance_docs&cmd=confirm_month",
                               display_text="✅ 確認本月資料"),
                _action_button("📊 文件統計",
                               "action=finance_docs&cmd=summary",
                               color=COLOR_SECONDARY,
                               display_text="📊 文件統計"),
            ],
        },
    }


def build_file_upload_result_flex(doc_info: dict) -> dict:
    """檔案上傳結果 Flex — 顯示分類結果 + 內容分析 + 確認/修改按鈕"""
    doc_id = doc_info["id"]

    # 分類方式中文
    method_labels = {
        "content": "📖 內容分析",
        "filename": "📝 檔名分析",
        "default": "⚙️ 預設分類",
    }
    method = doc_info.get("classification_method", "default")
    method_label = method_labels.get(method, "⚙️ 預設")

    body_rows = [
        _kv_row("📄 歸檔名", doc_info.get("filename", "")),
    ]

    # 如果有原始檔名且不同，顯示
    orig = doc_info.get("original_filename", "")
    if orig and orig != doc_info.get("filename", ""):
        body_rows.append(_kv_row("📎 原檔名", orig))

    body_rows.extend([
        _kv_row("📋 類型", doc_info.get("file_type", "").upper()),
        _kv_row("🏷️ 分類", doc_info.get("category_label", "")),
        _kv_row("🔍 分類依據", method_label),
        _kv_row("📅 月份", doc_info.get("year_month", "")),
    ])

    # 內容關鍵字
    keywords = doc_info.get("content_keywords", [])
    if keywords:
        body_rows.append({"type": "separator", "margin": "sm"})
        body_rows.append({
            "type": "text",
            "text": f"🔑 偵測到：{', '.join(keywords[:6])}",
            "size": "xxs", "color": COLOR_PRIMARY, "wrap": True,
            "margin": "sm",
        })

    # GDrive 路徑
    if doc_info.get("gdrive_path"):
        body_rows.append(_kv_row("☁️ 雲端", doc_info["gdrive_path"]))

    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("檔案已歸檔", "📁"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": body_rows,
        },
        "footer": {
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "paddingAll": "12px",
            "contents": [
                _action_button("✅ 確認",
                               f"action=file_confirm&id={doc_id}",
                               display_text="✅ 確認分類"),
                _action_button("🏷️ 修改分類",
                               f"action=file_reclassify&id={doc_id}",
                               color=COLOR_SECONDARY,
                               display_text="🏷️ 修改分類"),
            ],
        },
    }


def build_file_reclassify_flex(doc_id: int) -> dict:
    """分類選擇 Flex — 八大循環按鈕"""
    categories = [
        ("收入循環", "revenue"), ("支出循環", "expenditure"),
        ("人力資源", "payroll"), ("生產循環", "production"),
        ("融資循環", "financing"), ("投資循環", "investment"),
        ("固定資產", "fixed_asset"), ("一般循環", "general"),
    ]
    buttons = []
    colors = [COLOR_PRIMARY, COLOR_SECONDARY]
    for i, (label, cat) in enumerate(categories):
        buttons.append(
            _action_button(
                label,
                f"action=file_set_category&id={doc_id}&cat={cat}",
                color=colors[i % 2],
                display_text=f"分類：{label}",
            )
        )
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box(f"修改分類（#{doc_id}）", "🏷️"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "12px",
            "contents": buttons,
        },
    }


def build_finance_doc_list_flex(docs: list, year_month: str) -> dict:
    """財務文件清單 Flex"""
    if not docs:
        return {
            "type": "bubble", "size": "mega",
            "header": _header_box(f"{year_month} 文件清單", "📂"),
            "body": {
                "type": "box", "layout": "vertical", "paddingAll": "16px",
                "contents": [
                    {"type": "text", "text": "📭 本月尚未上傳任何文件",
                     "size": "sm", "color": COLOR_TEXT_SUB, "wrap": True},
                    {"type": "text",
                     "text": "直接傳 Excel/PDF 給小膳即可開始！",
                     "size": "xs", "color": COLOR_PRIMARY, "wrap": True,
                     "margin": "md"},
                ],
            },
        }

    rows = []
    for d in docs[:15]:
        status_icon = "✅" if d.get("status") == "confirmed" else "⏳"
        rows.append({
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "margin": "sm",
            "contents": [
                {"type": "text", "text": status_icon, "size": "sm", "flex": 0},
                {"type": "text", "text": d.get("filename", ""),
                 "size": "xxs", "color": COLOR_TEXT, "flex": 4, "wrap": True},
                {"type": "text",
                 "text": _category_short_label(d.get("doc_category", "")),
                 "size": "xxs", "color": COLOR_TEXT_SUB, "flex": 2,
                 "align": "end"},
            ],
        })

    return {
        "type": "bubble", "size": "mega",
        "header": _header_box(f"{year_month} 文件（{len(docs)} 件）", "📂"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "xs",
            "paddingAll": "14px",
            "contents": rows,
        },
    }


def _category_short_label(cat: str) -> str:
    labels = {
        "revenue": "收入", "expenditure": "支出", "payroll": "薪資",
        "production": "生產", "financing": "融資", "investment": "投資",
        "fixed_asset": "資產", "general": "一般",
    }
    return labels.get(cat, cat)


def build_finance_doc_summary_flex(summary: dict) -> dict:
    """財務文件統計 Flex"""
    ym = summary.get("year_month", "")
    total = summary.get("total", 0)
    confirmed = summary.get("confirmed", 0)
    categories = summary.get("categories", {})

    rows = [
        _kv_row("📁 總文件數", f"{total} 件"),
        _kv_row("✅ 已確認", f"{confirmed} 件"),
        {"type": "separator", "margin": "md"},
    ]

    cat_labels = {
        "revenue": "收入循環", "expenditure": "支出循環",
        "payroll": "人力資源", "production": "生產循環",
        "financing": "融資循環", "investment": "投資循環",
        "fixed_asset": "固定資產", "general": "一般循環",
    }
    for cat, label in cat_labels.items():
        info = categories.get(cat, {})
        cnt = info.get("count", 0)
        if cnt > 0:
            rows.append(_kv_row(f"  {label}", f"{cnt} 件"))

    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box(f"{ym} 文件統計", "📊"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": rows,
        },
    }


# (保留舊 build_finance_menu 作為相容別名)
def build_finance_menu() -> dict:
    return build_finance_upload_menu()


# ========================================================
#  格子 3: 🛒 採購管理
# ========================================================

def build_purchase_menu(pending_count: int = 0) -> dict:
    badge = f" [{pending_count} 筆]" if pending_count else ""
    return {
        "type": "bubble", "size": "mega",
        "header": _header_box("採購管理", "🛒"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "paddingAll": "16px",
            "contents": [
                {"type": "text",
                 "text": "管理每日採購、比價、追蹤供應商！",
                 "size": "sm", "color": COLOR_TEXT, "weight": "bold", "wrap": True},
                {"type": "separator", "margin": "md"},
                _step_row("1", "拍照上傳", "拍收據後小膳自動辨識（用「拍照記帳」）"),
                _step_row("2", "確認待處理", "檢查 OCR 辨識結果，確認或修改"),
                _step_row("3", "查看比價", "進貨價 vs 市場行情，偏離標紅"),
                {"type": "separator", "margin": "md"},
                {"type": "text",
                 "text": f"📝 待處理憑證{badge}",
                 "size": "sm", "color": COLOR_TEXT, "weight": "bold"},
                _action_button("📝 查看待處理",
                               "action=purchase&cmd=pending",
                               display_text="📝 待處理"),
                {
                    "type": "box", "layout": "horizontal", "spacing": "sm",
                    "margin": "sm",
                    "contents": [
                        _action_button("📊 市場行情",
                                       "action=purchase&cmd=market",
                                       color=COLOR_SECONDARY,
                                       display_text="📊 市場行情"),
                        _action_button("🏪 供應商",
                                       "action=purchase&cmd=suppliers",
                                       color=COLOR_SECONDARY,
                                       display_text="🏪 供應商"),
                    ],
                },
                _action_button("📦 食材價格對照表",
                               "action=purchase&cmd=price_compare",
                               color=COLOR_BLUE,
                               display_text="📦 食材價格對照表"),
            ],
        },
    }


# ========================================================
#  格子 4: 🍽️ 菜單企劃（Carousel 3 卡）
# ========================================================

def build_menu_plan_menu() -> dict:
    return {
        "type": "carousel",
        "contents": [
            _menu_card_intro(),
            _menu_card_current(),
            _menu_card_image(),
            _menu_card_cost(),
        ],
    }


def _menu_card_intro() -> dict:
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("菜單企劃", "🍽️"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "AI 幫你規劃菜單、算成本、做文宣！",
                 "size": "sm", "color": COLOR_TEXT, "wrap": True, "weight": "bold"},
                {"type": "separator", "margin": "md"},
                _step_row("1", "查看/編輯菜單", "確認本月每日菜色安排"),
                _step_row("2", "生成菜色圖片", "輸入菜名，AI 生成精美文宣圖"),
                _step_row("3", "食材成本試算", "輸入菜名或食材，即時算出成本"),
                {"type": "separator", "margin": "md"},
                {"type": "text", "text": "👉 滑動選擇功能",
                 "size": "xs", "color": COLOR_PRIMARY, "align": "center",
                 "margin": "md"},
            ],
        },
    }


def _menu_card_current() -> dict:
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("本月菜單確認", "🍽️"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "查看/確認本月菜單安排",
                 "size": "sm", "color": COLOR_TEXT, "wrap": True},
                {"type": "text", "text": "AI 會幫您：",
                 "size": "xs", "color": COLOR_TEXT_SUB, "margin": "md"},
                {"type": "text", "text": "✅ 確認每道菜的食材清單",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "text", "text": "✅ 計算每道菜的食材成本",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "text", "text": "✅ 檢查食材是否有供應商",
                 "size": "xs", "color": COLOR_TEXT_SUB},
            ],
        },
        "footer": {
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "paddingAll": "12px",
            "contents": [
                _action_button("📋 查看菜單",
                               "action=menu&cmd=view_current",
                               display_text="📋 查看本月菜單"),
                _action_button("✏️ 編輯菜單",
                               "action=menu&cmd=edit",
                               color=COLOR_SECONDARY,
                               display_text="✏️ 編輯菜單"),
            ],
        },
    }


def _menu_card_image() -> dict:
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("菜色文宣圖片", "🎨"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "兩種方式生成行銷海報：",
                 "size": "sm", "color": COLOR_TEXT, "wrap": True},
                {"type": "text", "text": "📸 上傳實拍照片 → AI 增強 + 文案",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "text", "text": "✍️ 輸入菜名 → AI 生成參考圖",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "text", "text": "📋 兩種都附行銷文案和 hashtags",
                 "size": "xs", "color": COLOR_TEXT_SUB},
            ],
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "12px",
            "contents": [
                _action_button("📸 上傳菜色照片",
                               "action=menu_photo_upload",
                               display_text="📸 上傳菜色照片"),
                _action_button("✍️ 輸入菜名生成",
                               "action=menu&cmd=gen_image",
                               color=COLOR_SECONDARY,
                               display_text="✍️ 輸入菜名生成"),
            ],
        },
    }


def _menu_card_cost() -> dict:
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("食材成本試算", "🧮"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "輸入一道菜的食材",
                 "size": "sm", "color": COLOR_TEXT, "wrap": True},
                {"type": "text", "text": "自動計算：",
                 "size": "xs", "color": COLOR_TEXT_SUB, "margin": "md"},
                {"type": "text", "text": "💵 食材成本（最新進貨價）",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "text", "text": "📊 成本佔售價比例",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "text", "text": "📈 與上月同菜比較",
                 "size": "xs", "color": COLOR_TEXT_SUB},
            ],
        },
        "footer": {
            "type": "box", "layout": "vertical", "paddingAll": "12px",
            "contents": [
                _action_button("🧮 開始試算",
                               "action=menu&cmd=cost_calc",
                               display_text="🧮 食材成本試算"),
            ],
        },
    }


# ========================================================
#  格子 5: 📊 報表生成（v2.2 Carousel 3 卡）
# ========================================================

def build_reports_menu() -> dict:
    return {
        "type": "carousel",
        "contents": [
            _reports_card_intro(),
            _reports_card_financial(),
            _reports_card_export(),
        ],
    }


def _reports_card_intro() -> dict:
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("報表生成", "📊"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "生成財務報表或匯出數據！",
                 "size": "sm", "color": COLOR_TEXT, "wrap": True, "weight": "bold"},
                {"type": "separator", "margin": "md"},
                _step_row("1", "選擇報表類型", "四大報表或匯出功能"),
                _step_row("2", "選擇期間", "本月、本期、上期"),
                _step_row("3", "自動生成", "生成報表 + 雲端同步"),
                {"type": "separator", "margin": "md"},
                {"type": "text", "text": "👉 滑動選擇功能",
                 "size": "xs", "color": COLOR_PRIMARY, "align": "center",
                 "margin": "md"},
            ],
        },
    }


def _reports_card_financial() -> dict:
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("四大財務報表", "📊"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "依財政部中小企業會計準則",
                 "size": "xs", "color": COLOR_TEXT_SUB, "wrap": True},
                {"type": "separator", "margin": "sm"},
                _action_button("📊 資產負債表",
                               "action=gen_report&type=balance_sheet",
                               display_text="📊 資產負債表"),
                _action_button("📊 損益表",
                               "action=gen_report&type=income_statement",
                               color=COLOR_SECONDARY,
                               display_text="📊 損益表"),
                _action_button("📊 現金流量表",
                               "action=gen_report&type=cash_flow",
                               display_text="📊 現金流量表"),
                _action_button("📊 權益變動表",
                               "action=gen_report&type=equity_changes",
                               color=COLOR_SECONDARY,
                               display_text="📊 權益變動表"),
            ],
        },
    }


def _reports_card_export() -> dict:
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("匯出功能", "📤"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "各類報表匯出",
                 "size": "xs", "color": COLOR_TEXT_SUB, "wrap": True},
                {"type": "separator", "margin": "sm"},
                _action_button("📋 月報表（Excel）",
                               "action=export&type=monthly",
                               display_text="📋 月報表"),
                _action_button("📋 年報表（Excel）",
                               "action=export&type=annual",
                               color=COLOR_SECONDARY,
                               display_text="📋 年報表"),
                _action_button("🏛️ 稅務申報檔",
                               "action=export&type=mof_txt",
                               color=COLOR_BLUE,
                               display_text="🏛️ 稅務申報"),
                _action_button("🧾 會計系統匯出",
                               "action=export&type=accounting",
                               color=COLOR_BLUE,
                               display_text="🧾 會計匯出"),
                _action_button("📄 經手人憑證",
                               "action=export&type=handler_cert",
                               color=COLOR_SECONDARY,
                               display_text="📄 經手人憑證"),
                _action_button("🧾 扣抵分析",
                               "action=tax_deduction_stats",
                               color=COLOR_SECONDARY,
                               display_text="🧾 扣抵分析"),
            ],
        },
    }


def build_report_period_picker(report_type: str) -> dict:
    """四大報表期間選擇 Flex"""
    now = datetime.now()
    ym = now.strftime("%Y-%m")
    year = now.year
    month = now.month

    # 上個月
    if month == 1:
        prev_ym = f"{year - 1}-12"
    else:
        prev_ym = f"{year}-{month - 1:02d}"

    type_labels = {
        "balance_sheet": "資產負債表",
        "income_statement": "損益表",
        "cash_flow": "現金流量表",
        "equity_changes": "權益變動表",
    }
    label = type_labels.get(report_type, report_type)

    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box(f"選擇{label}期間", "📊"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                _action_button(
                    f"本月 {ym}",
                    f"action=do_gen_report&type={report_type}&period={ym}",
                    display_text=f"生成{label} {ym}"),
                _action_button(
                    f"上月 {prev_ym}",
                    f"action=do_gen_report&type={report_type}&period={prev_ym}",
                    color=COLOR_SECONDARY,
                    display_text=f"生成{label} {prev_ym}"),
            ],
        },
    }


# 保留舊 build_export_menu 作為相容別名
def build_export_menu() -> dict:
    return build_reports_menu()


# ========================================================
#  格子 6: ❓ 使用說明（Carousel 4 卡）
# ========================================================

def build_guide_menu() -> dict:
    return {
        "type": "carousel",
        "contents": [
            _guide_card_quickstart(),
            _guide_card_camera_steps(),
            _guide_card_finance_group(),
            _guide_card_features(),
            _guide_card_faq(),
            _guide_card_info(),
        ],
    }


def _guide_card_quickstart() -> dict:
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("快速入門", "🚀"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "歡迎使用小膳！只要 3 步就能開始：",
                 "size": "sm", "color": COLOR_TEXT, "weight": "bold", "wrap": True},
                {"type": "separator", "margin": "md"},
                _step_row("1", "拍照記帳", "點選下方選單「拍照記帳」→ 按「拍照」或「從相簿選」拍發票"),
                _step_row("2", "確認記錄", "小膳 AI 辨識完成後，檢查結果 → 按「確認」"),
                _step_row("3", "查看報表", "到「報表生成」隨時看累計花費和分類統計"),
                {"type": "separator", "margin": "md"},
                {"type": "text",
                 "text": "就這麼簡單！拍照就能記帳 📸",
                 "size": "xs", "color": COLOR_TEXT_SUB, "wrap": True,
                 "margin": "md"},
            ],
        },
    }


def _guide_card_camera_steps() -> dict:
    """拍照記帳詳細步驟指南"""
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("拍照記帳教學", "📸"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "完整操作流程：",
                 "size": "sm", "color": COLOR_TEXT, "weight": "bold"},
                {"type": "separator", "margin": "sm"},
                _step_row("1", "開啟拍照功能",
                          "點選下方六宮格的「📸 拍照記帳」"),
                _step_row("2", "選擇拍照方式",
                          "按「📷 拍照」開啟相機，或「🖼️ 從相簿選」選舊照片"),
                _step_row("3", "等待 AI 辨識",
                          "小膳分析發票內容（約 3-5 秒）"),
                _step_row("4", "確認或修改",
                          "檢查供應商、金額、品項 → 按「確認」或「修改」"),
                _step_row("5", "自動歸檔",
                          "確認後自動存到雲端 + 更新統計"),
                {"type": "separator", "margin": "md"},
                {"type": "text",
                 "text": "💡 拍照小技巧：\n• 發票平放桌面\n• 確保光線充足\n• 避免手影遮擋\n• 整張發票入鏡",
                 "size": "xxs", "color": COLOR_TEXT_SUB, "wrap": True,
                 "margin": "sm"},
            ],
        },
    }


def _guide_card_finance_group() -> dict:
    """財務群組使用指南"""
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("群組 vs 一對一", "👥"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "📌 邀 Bot 進財務群組",
                 "size": "sm", "weight": "bold", "color": COLOR_TEXT},
                {"type": "text", "text": "• 多人需要看到上傳確認結果",
                 "size": "xs", "color": COLOR_TEXT_SUB, "wrap": True},
                {"type": "text", "text": "• 共同維護每月財務文件",
                 "size": "xs", "color": COLOR_TEXT_SUB, "wrap": True},
                {"type": "text", "text": "• 拍照記帳、採購管理",
                 "size": "xs", "color": COLOR_TEXT_SUB, "wrap": True},
                {"type": "separator", "margin": "md"},
                {"type": "text", "text": "📌 用 Bot 一對一",
                 "size": "sm", "weight": "bold", "color": COLOR_TEXT},
                {"type": "text", "text": "• 個人查帳、生成報表",
                 "size": "xs", "color": COLOR_TEXT_SUB, "wrap": True},
                {"type": "text", "text": "• 上傳私密薪資文件",
                 "size": "xs", "color": COLOR_TEXT_SUB, "wrap": True},
                {"type": "text", "text": "• 匯出稅務或會計檔案",
                 "size": "xs", "color": COLOR_TEXT_SUB, "wrap": True},
                {"type": "separator", "margin": "md"},
                {"type": "text",
                 "text": "💡 直接傳檔案給小膳，自動分類歸檔！",
                 "size": "xs", "color": COLOR_PRIMARY, "wrap": True,
                 "margin": "sm"},
            ],
        },
    }


def _guide_card_features() -> dict:
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("各功能操作說明", "📖"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                _guide_feature_row("📸", "拍照記帳",
                                   "點選 → 按「拍照」或「相簿」→ 等辨識 → 確認"),
                {"type": "separator", "margin": "sm"},
                _guide_feature_row("📁", "財務資料",
                                   "傳 Excel/PDF → 自動分類 → 確認 → 歸檔"),
                {"type": "separator", "margin": "sm"},
                _guide_feature_row("🛒", "採購管理",
                                   "點選 → 查待處理/市場行情/供應商/比價"),
                {"type": "separator", "margin": "sm"},
                _guide_feature_row("🍽️", "菜單企劃",
                                   "點選 → 滑動選：查菜單/生成圖片/成本試算"),
                {"type": "separator", "margin": "sm"},
                _guide_feature_row("📊", "報表生成",
                                   "四大財務報表 + 月報/年報/稅務匯出"),
            ],
        },
    }


def _guide_feature_row(emoji: str, title: str, desc: str) -> dict:
    return {
        "type": "box", "layout": "horizontal", "spacing": "md",
        "contents": [
            {"type": "text", "text": emoji, "size": "lg", "flex": 0},
            {
                "type": "box", "layout": "vertical", "flex": 5,
                "contents": [
                    {"type": "text", "text": title,
                     "size": "sm", "weight": "bold", "color": COLOR_TEXT},
                    {"type": "text", "text": desc,
                     "size": "xxs", "color": COLOR_TEXT_SUB, "wrap": True},
                ],
            },
        ],
    }


def _guide_card_faq() -> dict:
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("常見問題", "❓"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "paddingAll": "16px",
            "contents": [
                _faq_item("辨識錯誤怎麼辦？",
                          "點「修改 #編號」可逐項更正"),
                {"type": "separator", "margin": "sm"},
                _faq_item("菜市場沒有發票？",
                          "拍攝收據，系統會產生「經手人證明」"),
                {"type": "separator", "margin": "sm"},
                _faq_item("可以補登之前的帳嗎？",
                          "可以，拍照時選相簿內舊照片即可"),
                {"type": "separator", "margin": "sm"},
                _faq_item("怎麼匯出報表？",
                          "點選「報表生成」選擇報表類型"),
                {"type": "separator", "margin": "sm"},
                _faq_item("上傳的檔案去哪了？",
                          "自動歸到 GDrive 對應月份資料夾"),
                {"type": "separator", "margin": "sm"},
                _faq_item("可以上傳哪些格式？",
                          "Excel (.xlsx/.xls) 和 PDF"),
            ],
        },
    }


def _faq_item(q: str, a: str) -> dict:
    return {
        "type": "box", "layout": "vertical", "spacing": "xs",
        "contents": [
            {"type": "text", "text": f"Q: {q}",
             "size": "xs", "weight": "bold", "color": COLOR_TEXT, "wrap": True},
            {"type": "text", "text": f"A: {a}",
             "size": "xs", "color": COLOR_TEXT_SUB, "wrap": True},
        ],
    }


def _guide_card_info() -> dict:
    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box("可查看的資訊", "👀"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "📌 即時查看",
                 "size": "sm", "weight": "bold", "color": COLOR_TEXT},
                {"type": "text", "text": "• 本月累計花費",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "text", "text": "• 待確認的 OCR 辨識結果",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "text", "text": "• 今日農產品市場行情",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "separator", "margin": "md"},
                {"type": "text", "text": "📌 定期報表",
                 "size": "sm", "weight": "bold", "color": COLOR_TEXT},
                {"type": "text", "text": "• 月報表（每月自動推送）",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "text", "text": "• 食材價格趨勢",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "separator", "margin": "md"},
                {"type": "text", "text": "📌 可覈對項目",
                 "size": "sm", "weight": "bold", "color": COLOR_TEXT},
                {"type": "text", "text": "• 發票金額 vs OCR 辨識",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "text", "text": "• 進貨價 vs 市場行情",
                 "size": "xs", "color": COLOR_TEXT_SUB},
                {"type": "text", "text": "• 菜單食材 vs 實際採購",
                 "size": "xs", "color": COLOR_TEXT_SUB},
            ],
        },
    }


# ========================================================
#  動態內容 Flex — 報表結果、價格對照等
# ========================================================

def build_stats_flex(year_month: str, stats: dict) -> dict:
    """統計摘要 Flex"""
    total = stats.get("total", 0) or 0
    pending = stats.get("pending", 0) or 0
    confirmed = stats.get("confirmed", 0) or 0
    exported = stats.get("exported", 0) or 0
    amount = stats.get("total_amount", 0) or 0
    tax = stats.get("total_tax", 0) or 0

    return {
        "type": "bubble", "size": "mega",
        "header": _header_box(f"{year_month} 統計", "📊"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                _kv_row("📝 總記錄", f"{total} 筆"),
                _kv_row("⏳ 待確認", f"{pending}"),
                _kv_row("✅ 已確認", f"{confirmed}"),
                _kv_row("📦 已匯出", f"{exported}"),
                {"type": "separator", "margin": "md"},
                _kv_row("💰 總金額", f"${amount:,.0f}"),
                _kv_row("🧾 進項稅額", f"${tax:,.0f}"),
            ],
        },
    }


def build_price_compare_flex(comparisons: list[dict]) -> dict:
    """食材價格對照表 Flex"""
    rows = []
    # 表頭
    rows.append({
        "type": "box", "layout": "horizontal",
        "contents": [
            {"type": "text", "text": "品名", "size": "xs",
             "weight": "bold", "color": COLOR_TEXT, "flex": 3},
            {"type": "text", "text": "進貨", "size": "xs",
             "weight": "bold", "color": COLOR_TEXT, "flex": 2, "align": "end"},
            {"type": "text", "text": "市場", "size": "xs",
             "weight": "bold", "color": COLOR_TEXT, "flex": 2, "align": "end"},
            {"type": "text", "text": "偏差", "size": "xs",
             "weight": "bold", "color": COLOR_TEXT, "flex": 2, "align": "end"},
        ],
    })
    rows.append({"type": "separator", "margin": "sm"})

    for item in comparisons[:15]:
        name = item.get("name", "")
        purchase = item.get("purchase_price", 0)
        market = item.get("market_price", 0)
        deviation = item.get("deviation_pct", 0)
        is_alert = abs(deviation) > 30

        color = COLOR_RED if is_alert else COLOR_TEXT
        prefix = "🔴 " if is_alert else ""

        rows.append({
            "type": "box", "layout": "horizontal", "margin": "sm",
            "contents": [
                {"type": "text", "text": f"{prefix}{name}", "size": "xxs",
                 "color": color, "flex": 3, "wrap": True},
                {"type": "text", "text": f"${purchase:.0f}", "size": "xxs",
                 "color": color, "flex": 2, "align": "end"},
                {"type": "text", "text": f"${market:.0f}", "size": "xxs",
                 "color": COLOR_TEXT_SUB, "flex": 2, "align": "end"},
                {"type": "text", "text": f"{deviation:+.0f}%", "size": "xxs",
                 "color": color, "flex": 2, "align": "end"},
            ],
        })

    alert_count = sum(1 for c in comparisons if abs(c.get("deviation_pct", 0)) > 30)
    if alert_count:
        rows.append({"type": "separator", "margin": "md"})
        rows.append({
            "type": "text",
            "text": f"⚠️ {alert_count} 項偏差超過 30%，建議議價",
            "size": "xxs", "color": COLOR_RED, "wrap": True, "margin": "sm",
        })

    return {
        "type": "bubble", "size": "mega",
        "header": _header_box("食材價格對照表（本月）", "📦"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "xs",
            "paddingAll": "14px",
            "contents": rows,
        },
    }


def build_supplier_list_flex(suppliers: list[dict]) -> dict:
    """供應商清單 Flex"""
    rows = []
    for s in suppliers[:20]:
        has_inv = s.get("has_uniform_invoice", 1)
        icon = "📄" if has_inv else "📝"
        tax_id = s.get("tax_id", "") or "無統編"
        rows.append({
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "margin": "sm",
            "contents": [
                {"type": "text", "text": icon, "size": "sm", "flex": 0},
                {"type": "text", "text": s["name"], "size": "xs",
                 "color": COLOR_TEXT, "flex": 3},
                {"type": "text", "text": tax_id, "size": "xxs",
                 "color": COLOR_TEXT_SUB, "flex": 2, "align": "end"},
            ],
        })

    return {
        "type": "bubble", "size": "mega",
        "header": _header_box(f"供應商（{len(suppliers)} 家）", "🏪"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "xs",
            "paddingAll": "14px",
            "contents": rows if rows else [
                {"type": "text", "text": "尚未建立供應商資料",
                 "size": "sm", "color": COLOR_TEXT_SUB},
            ],
        },
    }


def build_pending_list_flex(pendings: list[dict]) -> dict:
    """待處理憑證清單 Flex"""
    if not pendings:
        return {
            "type": "bubble", "size": "mega",
            "header": _header_box("待處理憑證", "📝"),
            "body": {
                "type": "box", "layout": "vertical", "paddingAll": "16px",
                "contents": [
                    {"type": "text", "text": "📭 目前沒有待處理的記錄",
                     "size": "sm", "color": COLOR_TEXT_SUB, "wrap": True},
                ],
            },
        }

    rows = []
    for p in pendings[:10]:
        rows.append({
            "type": "box", "layout": "vertical", "spacing": "xs",
            "margin": "md",
            "contents": [
                {
                    "type": "box", "layout": "horizontal",
                    "contents": [
                        {"type": "text",
                         "text": f"#{p['id']} | {p.get('purchase_date', '')}",
                         "size": "xs", "weight": "bold", "color": COLOR_TEXT,
                         "flex": 4},
                        {"type": "text",
                         "text": f"${p.get('total_amount', 0):,.0f}",
                         "size": "xs", "color": COLOR_PRIMARY,
                         "flex": 2, "align": "end"},
                    ],
                },
                {"type": "text",
                 "text": p.get("supplier_name", "未知供應商"),
                 "size": "xxs", "color": COLOR_TEXT_SUB},
                {
                    "type": "box", "layout": "horizontal", "spacing": "sm",
                    "margin": "sm",
                    "contents": [
                        _action_button("✅ 確認", f"action=confirm&id={p['id']}",
                                       color=COLOR_PRIMARY),
                        _action_button("✏️ 修改", f"action=edit&id={p['id']}",
                                       color=COLOR_SECONDARY),
                        _action_button("❌ 捨棄", f"action=discard&id={p['id']}",
                                       color=COLOR_RED),
                    ],
                },
            ],
        })
        if p != pendings[-1] and pendings.index(p) < 9:
            rows.append({"type": "separator", "margin": "sm"})

    return {
        "type": "bubble", "size": "mega",
        "header": _header_box(f"待處理（{len(pendings)} 筆）", "📝"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "xs",
            "paddingAll": "14px",
            "contents": rows,
        },
    }


def build_export_period_picker(export_type: str) -> dict:
    """匯出期間選擇 Flex"""
    now = datetime.now()
    year = now.year
    month = now.month

    # 當前期
    if month % 2 == 1:
        cur_start, cur_end = month, month + 1
    else:
        cur_start, cur_end = month - 1, month

    # 上一期
    if cur_start <= 2:
        prev_start, prev_end = 11, 12
        prev_year = year - 1
    else:
        prev_start = cur_start - 2
        prev_end = cur_end - 2
        prev_year = year

    type_labels = {
        "monthly": "月報表", "annual": "年報表",
        "mof_txt": "稅務申報", "accounting": "會計匯出",
        "handler_cert": "經手人憑證",
    }
    label = type_labels.get(export_type, export_type)

    buttons = [
        _action_button(
            f"本期 {cur_start}-{cur_end}月",
            f"action=do_export&type={export_type}&period={year}-{cur_start:02d}-{cur_end:02d}",
            display_text=f"匯出{label} {cur_start}-{cur_end}月"),
        _action_button(
            f"上期 {prev_start}-{prev_end}月",
            f"action=do_export&type={export_type}&period={prev_year}-{prev_start:02d}-{prev_end:02d}",
            color=COLOR_SECONDARY,
            display_text=f"匯出{label} {prev_start}-{prev_end}月"),
    ]

    # 月報和年報加上「本月」選項
    if export_type in ("monthly", "annual"):
        ym = now.strftime("%Y-%m")
        buttons.insert(0, _action_button(
            f"本月 {ym}",
            f"action=do_export&type={export_type}&period={ym}",
            display_text=f"匯出{label} {ym}"))

    return {
        "type": "bubble", "size": "kilo",
        "header": _header_box(f"選擇{label}期間", "📤"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": buttons,
        },
    }


def build_menu_dish_flex(dish_name: str, ingredients: list[str],
                         total_cost: float, description: str = "",
                         image_url: str = "") -> dict:
    """菜色結果卡片"""
    contents = []
    if description:
        contents.append({"type": "text", "text": description,
                         "size": "sm", "color": COLOR_TEXT, "wrap": True})
    contents.append({"type": "separator", "margin": "md"})
    contents.append({"type": "text", "text": "食材清單：",
                     "size": "xs", "weight": "bold", "color": COLOR_TEXT,
                     "margin": "md"})
    for ing in ingredients[:10]:
        contents.append({"type": "text", "text": f"• {ing}",
                         "size": "xs", "color": COLOR_TEXT_SUB})
    contents.append({"type": "separator", "margin": "md"})
    contents.append(_kv_row("💵 預估成本", f"${total_cost:,.0f}"))

    bubble = {
        "type": "bubble", "size": "mega",
        "header": _header_box(dish_name, "🍽️"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": contents,
        },
    }

    if image_url:
        bubble["hero"] = {
            "type": "image", "url": image_url,
            "size": "full", "aspectRatio": "20:13", "aspectMode": "cover",
        }

    return bubble


def build_tax_deduction_summary_flex(stats: dict) -> dict:
    """扣抵分析 Flex — 圓餅圖式顯示可扣抵/不可扣抵統計"""
    d_count = stats.get("deductible_count", 0)
    d_amount = stats.get("deductible_amount", 0)
    d_tax = stats.get("deductible_tax", 0)
    nd_count = stats.get("non_deductible_count", 0)
    nd_amount = stats.get("non_deductible_amount", 0)
    nd_tax = stats.get("non_deductible_tax", 0)
    total_count = stats.get("total_count", 0)
    total_amount = stats.get("total_amount", 0)

    # 計算比例
    d_pct = round(d_amount / total_amount * 100, 1) if total_amount else 0
    nd_pct = round(100 - d_pct, 1) if total_amount else 0

    # 進度條模擬（10 格）
    d_bars = round(d_pct / 10)
    bar_visual = "🟢" * d_bars + "🔴" * (10 - d_bars)

    return {
        "type": "bubble", "size": "mega",
        "header": _header_box("扣抵分析", "🧾"),
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": bar_visual,
                 "size": "lg", "align": "center"},
                {"type": "text",
                 "text": f"可扣抵 {d_pct}% / 不可扣抵 {nd_pct}%",
                 "size": "xs", "color": COLOR_TEXT_SUB, "align": "center",
                 "margin": "sm"},
                {"type": "separator", "margin": "md"},
                {"type": "text", "text": "🟢 可扣抵進項",
                 "size": "sm", "weight": "bold", "color": COLOR_PRIMARY,
                 "margin": "md"},
                _kv_row("  筆數", f"{d_count} 筆"),
                _kv_row("  金額", f"${d_amount:,.0f}"),
                _kv_row("  進項稅額", f"${d_tax:,.0f}"),
                {"type": "separator", "margin": "md"},
                {"type": "text", "text": "🔴 不可扣抵",
                 "size": "sm", "weight": "bold", "color": COLOR_RED,
                 "margin": "md"},
                _kv_row("  筆數", f"{nd_count} 筆"),
                _kv_row("  金額", f"${nd_amount:,.0f}"),
                _kv_row("  稅額（成本化）", f"${nd_tax:,.0f}"),
                {"type": "separator", "margin": "md"},
                _kv_row("📊 合計", f"{total_count} 筆 / ${total_amount:,.0f}"),
            ],
        },
    }


def build_menu_marketing_flex(
    original_url: str, enhanced_url: str,
    analysis: dict, copy: dict,
) -> dict:
    """菜色行銷海報 Flex — 增強圖 + 文案"""
    dish_name = analysis.get("dish_name", "菜色")
    tagline = copy.get("tagline", "")
    marketing_copy = copy.get("copy", "")
    hashtags = copy.get("hashtags", [])
    hashtag_text = " ".join(hashtags[:6]) if hashtags else ""

    body_contents = [
        {"type": "text", "text": dish_name,
         "size": "xl", "weight": "bold", "color": COLOR_TEXT},
    ]
    if tagline:
        body_contents.append(
            {"type": "text", "text": tagline,
             "size": "md", "color": COLOR_PRIMARY, "wrap": True, "margin": "sm"})
    if marketing_copy:
        body_contents.append({"type": "separator", "margin": "md"})
        body_contents.append(
            {"type": "text", "text": marketing_copy,
             "size": "sm", "color": COLOR_TEXT, "wrap": True, "margin": "md"})
    if hashtag_text:
        body_contents.append(
            {"type": "text", "text": hashtag_text,
             "size": "xs", "color": COLOR_BLUE, "wrap": True, "margin": "md"})

    # 分析摘要
    style = analysis.get("style", "")
    plating = analysis.get("plating_assessment", "")
    if style or plating:
        body_contents.append({"type": "separator", "margin": "md"})
        if style:
            body_contents.append(
                {"type": "text", "text": f"🎨 風格：{style}",
                 "size": "xs", "color": COLOR_TEXT_SUB, "wrap": True, "margin": "sm"})
        if plating:
            body_contents.append(
                {"type": "text", "text": f"🍽️ 擺盤：{plating}",
                 "size": "xs", "color": COLOR_TEXT_SUB, "wrap": True})

    bubble = {
        "type": "bubble", "size": "mega",
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": body_contents,
        },
        "footer": {
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "paddingAll": "12px",
            "contents": [
                _action_button("🔄 重新生成",
                               "action=menu_photo_regenerate",
                               color=COLOR_SECONDARY,
                               display_text="🔄 重新生成"),
            ],
        },
    }

    # Hero: 增強後的圖片（有的話用增強圖，沒有用原圖）
    hero_url = enhanced_url or original_url
    if hero_url:
        bubble["hero"] = {
            "type": "image", "url": hero_url,
            "size": "full", "aspectRatio": "20:13", "aspectMode": "cover",
        }

    return bubble


# === 輔助 ===

def _kv_row(label: str, value: str) -> dict:
    return {
        "type": "box", "layout": "horizontal", "margin": "sm",
        "contents": [
            {"type": "text", "text": label, "size": "sm",
             "color": COLOR_TEXT, "flex": 4},
            {"type": "text", "text": value, "size": "sm",
             "color": COLOR_TEXT, "flex": 3, "align": "end",
             "weight": "bold"},
        ],
    }
