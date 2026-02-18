"""菜單 AI 服務 — Gemini 覈對、菜色描述、成本試算、圖片生成"""

import base64
import json
import logging
import os
from datetime import datetime
from typing import Optional

import requests
import state_manager as sm

logger = logging.getLogger("shanbot.menu_ai")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
IMAGEN_MODEL = "imagen-3.0-generate-002"
IMAGEN_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{IMAGEN_MODEL}:predict"
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")
IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "images")


def _call_gemini(prompt: str, json_mode: bool = False) -> str | None:
    """呼叫 Gemini API"""
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set")
        return None

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2048},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"

    try:
        resp = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json=body,
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return text
        logger.error(f"Gemini API error: {resp.status_code} {resp.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"Gemini call error: {e}")
        return None


def review_menu(menu_data: list[dict], budget_per_person: float = 70,
                servings: int = 100) -> dict:
    """AI 覈對菜單 — 檢查合理性、營養、成本"""
    menu_json = json.dumps(menu_data, ensure_ascii=False, indent=2)

    prompt = f"""你是團膳營養師和成本顧問。請覈對以下菜單：

菜單資料：
{menu_json}

每人每餐預算上限：${budget_per_person}
供餐人數：{servings} 人

請以 JSON 格式回覆，結構如下：
{{
  "overall_score": 85,
  "summary": "整體評價簡述",
  "issues": [
    {{"day": "週三", "issue": "問題描述", "suggestion": "建議"}},
  ],
  "nutrition_notes": "營養搭配建議",
  "cost_estimate": {{
    "per_person_per_day": 65,
    "total_weekly": 9100,
    "over_budget": false
  }}
}}"""

    result = _call_gemini(prompt, json_mode=True)
    if result:
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"overall_score": 0, "summary": result, "issues": []}
    return {"overall_score": 0, "summary": "AI 覈對暫時無法使用", "issues": []}


def generate_dish_description(dish_name: str) -> dict:
    """生成菜色描述 + 行銷文案"""
    prompt = f"""你是團膳行銷顧問。請為以下菜色生成描述：

菜名：{dish_name}

請以 JSON 格式回覆：
{{
  "dish_name": "{dish_name}",
  "description": "50 字以內的菜色介紹",
  "ingredients": ["主要食材1", "主要食材2", ...],
  "cooking_method": "烹調方式",
  "marketing_copy": "一句吸引人的行銷文案",
  "plating_suggestion": "擺盤建議"
}}"""

    result = _call_gemini(prompt, json_mode=True)
    if result:
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"dish_name": dish_name, "description": result, "ingredients": []}
    return {"dish_name": dish_name, "description": "AI 暫時無法使用", "ingredients": []}


def estimate_dish_cost(dish_name: str, ingredients_info: list[dict] = None) -> dict:
    """估算菜色食材成本"""
    # 如果有配方資料，直接從 DB 計算
    if ingredients_info:
        total = 0
        items = []
        for ing in ingredients_info:
            cost = (ing.get("quantity", 0) or 0) * (ing.get("current_price", 0) or 0)
            total += cost
            items.append({
                "name": ing.get("ingredient_name", ing.get("name", "")),
                "quantity": ing.get("quantity", 0),
                "unit": ing.get("unit", ""),
                "unit_price": ing.get("current_price", 0),
                "cost": round(cost, 1),
            })
        return {
            "dish_name": dish_name,
            "total_cost": round(total, 0),
            "items": items,
            "source": "database",
        }

    # 否則用 AI 估算
    prompt = f"""你是團膳成本分析師。請估算以下菜色的食材成本（台灣市場價格，100 人份）：

菜名：{dish_name}

請以 JSON 格式回覆：
{{
  "dish_name": "{dish_name}",
  "total_cost": 850,
  "cost_per_serving": 8.5,
  "items": [
    {{"name": "食材名", "quantity": 5, "unit": "斤", "unit_price": 35, "cost": 175}},
  ],
  "notes": "備註"
}}

注意：價格使用新台幣，重量單位用斤或公斤。"""

    result = _call_gemini(prompt, json_mode=True)
    if result:
        try:
            data = json.loads(result)
            data["source"] = "ai_estimate"
            return data
        except json.JSONDecodeError:
            pass
    return {
        "dish_name": dish_name,
        "total_cost": 0,
        "items": [],
        "source": "error",
        "notes": "AI 估算暫時無法使用",
    }


