"""多租戶公司服務 — Channel 路由、公司 context、憑證管理"""

import json
import logging
import os
from typing import Optional

import state_manager as sm

logger = logging.getLogger("shanbot.company")

# === 快取：Channel ID → Company 映射（啟動時載入） ===
_channel_map: dict[str, dict] = {}
_company_cache: dict[int, dict] = {}
# Bot userId → Company 映射（啟動時自動建立，用於 destination fallback）
_bot_user_map: dict[str, int] = {}


def init_companies():
    """啟動時載入所有公司設定到快取"""
    global _channel_map, _company_cache, _bot_user_map
    companies = sm.get_all_companies()
    _company_cache.clear()
    _channel_map.clear()
    _bot_user_map.clear()

    for c in companies:
        _company_cache[c["id"]] = c
        if c.get("line_channel_id"):
            _channel_map[c["line_channel_id"]] = c

    # 從 companies.json 補齊資料庫中缺少 LINE 憑證的公司
    _load_from_config()

    # 自動建立 bot userId → company 映射（用各公司 token 查詢 bot info）
    _build_bot_user_map()

    logger.info(f"Companies loaded: {len(_company_cache)} total, "
                f"{len(_channel_map)} with LINE credentials")


def _load_from_config():
    """從 config/companies.json 載入（補齊 DB 中缺少的公司或憑證）"""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                               "config", "companies.json")
    if not os.path.exists(config_path):
        return

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for c in data.get("companies", []):
            cid = c.get("id")
            channel_id = c.get("line_channel_id", "")
            channel_secret = c.get("line_channel_secret", "")
            access_token = c.get("line_channel_access_token", "")

            if not (channel_id and channel_secret and access_token and cid):
                continue

            # 如果 channel 已在 _channel_map 且憑證一致，跳過
            existing = _channel_map.get(channel_id)
            if existing and existing.get("line_channel_secret") == channel_secret:
                continue

            # 新公司或憑證更新 → 寫入資料庫 + 更新快取
            sm.update_company_line_credentials(
                cid, channel_id, channel_secret, access_token
            )

            if cid not in _company_cache:
                # 資料庫中沒有這家公司 → 從 config 建立
                _company_cache[cid] = {
                    "id": cid,
                    "short_name": c.get("short_name", f"Company-{cid}"),
                    "full_name": c.get("full_name", ""),
                    "tax_id": c.get("tax_id", ""),
                    "gdrive_folder": c.get("gdrive_folder", "福利社"),
                    "is_default": c.get("is_default", False),
                }

            _company_cache[cid]["line_channel_id"] = channel_id
            _company_cache[cid]["line_channel_secret"] = channel_secret
            _company_cache[cid]["line_channel_access_token"] = access_token
            _channel_map[channel_id] = _company_cache[cid]
            logger.info(f"Synced LINE credentials for [{cid}] {c.get('short_name', '')} from config")

    except Exception as e:
        logger.warning(f"Failed to load companies.json: {e}")


def _build_bot_user_map():
    """啟動時用各公司 token 查 bot info，建立 bot userId → company_id 映射"""
    global _bot_user_map
    import requests

    for channel_id, company in _channel_map.items():
        token = company.get("line_channel_access_token", "")
        if not token:
            continue
        try:
            resp = requests.get(
                "https://api.line.me/v2/bot/info",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            if resp.status_code == 200:
                bot_user_id = resp.json().get("userId", "")
                if bot_user_id:
                    _bot_user_map[bot_user_id] = company["id"]
        except Exception:
            pass  # 網路問題不影響啟動

    if _bot_user_map:
        logger.info(f"Bot user map built: {len(_bot_user_map)} bots registered")


def reload_companies():
    """重新載入公司設定（憑證更新後呼叫）"""
    init_companies()


# === 路由 ===

def resolve_company(channel_id: str = None, chat_id: str = None) -> dict:
    """從 Channel ID 或 chat_id 解析對應公司"""
    if channel_id and channel_id in _channel_map:
        return _channel_map[channel_id]

    # Fallback: 預設公司
    default = next((c for c in _company_cache.values() if c.get("is_default")), None)
    if default:
        return default

    # 終極 fallback
    if _company_cache:
        return next(iter(_company_cache.values()))

    return {"id": 1, "short_name": "福利社", "gdrive_folder": "福利社"}


def get_company_by_id(company_id: int) -> Optional[dict]:
    """從快取取得公司"""
    return _company_cache.get(company_id)


def get_all_active_companies() -> list[dict]:
    """取得所有啟用的公司"""
    return list(_company_cache.values())


def get_channel_secret(channel_id: str) -> str:
    """取得指定 Channel 的 Secret（用於簽名驗證）"""
    company = _channel_map.get(channel_id)
    if company:
        return company.get("line_channel_secret", "")
    return ""


def get_access_token(company_id: int = None, channel_id: str = None) -> str:
    """取得 Access Token（用於回覆/推送）"""
    if company_id and company_id in _company_cache:
        token = _company_cache[company_id].get("line_channel_access_token", "")
        if token:
            return token

    if channel_id and channel_id in _channel_map:
        token = _channel_map[channel_id].get("line_channel_access_token", "")
        if token:
            return token

    return ""


def resolve_by_signature(body: bytes, signature: str) -> Optional[dict]:
    """用簽名比對找出是哪家公司的 webhook（多租戶核心路由）

    遍歷所有已註冊 channel，用各自的 secret 計算 HMAC-SHA256，
    與 LINE 送來的 X-Line-Signature 比對。
    """
    import base64
    import hashlib
    import hmac as _hmac

    for channel_id, company in _channel_map.items():
        secret = company.get("line_channel_secret", "")
        if not secret:
            continue
        mac = _hmac.new(secret.encode("utf-8"), body, hashlib.sha256)
        expected = base64.b64encode(mac.digest()).decode("utf-8")
        if _hmac.compare_digest(expected, signature):
            return company
    return None


def resolve_by_destination(destination: str) -> Optional[dict]:
    """用 destination (bot userId) 找出對應公司 — signature 失敗時的 fallback

    destination 是 LINE webhook payload 中的 bot userId，
    與 _bot_user_map（啟動時自動建立）比對。
    """
    company_id = _bot_user_map.get(destination)
    if company_id:
        return _company_cache.get(company_id)
    return None


def get_gdrive_folder(company_id: int) -> str:
    """取得公司的 GDrive 資料夾名稱"""
    company = _company_cache.get(company_id)
    if company:
        return company.get("gdrive_folder", "福利社")
    return "福利社"
