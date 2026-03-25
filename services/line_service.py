"""LINE Messaging API 封裝（v3.0 — 多租戶多 Token 支援）"""

import os
import logging
import requests

logger = logging.getLogger("shanbot.line")

API_BASE = "https://api.line.me"
API_DATA_BASE = "https://api-data.line.me"


def _sanitize_flex(obj):
    """遞迴修復 Flex Message 中的空 text 欄位（LINE API 要求 non-empty）"""
    if isinstance(obj, dict):
        if obj.get("type") == "text" and "text" in obj:
            if not obj["text"]:
                obj["text"] = "-"
        for v in obj.values():
            _sanitize_flex(v)
    elif isinstance(obj, list):
        for item in obj:
            _sanitize_flex(item)


class LineService:
    """多租戶 LINE 服務 — 根據 company_id 使用對應的 Token"""

    def __init__(self):
        # 預設 Token（相容舊設定，single-tenant fallback）
        self._default_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        self.channel_id = os.environ.get("LINE_CHANNEL_ID", "")
        self.channel_secret = os.environ.get("LINE_CHANNEL_SECRET", "")
        # 當前 context 的 token（每次 webhook 設定）
        self._current_token = self._default_token

    def _headers(self, token: str = None) -> dict:
        """產生帶正確 Token 的 headers"""
        t = token or self._current_token or self._default_token
        return {
            "Authorization": f"Bearer {t}",
            "Content-Type": "application/json",
        }

    def set_context_token(self, token: str):
        """設定當前 webhook context 的 Token"""
        if token:
            self._current_token = token

    def reset_context(self):
        """重設為預設 Token"""
        self._current_token = self._default_token

    def get_token_for_company(self, company_id: int) -> str:
        """從 company_service 取得指定公司的 Token"""
        from services.company_service import get_access_token
        return get_access_token(company_id=company_id)

    def reply(self, reply_token: str, text: str, company_id: int = None) -> bool:
        """回覆 webhook（必須在數秒內回應）"""
        token = self.get_token_for_company(company_id) if company_id else None
        h = self._headers(token)
        if not (token or self._current_token or self._default_token) or not reply_token:
            return False
        chunks = [text[i:i + 4900] for i in range(0, len(text), 4900)]
        messages = [{"type": "text", "text": c} for c in chunks[:5]]
        try:
            resp = requests.post(
                f"{API_BASE}/v2/bot/message/reply",
                headers=h,
                json={"replyToken": reply_token, "messages": messages},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error(f"Reply failed: {resp.status_code} {resp.text}")
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Reply error: {e}")
            return False

    def push(self, to: str, text: str, company_id: int = None) -> bool:
        """主動推送訊息"""
        token = self.get_token_for_company(company_id) if company_id else None
        h = self._headers(token)
        effective_token = token or self._current_token or self._default_token
        if not effective_token or not to:
            return False
        chunks = [text[i:i + 4900] for i in range(0, len(text), 4900)]
        messages = [{"type": "text", "text": c} for c in chunks[:5]]
        try:
            resp = requests.post(
                f"{API_BASE}/v2/bot/message/push",
                headers=h,
                json={"to": to, "messages": messages},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error(f"Push failed: {resp.status_code} {resp.text}")
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Push error: {e}")
            return False

    def push_flex(self, to: str, alt_text: str, flex_content: dict,
                  company_id: int = None) -> bool:
        """推送 Flex Message"""
        token = self.get_token_for_company(company_id) if company_id else None
        h = self._headers(token)
        effective_token = token or self._current_token or self._default_token
        if not effective_token or not to:
            return False
        _sanitize_flex(flex_content)
        try:
            resp = requests.post(
                f"{API_BASE}/v2/bot/message/push",
                headers=h,
                json={
                    "to": to,
                    "messages": [{
                        "type": "flex",
                        "altText": alt_text,
                        "contents": flex_content,
                    }],
                },
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error(f"Push flex failed: {resp.status_code} {resp.text}")
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Push flex error: {e}")
            return False

    def reply_flex(self, reply_token: str, alt_text: str, flex_content: dict,
                   company_id: int = None) -> bool:
        """回覆 Flex Message"""
        token = self.get_token_for_company(company_id) if company_id else None
        h = self._headers(token)
        effective_token = token or self._current_token or self._default_token
        if not effective_token or not reply_token:
            logger.warning(f"Reply flex skipped: token={'set' if effective_token else 'missing'}, "
                           f"reply_token={'set' if reply_token else 'missing'}")
            return False
        _sanitize_flex(flex_content)
        try:
            resp = requests.post(
                f"{API_BASE}/v2/bot/message/reply",
                headers=h,
                json={
                    "replyToken": reply_token,
                    "messages": [{
                        "type": "flex",
                        "altText": alt_text,
                        "contents": flex_content,
                    }],
                },
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error(f"Reply flex failed: {resp.status_code} {resp.text}")
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Reply flex error: {e}")
            return False

    def reply_image(self, reply_token: str, image_url: str,
                    preview_url: str = "", company_id: int = None) -> bool:
        """回覆圖片訊息"""
        token = self.get_token_for_company(company_id) if company_id else None
        h = self._headers(token)
        effective_token = token or self._current_token or self._default_token
        if not effective_token or not reply_token:
            return False
        msg = {
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": preview_url or image_url,
        }
        try:
            resp = requests.post(
                f"{API_BASE}/v2/bot/message/reply",
                headers=h,
                json={"replyToken": reply_token, "messages": [msg]},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Reply image error: {e}")
            return False

    def reply_messages(self, reply_token: str, messages: list[dict],
                       company_id: int = None) -> bool:
        """回覆多則訊息（最多 5 則）"""
        token = self.get_token_for_company(company_id) if company_id else None
        h = self._headers(token)
        effective_token = token or self._current_token or self._default_token
        if not effective_token or not reply_token or not messages:
            return False
        try:
            resp = requests.post(
                f"{API_BASE}/v2/bot/message/reply",
                headers=h,
                json={"replyToken": reply_token, "messages": messages[:5]},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error(f"Reply messages failed: {resp.status_code} {resp.text}")
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Reply messages error: {e}")
            return False

    def push_image(self, to: str, image_url: str,
                   preview_url: str = "", company_id: int = None) -> bool:
        """推送圖片訊息"""
        token = self.get_token_for_company(company_id) if company_id else None
        h = self._headers(token)
        effective_token = token or self._current_token or self._default_token
        if not effective_token or not to:
            return False
        msg = {
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": preview_url or image_url,
        }
        try:
            resp = requests.post(
                f"{API_BASE}/v2/bot/message/push",
                headers=h,
                json={"to": to, "messages": [msg]},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Push image error: {e}")
            return False

    def get_content(self, message_id: str, company_id: int = None) -> bytes | None:
        """下載使用者上傳的檔案/圖片"""
        token = self.get_token_for_company(company_id) if company_id else None
        effective_token = token or self._current_token or self._default_token
        try:
            resp = requests.get(
                f"{API_DATA_BASE}/v2/bot/message/{message_id}/content",
                headers={"Authorization": f"Bearer {effective_token}"},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.content
            logger.error(f"Get content failed: {resp.status_code}")
            return None
        except Exception as e:
            logger.error(f"Get content error: {e}")
            return None

    def get_profile(self, user_id: str) -> dict | None:
        """取得使用者基本資訊"""
        try:
            resp = requests.get(
                f"{API_BASE}/v2/bot/profile/{user_id}",
                headers=self._headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception:
            return None

    def get_group_member_profile(self, group_id: str, user_id: str) -> dict | None:
        """取得群組內的成員資訊"""
        try:
            resp = requests.get(
                f"{API_BASE}/v2/bot/group/{group_id}/member/{user_id}",
                headers=self._headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception:
            return None
