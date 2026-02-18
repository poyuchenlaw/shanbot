"""Rich Menu 管理 — 建立、上傳圖片、設為預設"""

import json
import logging
import os

import requests

logger = logging.getLogger("shanbot.richmenu")

API_BASE = "https://api.line.me"
DATA_BASE = "https://api-data.line.me"

RICHMENU_JSON = {
    "size": {"width": 2500, "height": 1686},
    "selected": True,
    "name": "shanbot-main-menu-v2",
    "chatBarText": "小膳功能選單",
    "areas": [
        {
            "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
            "action": {
                "type": "postback", "label": "拍照記帳",
                "data": "menu=camera", "displayText": "📸 拍照記帳",
            },
        },
        {
            "bounds": {"x": 833, "y": 0, "width": 833, "height": 843},
            "action": {
                "type": "postback", "label": "財務資料",
                "data": "menu=finance_upload", "displayText": "📁 財務資料提供和確認",
            },
        },
        {
            "bounds": {"x": 1666, "y": 0, "width": 834, "height": 843},
            "action": {
                "type": "postback", "label": "採購管理",
                "data": "menu=purchase", "displayText": "🛒 採購管理",
            },
        },
        {
            "bounds": {"x": 0, "y": 843, "width": 833, "height": 843},
            "action": {
                "type": "postback", "label": "菜單企劃",
                "data": "menu=menu_plan", "displayText": "🍽️ 菜單企劃",
            },
        },
        {
            "bounds": {"x": 833, "y": 843, "width": 833, "height": 843},
            "action": {
                "type": "postback", "label": "報表生成",
                "data": "menu=reports", "displayText": "📊 報表生成",
            },
        },
        {
            "bounds": {"x": 1666, "y": 843, "width": 834, "height": 843},
            "action": {
                "type": "postback", "label": "使用說明",
                "data": "menu=guide", "displayText": "❓ 使用說明",
            },
        },
    ],
}


class RichMenuService:
    def __init__(self, token: str = ""):
        self.token = token or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        self._headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def create_rich_menu(self) -> str | None:
        """建立 Rich Menu，回傳 richMenuId"""
        try:
            resp = requests.post(
                f"{API_BASE}/v2/bot/richmenu",
                headers=self._headers,
                json=RICHMENU_JSON,
                timeout=15,
            )
            if resp.status_code == 200:
                menu_id = resp.json().get("richMenuId", "")
                logger.info(f"Rich menu created: {menu_id}")
                return menu_id
            logger.error(f"Create rich menu failed: {resp.status_code} {resp.text}")
            return None
        except Exception as e:
            logger.error(f"Create rich menu error: {e}")
            return None

    def upload_image(self, menu_id: str, image_path: str) -> bool:
        """上傳 Rich Menu 圖片"""
        if not os.path.exists(image_path):
            logger.error(f"Image not found: {image_path}")
            return False

        ext = os.path.splitext(image_path)[1].lower()
        content_type = "image/png" if ext == ".png" else "image/jpeg"

        try:
            with open(image_path, "rb") as f:
                resp = requests.post(
                    f"{DATA_BASE}/v2/bot/richmenu/{menu_id}/content",
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": content_type,
                    },
                    data=f,
                    timeout=30,
                )
            if resp.status_code == 200:
                logger.info(f"Rich menu image uploaded: {menu_id}")
                return True
            logger.error(f"Upload image failed: {resp.status_code} {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Upload image error: {e}")
            return False

    def set_default(self, menu_id: str) -> bool:
        """設為所有用戶的預設 Rich Menu"""
        try:
            resp = requests.post(
                f"{API_BASE}/v2/bot/user/all/richmenu/{menu_id}",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Length": "0",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                logger.info(f"Rich menu set as default: {menu_id}")
                return True
            logger.error(f"Set default failed: {resp.status_code} {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Set default error: {e}")
            return False

    def list_menus(self) -> list[dict]:
        """列出所有 Rich Menu"""
        try:
            resp = requests.get(
                f"{API_BASE}/v2/bot/richmenu/list",
                headers=self._headers,
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json().get("richmenus", [])
            return []
        except Exception:
            return []

    def delete_menu(self, menu_id: str) -> bool:
        """刪除 Rich Menu"""
        try:
            resp = requests.delete(
                f"{API_BASE}/v2/bot/richmenu/{menu_id}",
                headers=self._headers,
                timeout=15,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def get_default_id(self) -> str | None:
        """取得目前預設 Rich Menu ID"""
        try:
            resp = requests.get(
                f"{API_BASE}/v2/bot/user/all/richmenu",
                headers=self._headers,
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json().get("richMenuId")
            return None
        except Exception:
            return None

    def deploy(self, image_path: str = None) -> str | None:
        """一鍵部署：建立 → 上傳圖片 → 設為預設"""
        menu_id = self.create_rich_menu()
        if not menu_id:
            return None

        if image_path:
            if not self.upload_image(menu_id, image_path):
                logger.warning("Image upload failed, menu created without image")

        if self.set_default(menu_id):
            return menu_id

        return menu_id