def _call_gemini_multimodal(prompt: str, image_bytes: bytes,
                            json_mode: bool = False) -> str | None:
    """呼叫 Gemini multimodal API（圖片+文字）"""
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set")
        return None

    img_b64 = base64.b64encode(image_bytes).decode("utf-8")
    body = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inlineData": {"mimeType": "image/jpeg", "data": img_b64}},
            ],
        }],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 2048},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"

    try:
        resp = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json=body,
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        logger.error(f"Gemini multimodal error: {resp.status_code} {resp.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"Gemini multimodal call error: {e}")
        return None


def analyze_dish_photo(image_bytes: bytes) -> dict:
    """Stage 1: Gemini Vision 分析菜色照片。

    Returns:
        {"dish_name", "ingredients", "style", "color_tone",
         "plating_assessment", "improvement_suggestions"}
    """
    prompt = """你是專業食物攝影分析師。請分析這張菜色照片，以 JSON 回覆：
{
  "dish_name": "菜色名稱",
  "ingredients": ["主要食材1", "主要食材2"],
  "style": "料理風格（如：中式家常、日式定食、西式排餐）",
  "color_tone": "主色調描述",
  "plating_assessment": "擺盤評估（優點和可改善處）",
  "improvement_suggestions": "拍攝/擺盤改善建議",
  "background_suggestion": "適合的背景建議（如：深色木板、白色大理石）"
}"""

    result = _call_gemini_multimodal(prompt, image_bytes, json_mode=True)
    if result:
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"dish_name": "未識別菜色", "ingredients": [], "style": result}
    return {"dish_name": "未識別菜色", "ingredients": [], "style": "分析失敗"}


def generate_enhanced_dish_prompt(analysis: dict) -> str:
    """Stage 2: 根據分析結果組裝 Imagen prompt，生成棚拍質感增強圖。"""
    dish_name = analysis.get("dish_name", "dish")
    style = analysis.get("style", "Chinese cuisine")
    color_tone = analysis.get("color_tone", "warm tones")
    bg = analysis.get("background_suggestion", "dark wooden table")
    ingredients = ", ".join(analysis.get("ingredients", [])[:5])

    prompt = (
        f"Professional food photography of {dish_name} ({style}). "
        f"Main ingredients: {ingredients}. "
        f"Studio lighting setup with soft diffused light from the left, "
        f"creating gentle shadows. Shallow depth of field, f/2.8. "
        f"The dish is elegantly plated on a premium ceramic plate, "
        f"placed on {bg}. Color palette: {color_tone}. "
        f"Garnished with fresh herbs. "
        f"Shot with a 85mm lens, 45-degree angle. "
        f"Restaurant-quality, magazine cover worthy, appetizing, vibrant colors. "
        f"8K resolution, ultra detailed."
    )
    return prompt


def generate_marketing_copy(analysis: dict) -> dict:
    """Stage 3: Gemini 生成中文行銷文案。

    Returns:
        {"tagline": "一口入魂的…", "copy": "嚴選在地…", "hashtags": ["#美食", ...]}
    """
    dish_name = analysis.get("dish_name", "美食")
    ingredients = "、".join(analysis.get("ingredients", [])[:5])
    style = analysis.get("style", "")

    prompt = f"""你是餐飲行銷文案專家。為以下菜色撰寫社群行銷文案：

菜名：{dish_name}
食材：{ingredients}
風格：{style}

請以 JSON 格式回覆：
{{
  "tagline": "10 字以內的吸睛標語",
  "copy": "50-80 字的推廣文案（要有溫度、故事感）",
  "hashtags": ["#美食", "#台灣味", "..."]
}}

要求：使用繁體中文，語調親切、有質感。hashtags 5-8 個。"""

    result = _call_gemini(prompt, json_mode=True)
    if result:
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"tagline": dish_name, "copy": result, "hashtags": []}
    return {"tagline": dish_name, "copy": "行銷文案生成暫時無法使用", "hashtags": []}


