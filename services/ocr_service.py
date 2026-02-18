"""OCR 雙引擎服務 — PaddleOCR + Gemini VLM 交叉驗證"""

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("shanbot.ocr")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# OCR 門檻（前 200 張較嚴格）
AUTO_PASS_THRESHOLD = 0.85
AUTO_PASS_THRESHOLD_EARLY = 0.90  # 前 200 張
REVIEW_THRESHOLD = 0.60
EARLY_CALIBRATION_COUNT = 200


# === 資料結構 ===

@dataclass
class OcrItem:
    """單一品項"""
    name: str = ""
    quantity: float = 0
    unit: str = ""
    unit_price: float = 0
    amount: float = 0
    is_handwritten: bool = False
    confidence: float = 0


@dataclass
class OcrResult:
    """整張收據辨識結果"""
    supplier_name: str = ""
    supplier_tax_id: str = ""
    invoice_prefix: str = ""
    invoice_number: str = ""
    invoice_type: str = ""
    purchase_date: str = ""
    items: list[OcrItem] = field(default_factory=list)
    subtotal: float = 0
    tax_amount: float = 0
    total_amount: float = 0
    raw_text: str = ""
    confidence: float = 0
    result_level: str = "REJECT"  # AUTO_PASS / REVIEW / REJECT
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# === Gemini VLM 結構化輸出 Schema ===

GEMINI_RECEIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "supplier_name": {"type": "string", "description": "供應商/店家名稱"},
        "supplier_tax_id": {"type": "string", "description": "供應商統一編號（8碼數字）"},
        "invoice_prefix": {"type": "string", "description": "發票字軌（2個英文字母）"},
        "invoice_number": {"type": "string", "description": "發票號碼（8碼數字）"},
        "invoice_type": {"type": "string", "enum": ["三聯式", "二聯式", "電子發票", "免用發票", "收據", "unknown"]},
        "purchase_date": {"type": "string", "description": "日期 YYYY-MM-DD 格式"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string"},
                    "unit_price": {"type": "number"},
                    "amount": {"type": "number"},
                    "is_handwritten": {"type": "boolean"},
                },
                "required": ["name", "amount"],
            },
        },
        "subtotal": {"type": "number", "description": "未稅小計"},
        "tax_amount": {"type": "number", "description": "稅額（5%營業稅）"},
        "total_amount": {"type": "number", "description": "含稅總計"},
    },
    "required": ["items", "total_amount"],
}


# === PaddleOCR 引擎 ===

_paddle_engine = None


def _get_paddle_engine():
    """延遲載入 PaddleOCR（節省啟動記憶體）"""
    global _paddle_engine
    if _paddle_engine is None:
        try:
            from paddleocr import PaddleOCR
            _paddle_engine = PaddleOCR(
                lang="chinese_cht",
                use_angle_cls=True,
                show_log=False,
            )
            logger.info("PaddleOCR initialized (PP-OCRv5)")
        except ImportError:
            logger.warning("PaddleOCR not installed, using Gemini-only mode")
            _paddle_engine = "unavailable"
        except Exception as e:
            logger.error(f"PaddleOCR init error: {e}")
            _paddle_engine = "unavailable"
    return _paddle_engine if _paddle_engine != "unavailable" else None


def ocr_paddle(image_path: str) -> tuple[str, float]:
    """PaddleOCR 辨識 → (文字, 平均信心度)"""
    engine = _get_paddle_engine()
    if not engine:
        return "", 0.0

    try:
        result = engine.ocr(image_path, cls=True)
        if not result or not result[0]:
            return "", 0.0

        lines = []
        scores = []
        for line_data in result[0]:
            if len(line_data) >= 2:
                text = line_data[1][0]
                score = line_data[1][1]
                lines.append(text)
                scores.append(score)

        full_text = "\n".join(lines)
        avg_score = sum(scores) / len(scores) if scores else 0.0

        logger.info(f"PaddleOCR: {len(lines)} lines, avg confidence={avg_score:.3f}")
        return full_text, avg_score

    except Exception as e:
        logger.error(f"PaddleOCR error: {e}")
        return "", 0.0


