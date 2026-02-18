"""LLM 服務層 — Claude CLI → llm-router → Gemini 三級 fallback"""

import os
import logging
import requests
from services.claude_bridge import chat as claude_chat

logger = logging.getLogger("shanbot.llm")

LLM_ROUTER_URL = os.environ.get("LLM_ROUTER_URL", "http://127.0.0.1:8010/chat")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

SYSTEM_IDENTITY = (
    "你是小膳，一個專為團膳公司設計的 AI 助理。"
    "你的職責是協助管理每日採購記錄、食材價格比較、菜單規劃和稅務相關作業。"
    "請用繁體中文回應，語氣親切專業。"
)


def chat(prompt: str, system: str = "", max_tokens: int = 4096, timeout: int = 60) -> str | None:
    """一般對話 — Sonnet 4.6"""
    full_system = f"{SYSTEM_IDENTITY}\n\n{system}" if system else SYSTEM_IDENTITY

    # Layer 1: Claude CLI (Sonnet 4.6)
    result = claude_chat(prompt, full_system, model="sonnet", timeout=timeout)
    if result:
        return result

    # Layer 2: llm-router (Rust, port 8010)
    result = _fallback_llm_router(prompt, full_system, max_tokens, timeout)
    if result:
        return result

    # Layer 3: Gemini direct
    result = _fallback_gemini(prompt, full_system, max_tokens)
    if result:
        return result

    logger.error("All LLM providers failed")
    return None


def analyze_receipt(ocr_text: str, structured_data: dict = None) -> str | None:
    """分析收據/對帳單 OCR 結果"""
    system = (
        "你是採購分析專家。分析以下 OCR 辨識結果，指出：\n"
        "1. 品項是否合理（團膳常用食材）\n"
        "2. 價格是否合理\n"
        "3. 數量是否合理\n"
        "4. 有無缺漏或異常\n"
        "請簡潔回覆，重點標示異常項目。"
    )
    prompt = f"OCR 原文：\n{ocr_text}"
    if structured_data:
        prompt += f"\n\n結構化資料：\n{structured_data}"
    return chat(prompt, system, timeout=30)


def suggest_category(item_name: str) -> str:
    """推薦食材分類"""
    categories = "蔬菜、肉類、水產、蛋豆、乾貨、調味料、油品、米糧、其他"
    prompt = f"食材「{item_name}」屬於以下哪個分類？只回覆分類名稱即可。\n分類：{categories}"
    result = chat(prompt, max_tokens=50, timeout=15)
    if result and result.strip() in categories:
        return result.strip()
    return "其他"


def _fallback_llm_router(prompt: str, system: str = "",
                          max_tokens: int = 4096, timeout: int = 60) -> str | None:
    try:
        resp = requests.post(
            LLM_ROUTER_URL,
            json={
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": max_tokens,
            },
            timeout=timeout,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")
        logger.warning(f"llm-router failed: {resp.status_code}")
        return None
    except Exception as e:
        logger.warning(f"llm-router error: {e}")
        return None


def _fallback_gemini(prompt: str, system: str = "", max_tokens: int = 4096) -> str | None:
    if not GEMINI_API_KEY:
        return None
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
        resp = requests.post(
            url,
            params={"key": GEMINI_API_KEY},
            json={
                "contents": [{"parts": [{"text": f"{system}\n\n{prompt}"}]}],
                "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3},
            },
            timeout=60,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        logger.warning(f"Gemini failed: {resp.status_code}")
        return None
    except Exception as e:
        logger.warning(f"Gemini error: {e}")
        return None
