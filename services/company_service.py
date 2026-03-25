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


def init_companies():
    """啟動時載入所有公司設定到快取"""
    global _channel_map, _company_cache
    companies = sm.get_all_companies()
    _company_cache.clear()
    _channel_map.clear()

    for c in companies:
        _company_cache[c["id"]] = c
        if c.get("line_channel_id"):
            _channel_map[c["line_channel_id"]] = c

    # 如果資料庫裡的公司還沒有 LINE 憑證，嘗試從 companies.json 載入
    if not _channel_map:
        _load_from_config()

    logger.info(f"Companies loaded: {len(_company_cache)} total, "
                f"{len(_channel_map)} with LINE credentials")


def _load_from_config():
    """從 config/companies.json 載入（backup source）"""
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

            if channel_id and channel_secret and access_token and cid:
                # 寫入資料庫
                sm.update_company_line_credentials(
                    cid, channel_id, channel_secret, access_token
                )
                # 更新快取
                if cid in _company_cache:
                    _company_cache[cid]["line_channel_id"] = channel_id
                    _company_cache[cid]["line_channel_secret"] = channel_secret
                    _company_cache[cid]["line_channel_access_token"] = access_token
                    _channel_map[channel_id] = _company_cache[cid]
                    logger.info(f"Loaded LINE credentials for company {cid} from config")
    except Exception as e:
        logger.warning(f"Failed to load companies.json: {e}")


def reload_companies():
    """重新載入公司設定（憑證更新後呼叫）"""
    init_companies()


# === 路由 ===

def resolve_company(channel_id: str = None, chat_id: str = None) -> dict:
    """從 Channel ID 或 chat_id 解析對應公司

    優先用 channel_id（LINE webhook 帶入），
    fallback 用 chat_id 查 conversation_state，
    最終 fallback 到預設公司。
    """
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
    # Fallback 到環境變數（相容舊的單一公司設定）
    return os.environ.get("LINE_CHANNEL_SECRET", "")


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

    # Fallback 到環境變數
    return os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")


def get_gdrive_folder(company_id: int) -> str:
    """取得公司的 GDrive 資料夾名稱"""
    company = _company_cache.get(company_id)
    if company:
        return company.get("gdrive_folder", "福利社")
    return "福利社"