def _call_imagen_api(prompt: str) -> bytes | None:
    """呼叫 Imagen API 生成圖片，回傳圖片 bytes 或 None。"""
    if not GEMINI_API_KEY:
        return None

    try:
        resp = requests.post(
            f"{IMAGEN_URL}?key={GEMINI_API_KEY}",
            json={
                "instances": [{"prompt": prompt}],
                "parameters": {
                    "sampleCount": 1,
                    "aspectRatio": "4:3",
                    "personGeneration": "dont_allow",
                },
            },
            timeout=60,
        )

        if resp.status_code != 200:
            logger.error(f"Imagen API error: {resp.status_code} {resp.text[:300]}")
            return None

        data = resp.json()
        predictions = data.get("predictions", [])
        if not predictions:
            return None

        img_b64 = predictions[0].get("bytesBase64Encoded", "")
        if not img_b64:
            return None

        return base64.b64decode(img_b64)
    except Exception as e:
        logger.error(f"Imagen API error: {e}")
        return None


def generate_dish_image(dish_name: str) -> dict:
    """用 Imagen 3 生成菜色照片風格圖片

    Returns:
        {"success": True, "local_path": "...", "image_url": "...", "filename": "..."}
        or {"success": False, "error": "..."}
    """
    if not GEMINI_API_KEY:
        return {"success": False, "error": "GEMINI_API_KEY not set"}

    prompt = (
        f"Professional food photography of a Taiwanese dish: {dish_name}. "
        "The dish is beautifully plated on a white ceramic plate, "
        "shot from a 45-degree angle with natural soft lighting. "
        "Garnished elegantly, restaurant quality presentation. "
        "Clean background, shallow depth of field, appetizing and vibrant colors."
    )

    try:
        resp = requests.post(
            f"{IMAGEN_URL}?key={GEMINI_API_KEY}",
            json={
                "instances": [{"prompt": prompt}],
                "parameters": {
                    "sampleCount": 1,
                    "aspectRatio": "4:3",
                    "personGeneration": "dont_allow",
                },
            },
            timeout=60,
        )

        if resp.status_code != 200:
            logger.error(f"Imagen API error: {resp.status_code} {resp.text[:300]}")
            return {"success": False, "error": f"API error {resp.status_code}"}

        data = resp.json()
        predictions = data.get("predictions", [])
        if not predictions:
            return {"success": False, "error": "No image generated"}

        # 解碼 base64 圖片
        img_b64 = predictions[0].get("bytesBase64Encoded", "")
        if not img_b64:
            return {"success": False, "error": "Empty image data"}

        img_bytes = base64.b64decode(img_b64)
        mime = predictions[0].get("mimeType", "image/png")
        ext = ".png" if "png" in mime else ".jpg"

        # 儲存
        os.makedirs(IMAGES_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = dish_name.replace(" ", "_").replace("/", "_")[:30]
        filename = f"dish_{safe_name}_{ts}{ext}"
        local_path = os.path.join(IMAGES_DIR, filename)

        with open(local_path, "wb") as f:
            f.write(img_bytes)

        logger.info(f"Dish image generated: {local_path} ({len(img_bytes)} bytes)")

        # 構建公開 URL
        image_url = ""
        if PUBLIC_BASE_URL:
            image_url = f"{PUBLIC_BASE_URL.rstrip('/')}/images/{filename}"

        # 上傳到 GDrive
        try:
            from services.gdrive_service import upload_export
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 同步上下文中無法 await，直接複製
                from services.gdrive_service import (
                    init_folder_structure, _year_month_path, GDRIVE_LOCAL,
                )
                import shutil
                ym = datetime.now().strftime("%Y-%m")
                init_folder_structure(ym)
                _, month_path = _year_month_path(ym)
                dest_dir = os.path.join(month_path, "菜單企劃")
                os.makedirs(dest_dir, exist_ok=True)
                shutil.copy2(local_path, os.path.join(dest_dir, filename))
        except Exception as e:
            logger.warning(f"GDrive upload skipped: {e}")

        return {
            "success": True,
            "local_path": local_path,
            "image_url": image_url,
            "filename": filename,
        }

    except requests.Timeout:
        return {"success": False, "error": "圖片生成逾時，請稍後再試"}
    except Exception as e:
        logger.error(f"Imagen error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def suggest_alternatives(dish_name: str, reason: str = "cost") -> list[dict]:
    """建議替代菜色"""
    prompt = f"""你是團膳菜單顧問。請為以下菜色建議 3 個替代方案：

原菜色：{dish_name}
替換原因：{'成本過高' if reason == 'cost' else '食材不足' if reason == 'supply' else reason}

請以 JSON 陣列格式回覆：
[
  {{"name": "替代菜名", "reason": "為什麼推薦", "estimated_cost_pct": "比原菜低 20%"}}
]"""

    result = _call_gemini(prompt, json_mode=True)
    if result:
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            pass
    return []
