"""LINE Messaging API 封裝（直接 REST，無 SDK 依賴）"""

import os
import logging
import requests

logger = logging.getLogger("shanbot.line")

API_BASE = "https://api.line.me"


class LineService:
    def __init__(self):
        self.token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        self.channel_id = os.environ.get("LINE_CHANNEL_ID", "")
        self.channel_secret = os.environ.get("LINE_CHANNEL_SECRET", "")
        self._headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def reply(self, reply_token: str, text: str) -> bool:
        """回覆 webhook（必須在數秒內回應）"""
        if not self.token or not reply_token:
            return False
        chunks = [text[i:i + 4900] for i in range(0, len(text), 4900)]
        messages = [{"type": "text", "text": c} for c in chunks[:5]]
        try:
            resp = requests.post(
                f"{API_BASE}/v2/bot/message/reply",
                headers=self._headers,
                json={"replyToken": reply_token, "messages": messages},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error(f"Reply failed: {resp.status_code} {resp.text}")
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Reply error: {e}")
            return False

    def push(self, to: str, text: str) -> bool:
        """主動推送訊息"""
        if not self.token or not to:
            return False
        chunks = [text[i:i + 4900] for i in range(0, len(text), 4900)]
        messages = [{"type": "text", "text": c} for c in chunks[:5]]
        try:
            resp = requests.post(
                f"{API_BASE}/v2/bot/message/push",
                headers=self._headers,
                json={"to": to, "messages": messages},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error(f"Push failed: {resp.status_code} {resp.text}")
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Push error: {e}")
            return False

    def push_flex(self, to: str, alt_text: str, flex_content: dict) -> bool:
        """推送 Flex Message"""
        if not self.token or not to:
            return False
        try:
            resp = requests.post(
                f"{API_BASE}/v2/bot/message/push",
                headers=self._headers,
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
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Push flex error: {e}")
            return False

    def reply_flex(self, reply_token: str, alt_text: str, flex_content: dict) -> bool:
        """回覆 Flex Message"""
        if not self.token or not reply_token:
            return False
        try:
            resp = requests.post(
                f"{API_BASE}/v2/bot/message/reply",
                headers=self._headers,
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
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Reply flex error: {e}")
            return False

    def reply_image(self, reply_token: str, image_url: str,
                    preview_url: str = "") -> bool:
        """回覆圖片訊息"""
        if not self.token or not reply_token:
            return False
        msg = {
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": preview_url or image_url,
        }
        try:
            resp = requests.post(
                f"{API_BASE}/v2/bot/message/reply",
                headers=self._headers,
                json={"replyToken": reply_token, "messages": [msg]},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Reply image error: {e}")
            return False

    def reply_messages(self, reply_token: str, messages: list[dict]) -> bool:
        """回覆多則訊息（最多 5 則）"""
        if not self.token or not reply_token or not messages:
            return False
        try:
            resp = requests.post(
                f"{API_BASE}/v2/bot/message/reply",
                headers=self._headers,
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
                   preview_url: str = "") -> bool:
        """推送圖片訊息"""
        if not self.token or not to:
            return False
        msg = {
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": preview_url or image_url,
        }
        try:
            resp = requests.post(
                f"{API_BASE}/v2/bot/message/push",
                headers=self._headers,
                json={"to": to, "messages": [msg]},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Push image error: {e}")
            return False

    def get_content(self, message_id: str) -> bytes | None:
        """下載使用者上傳的檔案/圖片"""
        try:
            resp = requests.get(
                f"{API_BASE}/v2/bot/message/{message_id}/content",
                headers={"Authorization": f"Bearer {self.token}"},
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
                headers=self._headers,
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
                headers=self._headers,
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception:
            return None
