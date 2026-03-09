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

# HunyuanOCR 配置
HUNYUAN_API_URL = os.environ.get("HUNYUAN_OCR_API_URL", "")
HUNYUAN_API_KEY = os.environ.get("HUNYUAN_OCR_API_KEY", "")  # HF Inference API token

# 電子發票 API 配置
EINVOICE_APP_ID = os.environ.get("EINVOICE_APP_ID", "")
EINVOICE_API_KEY = os.environ.get("EINVOICE_API_KEY", "")
EINVOICE_API_URL = "https://api.einvoice.nat.gov.tw"


def _get_paddle_engine():
    """延遲載入 PaddleOCR PP-OCRv5（節省啟動記憶體）"""
    global _paddle_engine
    if _paddle_engine is None:
        try:
            import logging as _logging
            _logging.getLogger("ppocr").setLevel(_logging.WARNING)
            from paddleocr import PaddleOCR
            _paddle_engine = PaddleOCR(
                lang="chinese_cht",
                use_angle_cls=True,
            )
            logger.info("PaddleOCR PP-OCRv5 initialized")
        except ImportError:
            logger.warning("PaddleOCR not installed, using Gemini-only mode")
            _paddle_engine = "unavailable"
        except Exception as e:
            logger.error(f"PaddleOCR init error: {e}")
            _paddle_engine = "unavailable"
    return _paddle_engine if _paddle_engine != "unavailable" else None


def ocr_paddle(image_path: str) -> tuple[str, float]:
    """PaddleOCR PP-OCRv5 辨識 → (文字, 平均信心度)"""
    engine = _get_paddle_engine()
    if not engine:
        return "", 0.0

    try:
        result = engine.ocr(image_path)
        if not result:
            return "", 0.0

        lines = []
        scores = []
        # PaddleOCR 3.x 回傳格式: list of dicts with 'rec_texts', 'rec_scores', etc.
        if isinstance(result, list) and result:
            first = result[0]
            # v3.x dict format
            if isinstance(first, dict):
                rec_texts = first.get("rec_texts", [])
                rec_scores = first.get("rec_scores", [])
                for text, score in zip(rec_texts, rec_scores):
                    lines.append(text)
                    scores.append(score)
            # v2.x list-of-lists format (fallback)
            elif isinstance(first, list):
                for line_data in first:
                    if isinstance(line_data, (list, tuple)) and len(line_data) >= 2:
                        text = line_data[1][0]
                        score = line_data[1][1]
                        lines.append(text)
                        scores.append(score)

        full_text = "\n".join(lines)
        avg_score = sum(scores) / len(scores) if scores else 0.0

        logger.info(f"PaddleOCR PP-OCRv5: {len(lines)} lines, avg confidence={avg_score:.3f}")
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


# === HunyuanOCR 引擎（Hugging Face Inference API fallback）===

def ocr_hunyuan(image_path: str) -> Optional[str]:
    """HunyuanOCR via Hugging Face Inference API → 純文字（Gemini 掛掉時備用）"""
    if not HUNYUAN_API_KEY:
        return None

    try:
        import requests

        api_url = HUNYUAN_API_URL or "https://api-inference.huggingface.co/models/tencent/HunyuanOCR"

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        headers = {"Authorization": f"Bearer {HUNYUAN_API_KEY}"}

        # HF Inference API: 送圖片 + prompt 做 OCR
        import base64
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        ext = os.path.splitext(image_path)[1].lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".webp": "image/webp"}
        mime_type = mime_map.get(ext, "image/jpeg")

        payload = {
            "inputs": {
                "image": f"data:{mime_type};base64,{b64_image}",
                "text": "OCR this receipt. Extract all text content.",
            },
        }

        resp = requests.post(api_url, headers=headers, json=payload, timeout=60)

        if resp.status_code == 200:
            data = resp.json()
            # HF Inference API 回傳格式因模型而異
            if isinstance(data, list) and data:
                text = data[0].get("generated_text", "") if isinstance(data[0], dict) else str(data[0])
            elif isinstance(data, dict):
                text = data.get("generated_text", "") or data.get("text", "") or json.dumps(data)
            else:
                text = str(data)
            logger.info(f"HunyuanOCR: {len(text)} chars extracted")
            return text
        else:
            logger.warning(f"HunyuanOCR API error: {resp.status_code}")
            return None

    except Exception as e:
        logger.error(f"HunyuanOCR error: {e}")
        return None


# === 電子發票驗證 API ===