# === Gemini VLM 引擎 ===

def ocr_gemini(image_path: str) -> Optional[dict]:
    """Gemini VLM 結構化提取 → JSON dict"""
    if not GEMINI_API_KEY:
        logger.warning("No GEMINI_API_KEY, skipping Gemini OCR")
        return None

    try:
        import base64
        import requests

        with open(image_path, "rb") as f:
            image_bytes = f.read()
        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        # 判斷 MIME type
        ext = os.path.splitext(image_path)[1].lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".webp": "image/webp",
                    ".heic": "image/heic"}
        mime_type = mime_map.get(ext, "image/jpeg")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
        payload = {
            "contents": [{
                "parts": [
                    {"inline_data": {"mime_type": mime_type, "data": b64_image}},
                    {"text": (
                        "請辨識這張收據/對帳單/發票的所有內容。\n"
                        "提取：供應商名稱、統一編號、發票字軌與號碼、日期、所有品項（品名、數量、單位、單價、金額）、"
                        "小計、稅額、總計。\n"
                        "如果是手寫的品項，把 is_handwritten 設為 true。\n"
                        "日期請轉換為 YYYY-MM-DD 格式（民國年+1911=西元年）。\n"
                        "如果欄位看不清楚，請填空字串或 0。"
                    )},
                ],
            }],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": GEMINI_RECEIPT_SCHEMA,
                "temperature": 0.1,
                "maxOutputTokens": 4096,
            },
        }

        resp = requests.post(url, params={"key": GEMINI_API_KEY}, json=payload, timeout=30)

        if resp.status_code == 200:
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            result = json.loads(text)
            logger.info(f"Gemini VLM: {len(result.get('items', []))} items extracted")
            return result
        else:
            logger.error(f"Gemini API error: {resp.status_code} {resp.text[:200]}")
            return None

    except Exception as e:
        logger.error(f"Gemini OCR error: {e}")
        return None


# === 合併驗證 ===

def process_image(image_path: str) -> OcrResult:
    """雙引擎辨識 + 合併驗證 → OcrResult"""
    result = OcrResult()

    # Engine 1: PaddleOCR
    paddle_text, paddle_confidence = ocr_paddle(image_path)
    result.raw_text = paddle_text

    # Engine 2: Gemini VLM
    gemini_data = ocr_gemini(image_path)

    # 如果兩個引擎都失敗
    if not paddle_text and not gemini_data:
        result.confidence = 0
        result.result_level = "REJECT"
        result.issues.append("兩個 OCR 引擎都無法辨識")
        return result

    # 以 Gemini 結構化資料為主（更可靠）
    if gemini_data:
        result.supplier_name = gemini_data.get("supplier_name", "")
        result.supplier_tax_id = gemini_data.get("supplier_tax_id", "")
        result.invoice_prefix = gemini_data.get("invoice_prefix", "")
        result.invoice_number = gemini_data.get("invoice_number", "")
        result.invoice_type = gemini_data.get("invoice_type", "")
        result.purchase_date = gemini_data.get("purchase_date", "")
        result.subtotal = float(gemini_data.get("subtotal", 0) or 0)
        result.tax_amount = float(gemini_data.get("tax_amount", 0) or 0)
        result.total_amount = float(gemini_data.get("total_amount", 0) or 0)

        for item_data in gemini_data.get("items", []):
            item = OcrItem(
                name=item_data.get("name", ""),
                quantity=float(item_data.get("quantity", 0) or 0),
                unit=item_data.get("unit", ""),
                unit_price=float(item_data.get("unit_price", 0) or 0),
                amount=float(item_data.get("amount", 0) or 0),
                is_handwritten=item_data.get("is_handwritten", False),
            )
            result.items.append(item)

    # === 信心度計算 ===
    base_confidence = paddle_confidence if paddle_confidence > 0 else 0.50

    # 1. OCR + VLM 一致性加分
    if paddle_text and gemini_data:
        # 檢查金額是否一致（PaddleOCR 文字中找數字 vs Gemini 結構化）
        if _check_amount_consistency(paddle_text, result.total_amount):
            base_confidence += 0.10
        else:
            result.issues.append("兩引擎金額不一致")

    # 2. 數學校驗（單價×數量=金額）
    math_ok = _check_math_consistency(result.items)
    if math_ok:
        base_confidence += 0.05
    elif result.items:
        result.issues.append("品項單價×數量≠金額")

    # 3. 稅額校驗（金額×5%=稅額，±1）
    tax_ok = _check_tax_consistency(result.subtotal, result.tax_amount)
    if tax_ok:
        base_confidence += 0.05
    elif result.subtotal > 0 and result.tax_amount > 0:
        result.issues.append("稅額與金額不一致")

    # 4. 手寫扣分
    has_handwritten = any(item.is_handwritten for item in result.items)
    if has_handwritten:
        base_confidence -= 0.10
        result.issues.append("含有手寫內容")

    # 限制範圍
    result.confidence = max(0.0, min(1.0, base_confidence))

    # === 判定結果等級 ===
    threshold = _get_auto_pass_threshold()
    if result.confidence >= threshold:
        result.result_level = "AUTO_PASS"
    elif result.confidence >= REVIEW_THRESHOLD:
        result.result_level = "REVIEW"
    else:
        result.result_level = "REJECT"

    # 額外驗證
    _validate_fields(result)

    logger.info(
        f"OCR result: confidence={result.confidence:.3f}, "
        f"level={result.result_level}, items={len(result.items)}, "
        f"issues={len(result.issues)}"
    )

    return result


