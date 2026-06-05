"""
OCR JSON Repair Chain v1 — 5-layer fallback for malformed Gemini VLM output.

Layer 1: json.loads(raw)
Layer 2: json_repair library
Layer 3: regex patch (unterminated strings + trailing commas)
Layer 4: truncate last incomplete object + retry
Layer 5: Gemini self-correct
Layer 6 (repair_json_safe) = total failure, caller falls back to PaddleOCR.
"""
import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger("shanbot.json_repair")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_REPAIR_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def _regex_patch(raw: str) -> str:
    """Layer 3: remove trailing commas; close unterminated strings; balance braces."""
    # trailing commas before } or ]
    patched = re.sub(r",\s*([}\]])", r"\1", raw)
    # unterminated string at end of line: odd quote count after last colon
    def _close_line(m: re.Match) -> str:
        line = m.group(0)
        after = line.split(":", 1)[-1] if ":" in line else line
        if after.count('"') % 2 == 1:
            return line + '"'
        return line
    patched = re.sub(r'[^\n]*"[^"\n]*$', _close_line, patched, flags=re.MULTILINE)
    # balance braces/brackets
    opens_sq = patched.count("[") - patched.count("]")
    opens_br = patched.count("{") - patched.count("}")
    if opens_sq > 0:
        patched = patched.rstrip() + "]" * opens_sq
    if opens_br > 0:
        patched = patched.rstrip() + "}" * opens_br
    return patched


def _truncate_last_incomplete(raw: str) -> str:
    """Layer 4: walk back to last balanced closing brace, truncate remainder."""
    depth = 0
    last_safe = -1
    in_string = False
    escape_next = False
    for i, ch in enumerate(raw):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth <= 0:
                last_safe = i
    if last_safe > 0:
        t = raw[: last_safe + 1]
        sq = t.count("[") - t.count("]")
        br = t.count("{") - t.count("}")
        if sq > 0:
            t = t.rstrip() + "]" * sq
        if br > 0:
            t = t.rstrip() + "}" * br
        return t
    return raw


def _gemini_self_correct(raw: str) -> Optional[dict]:
    """Layer 5: ask Gemini 2.5 Flash to fix JSON syntax, return parsed dict."""
    if not GEMINI_API_KEY:
        return None
    try:
        import requests
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{GEMINI_REPAIR_MODEL}:generateContent")
        prompt = ("請修正下列 JSON 語法錯誤，只回傳修正後的 JSON，不要任何說明文字：\n\n"
                  + raw[:8000])
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.0,
                "maxOutputTokens": 4096,
            },
        }
        resp = requests.post(url, params={"key": GEMINI_API_KEY},
                             json=payload, timeout=30)
        if resp.status_code == 200:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        logger.warning(f"Gemini self-correct API error: {resp.status_code}")
        return None
    except Exception as e:
        logger.warning(f"Gemini self-correct failed: {e}")
        return None


def repair_json(raw: str) -> tuple:
    """
    Parse raw through layers 1-5. Returns (dict, layer_hit:int).
    Raises ValueError if all layers fail.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Empty or non-string input")
    # Layer 1
    try:
        return json.loads(raw), 1
    except json.JSONDecodeError:
        pass
    # Layer 2
    try:
        from json_repair import repair_json as _lib
        fixed = _lib(raw)
        result = json.loads(fixed) if isinstance(fixed, str) else fixed
        if isinstance(result, dict) and result:
            return result, 2
    except Exception as e:
        logger.debug(f"Layer 2: {e}")
    # Layer 3
    try:
        return json.loads(_regex_patch(raw)), 3
    except Exception as e:
        logger.debug(f"Layer 3: {e}")
    # Layer 4
    try:
        t = _truncate_last_incomplete(raw)
        if t != raw:
            return json.loads(t), 4
    except Exception as e:
        logger.debug(f"Layer 4: {e}")
    # Layer 5
    result = _gemini_self_correct(raw)
    if result is not None:
        return result, 5
    raise ValueError(f"All 5 JSON repair layers failed. Snippet: {raw[:200]!r}")


def repair_json_safe(raw: str) -> tuple:
    """Like repair_json but returns (None, 6) instead of raising on total failure."""
    try:
        return repair_json(raw)
    except ValueError:
        return None, 6