def verify_einvoice(invoice_number: str, invoice_date: str,
                    seller_tax_id: str = "") -> Optional[dict]:
    """呼叫財政部電子發票 API 交叉驗證發票真偽 + 補全資訊

    Args:
        invoice_number: 發票號碼（10碼: 字軌2碼+號碼8碼）
        invoice_date: 發票日期 YYYY-MM-DD
        seller_tax_id: 賣方統編（選填）

    Returns:
        dict with verified fields, or None if unavailable
    """
    if not EINVOICE_APP_ID or not EINVOICE_API_KEY:
        return None

    try:
        import requests
        from datetime import datetime

        # 轉換日期為民國年月格式 (invTerm = YYY/MM-MM, 雙月期)
        d = datetime.strptime(invoice_date, "%Y-%m-%d")
        roc_year = d.year - 1911
        month = d.month
        # 雙月期：1-2月、3-4月...
        start_month = month if month % 2 == 1 else month - 1
        end_month = start_month + 1
        inv_term = f"{roc_year}{start_month:02d}{end_month:02d}"

        # 查詢發票表頭
        params = {
            "version": "0.5",
            "type": "QRCode",
            "invNum": invoice_number,
            "action": "qryInvHeader",
            "generation": "V2",
            "invTerm": inv_term,
            "invDate": invoice_date.replace("-", "/"),
            "UUID": "00000000",
            "appID": EINVOICE_APP_ID,
        }

        # 產生簽章
        import hashlib
        import hmac
        import time
        timestamp = str(int(time.time()))
        sign_data = f"appID={EINVOICE_APP_ID}&invTerm={inv_term}&timeStamp={timestamp}"
        signature = hmac.new(
            EINVOICE_API_KEY.encode("utf-8"),
            sign_data.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        params["timeStamp"] = timestamp
        params["signature"] = signature

        resp = requests.get(
            f"{EINVOICE_API_URL}/PB2CAPIVAN/invapp/InvApp",
            params=params,
            timeout=10,
        )

        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 200:
                result = {
                    "verified": True,
                    "invoice_number": data.get("invNum", ""),
                    "invoice_date": data.get("invDate", ""),
                    "seller_name": data.get("sellerName", ""),
                    "seller_tax_id": data.get("sellerBan", ""),
                    "invoice_status": data.get("invStatus", ""),
                    "total_amount": float(data.get("invAmount", 0) or 0),
                }
                logger.info(f"E-invoice verified: {invoice_number} → {result['seller_name']}")
                return result
            else:
                logger.info(f"E-invoice query: code={data.get('code')}, msg={data.get('msg', '')}")
                return {"verified": False, "msg": data.get("msg", "")}

        return None

    except Exception as e:
        logger.error(f"E-invoice API error: {e}")
        return None


# === 合併驗證 ===

def process_image(image_path: str) -> OcrResult:
    """三引擎辨識 + 電子發票交叉驗證 → OcrResult

    引擎優先序：
    1. PaddleOCR PP-OCRv5 — 文字偵測 + 辨識（繁中）
    2. Gemini VLM — 結構化提取（主力）
    3. HunyuanOCR — 備用 OCR（Gemini 失敗時啟用）
    4. 電子發票 API — 交叉驗證 + 補全資訊
    """
    result = OcrResult()

    # Engine 1: PaddleOCR PP-OCRv5
    paddle_text, paddle_confidence = ocr_paddle(image_path)
    result.raw_text = paddle_text

    # Engine 2: Gemini VLM
    gemini_data = ocr_gemini(image_path)

    # Engine 3: HunyuanOCR（僅在 Gemini 失敗時啟用）
    hunyuan_text = None
    if not gemini_data:
        hunyuan_text = ocr_hunyuan(image_path)
        if hunyuan_text and not paddle_text:
            result.raw_text = hunyuan_text

    # 如果所有引擎都失敗
    if not paddle_text and not gemini_data and not hunyuan_text:
        result.confidence = 0
        result.result_level = "REJECT"
        result.issues.append("所有 OCR 引擎都無法辨識")
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
    all_text = paddle_text or hunyuan_text or ""
    if all_text and gemini_data:
        if _check_amount_consistency(all_text, result.total_amount):
            base_confidence += 0.10
        else:
            result.issues.append("引擎間金額不一致")

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

    # 5. 電子發票 API 交叉驗證（有發票號碼時）
    inv_num = (result.invoice_prefix + result.invoice_number).strip()
    if len(inv_num) == 10 and result.purchase_date:
        einvoice_result = verify_einvoice(inv_num, result.purchase_date, result.supplier_tax_id)
        if einvoice_result and einvoice_result.get("verified"):
            # 用政府資料補全/修正
            if einvoice_result.get("seller_name") and not result.supplier_name:
                result.supplier_name = einvoice_result["seller_name"]
            if einvoice_result.get("seller_tax_id") and not result.supplier_tax_id:
                result.supplier_tax_id = einvoice_result["seller_tax_id"]
            # 金額交叉驗證
            api_amount = einvoice_result.get("total_amount", 0)
            if api_amount > 0 and abs(api_amount - result.total_amount) <= 1:
                base_confidence += 0.10  # 政府資料吻合 → 大幅加分
            elif api_amount > 0:
                result.issues.append(
                    f"電子發票金額 ${api_amount:,.0f} ≠ OCR ${result.total_amount:,.0f}"
                )

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

    engines_used = []
    if paddle_text:
        engines_used.append("PaddleOCR")
    if gemini_data:
        engines_used.append("Gemini")
    if hunyuan_text:
        engines_used.append("HunyuanOCR")
    logger.info(
        f"OCR result: engines={'+'.join(engines_used)}, "
        f"confidence={result.confidence:.3f}, level={result.result_level}, "
        f"items={len(result.items)}, issues={len(result.issues)}"
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
    uncertain_items = []
    for i, item in enumerate(result.items):
        is_uncertain = item.confidence < 0.6 or item.is_handwritten
        color = "#FF0000" if is_uncertain else "#333333"
        prefix = "⚠️ " if is_uncertain else ""
        if is_uncertain:
            uncertain_items.append(item)
        item_rows.append({
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": f"{prefix}{item.name or f'品項{i+1}'}", "size": "sm",
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

    # 手寫/模糊品項提問
    if uncertain_items:
        q_lines = []
        for item in uncertain_items[:5]:
            tag = "✍️手寫" if item.is_handwritten else "❓模糊"
            q_lines.append(f"  {tag}：{item.name} {item.quantity}{item.unit} = ${item.amount:,.0f}")
        flex["footer"]["contents"].append(
            {"type": "text",
             "text": "以下品項請特別確認：\n" + "\n".join(q_lines),
             "size": "xs", "color": "#DD2E44", "wrap": True, "margin": "md"})

    # 操作按鈕（同意 + 修改）
    flex["footer"]["contents"].extend([
        {
            "type": "box", "layout": "horizontal", "margin": "md", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#00C853",
                 "action": {"type": "message", "label": "✅ 同意",
                           "text": f"確認 #{staging_id}"}},
                {"type": "button", "style": "secondary",
                 "action": {"type": "message", "label": "✏️ 修改",
                           "text": f"修改 #{staging_id}"}},
            ],
        },
    ])

    # 簡易確認提示
    flex["footer"]["contents"].append(
        {"type": "text",
         "text": "💡 也可以直接回覆「OK」或貼圖確認",
         "size": "xxs", "color": "#999999", "align": "center", "margin": "md"})

    return flex


def build_final_confirm_flex(staging_id: int, staging: dict, items: list) -> dict:
    """生成最終確認 Flex Message（二次確認）"""
    supplier = staging.get("supplier_name", "未知")
    purchase_date = staging.get("purchase_date", "未知")
    total = staging.get("total_amount", 0)
    item_count = len(items)

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "📋 最終確認",
                 "weight": "bold", "size": "lg", "color": "#333333"},
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {"type": "text", "text": f"供應商：{supplier}",
                 "size": "sm", "color": "#555555"},
                {"type": "text", "text": f"日期：{purchase_date}",
                 "size": "sm", "color": "#555555"},
                {"type": "text", "text": f"金額：${total:,.0f}",
                 "size": "md", "weight": "bold", "color": "#333333"},
                {"type": "text", "text": f"品項數：{item_count} 項",
                 "size": "sm", "color": "#555555"},
                {"type": "separator", "margin": "md"},
                {"type": "text", "text": "確認歸檔後將存入 GDrive",
                 "size": "xs", "color": "#999999", "margin": "md"},
            ],
        },
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#00C853",
                 "action": {"type": "message", "label": "✅ 確認歸檔",
                           "text": f"最終確認 #{staging_id}"}},
                {"type": "button", "style": "primary", "color": "#DD2E44",
                 "action": {"type": "message", "label": "❌ 不予理會",
                           "text": f"拒絕 #{staging_id}"}},
            ],
        },
    }