# === 輔助函數 ===

def _check_amount_consistency(ocr_text: str, gemini_total: float) -> bool:
    """檢查 PaddleOCR 文字中是否包含 Gemini 提取的總金額"""
    if gemini_total <= 0:
        return False
    # 在 OCR 文字中找數字
    total_str = str(int(gemini_total))
    # 也檢查加逗號的版本
    total_with_comma = f"{int(gemini_total):,}"
    return total_str in ocr_text or total_with_comma in ocr_text


def _check_math_consistency(items: list[OcrItem]) -> bool:
    """檢查每個品項的 單價×數量=金額"""
    if not items:
        return True
    all_ok = True
    for item in items:
        if item.unit_price > 0 and item.quantity > 0 and item.amount > 0:
            expected = item.unit_price * item.quantity
            if abs(expected - item.amount) > 1:
                all_ok = False
    return all_ok


def _check_tax_consistency(subtotal: float, tax_amount: float) -> bool:
    """檢查 稅額 ≈ 金額 × 5%"""
    if subtotal <= 0 or tax_amount <= 0:
        return True  # 無法驗證時不扣分
    expected_tax = subtotal * 0.05
    return abs(expected_tax - tax_amount) <= 1


def _get_auto_pass_threshold() -> float:
    """根據已處理的張數決定 AUTO_PASS 門檻"""
    try:
        import state_manager as sm
        stats = sm.get_ocr_stats()
        total = stats.get("total", 0) or 0
        if total < EARLY_CALIBRATION_COUNT:
            return AUTO_PASS_THRESHOLD_EARLY
    except Exception:
        pass
    return AUTO_PASS_THRESHOLD


def _validate_fields(result: OcrResult):
    """額外欄位驗證"""
    # 統一編號格式
    if result.supplier_tax_id and not re.match(r"^\d{8}$", result.supplier_tax_id):
        result.issues.append(f"統一編號格式異常：{result.supplier_tax_id}")
        result.confidence -= 0.05

    # 發票號碼格式
    if result.invoice_number and not re.match(r"^\d{8}$", result.invoice_number):
        result.issues.append(f"發票號碼格式異常：{result.invoice_number}")

    # 發票字軌格式
    if result.invoice_prefix and not re.match(r"^[A-Z]{2}$", result.invoice_prefix):
        result.issues.append(f"發票字軌格式異常：{result.invoice_prefix}")

    # 日期格式
    if result.purchase_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", result.purchase_date):
        result.issues.append(f"日期格式異常：{result.purchase_date}")

    # 總額 vs 品項加總
    if result.items and result.total_amount > 0:
        items_sum = sum(item.amount for item in result.items)
        if items_sum > 0 and abs(items_sum - result.total_amount) > result.total_amount * 0.1:
            result.issues.append("品項金額加總與總額差異超過 10%")


# === Flex Message 生成 ===

def build_review_flex(result: OcrResult, staging_id: int) -> dict:
    """生成 Flex Message 供人工確認"""
    # 品項列表
    item_rows = []
    for i, item in enumerate(result.items):
        color = "#FF0000" if item.confidence < 0.6 or item.is_handwritten else "#333333"
        item_rows.append({
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": item.name or f"品項{i+1}", "size": "sm",
                 "color": color, "flex": 3},
                {"type": "text", "text": f"{item.quantity}{item.unit}", "size": "sm",
                 "color": color, "flex": 2, "align": "center"},
                {"type": "text", "text": f"${item.amount:,.0f}", "size": "sm",
                 "color": color, "flex": 2, "align": "end"},
            ],
        })

    # 問題標記
    issue_text = ""
    if result.issues:
        issue_text = "⚠️ " + " | ".join(result.issues[:3])

    # 信心度顏色
    conf_pct = int(result.confidence * 100)
    conf_color = "#00C853" if conf_pct >= 85 else "#FF6D00" if conf_pct >= 60 else "#FF0000"

    flex = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "📋 採購辨識結果", "weight": "bold", "size": "lg"},
                {"type": "text", "text": f"供應商：{result.supplier_name or '未識別'}",
                 "size": "sm", "color": "#666666"},
                {"type": "text", "text": f"日期：{result.purchase_date or '未識別'}",
                 "size": "sm", "color": "#666666"},
                {"type": "text", "text": f"信心度：{conf_pct}%",
                 "size": "sm", "color": conf_color, "weight": "bold"},
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                # 品項標題列
                {
                    "type": "box", "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": "品名", "size": "xs", "color": "#999999", "flex": 3},
                        {"type": "text", "text": "數量", "size": "xs", "color": "#999999",
                         "flex": 2, "align": "center"},
                        {"type": "text", "text": "金額", "size": "xs", "color": "#999999",
                         "flex": 2, "align": "end"},
                    ],
                },
                {"type": "separator", "margin": "sm"},
                *item_rows,
                {"type": "separator", "margin": "md"},
                # 合計
                {
                    "type": "box", "layout": "horizontal", "margin": "md",
                    "contents": [
                        {"type": "text", "text": "合計", "weight": "bold", "flex": 3},
                        {"type": "text", "text": f"${result.total_amount:,.0f}",
                         "weight": "bold", "flex": 4, "align": "end"},
                    ],
                },
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [],
        },
    }

    # 加入問題說明
    if issue_text:
        flex["footer"]["contents"].append(
            {"type": "text", "text": issue_text, "size": "xs",
             "color": "#FF6D00", "wrap": True, "margin": "sm"}
        )

    # 操作按鈕
    flex["footer"]["contents"].extend([
        {
            "type": "box", "layout": "horizontal", "margin": "md", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#00C853",
                 "action": {"type": "message", "label": "✅ 確認",
                           "text": f"確認 #{staging_id}"}},
                {"type": "button", "style": "secondary",
                 "action": {"type": "message", "label": "✏️ 修改",
                           "text": f"修改 #{staging_id}"}},
                {"type": "button", "style": "secondary", "color": "#FF0000",
                 "action": {"type": "message", "label": "❌ 捨棄",
                           "text": f"捨棄 #{staging_id}"}},
            ],
        },
    ])

    return flex
