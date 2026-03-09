"""小膳 Bot — 團膳公司內帳系統 LINE Bot (FastAPI)"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# 載入環境變數
load_dotenv(os.path.join(os.path.dirname(__file__), "config", ".env"))

import state_manager as sm
from services.line_service import LineService
from task_manager import (
    HeartbeatScheduler,
    MarketSyncScheduler,
    MonthlySummaryScheduler,
    WebhookGuardScheduler,
    ExternalAPIGuardScheduler,
)

# Logging
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO")),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "logs", "out.log"),
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("shanbot")

# 全域
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
PORT = int(os.environ.get("PORT", 8025))

line_service: LineService | None = None
api_guard: ExternalAPIGuardScheduler | None = None
ADMIN_LINE_USER_ID = ""
ALLOWED_GROUPS: set[str] = set()


def verify_signature(body: bytes, signature: str) -> bool:
    """HMAC-SHA256 簽名驗證"""
    if not CHANNEL_SECRET:
        return True  # 開發模式
    mac = hmac.new(CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256)
    expected = base64.b64encode(mac.digest()).decode("utf-8")
    return hmac.compare_digest(expected, signature)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """啟動/關閉生命週期"""
    global line_service, api_guard, ADMIN_LINE_USER_ID, ALLOWED_GROUPS

    # 初始化 DB
    sm.init_db()
    logger.info("Database initialized")

    # 載入設定
    ADMIN_LINE_USER_ID = sm.get_config("admin_user_id", "")
    groups_json = sm.get_config("allowed_groups", "[]")
    ALLOWED_GROUPS = set(json.loads(groups_json))

    # GDrive 資料夾結構
    try:
        from services.gdrive_service import init_folder_structure
        month_path = init_folder_structure()
        logger.info(f"GDrive folder ready: {month_path}")
    except Exception as e:
        logger.warning(f"GDrive init skipped: {e}")

    # LINE 服務
    line_service = LineService()

    # 排程器
    primary_group = sm.get_config("primary_group_id", "")

    heartbeat = HeartbeatScheduler(line_service, primary_group)
    heartbeat.start()

    market_sync = MarketSyncScheduler()
    market_sync.start()

    monthly = MonthlySummaryScheduler(line_service, primary_group)
    monthly.start()

    webhook_guard = WebhookGuardScheduler()
    webhook_guard.start()

    api_guard = ExternalAPIGuardScheduler()
    api_guard.start()

    logger.info(f"小膳 Bot started on port {PORT}")
    logger.info(f"LINE Webhook URL: https://shanbot.kuangshin.tw/webhook")
    logger.info(f"Admin: {'set' if ADMIN_LINE_USER_ID else 'not set'}")
    logger.info(f"Groups: {len(ALLOWED_GROUPS)}")

    yield

    heartbeat.stop()
    market_sync.stop()
    monthly.stop()
    webhook_guard.stop()
    api_guard.stop()
    logger.info("小膳 Bot stopped")


app = FastAPI(title="ShanBot", version="2.4.0", lifespan=lifespan)

# 靜態檔案路由 — 生成的菜色圖片
IMAGES_DIR = os.path.join(os.path.dirname(__file__), "data", "images")
os.makedirs(IMAGES_DIR, exist_ok=True)
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")


@app.post("/webhook")
async def webhook(request: Request):
    """LINE Webhook 入口"""
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    if not verify_signature(body, signature):
        return JSONResponse({"error": "Invalid signature"}, status_code=403)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    events = payload.get("events", [])
    if events:
        logger.info(f"Webhook received {len(events)} event(s): "
                     f"{[e.get('type','?') for e in events]}")
    for event in events:
        asyncio.create_task(_process_event(event))

    return {"status": "ok"}


async def _process_event(event: dict):
    """處理單一事件（非阻塞）"""
    global ADMIN_LINE_USER_ID, ALLOWED_GROUPS

    try:
        event_type = event.get("type", "")
        source = event.get("source", {})
        source_type = source.get("type", "")
        user_id = source.get("userId", "")
        group_id = source.get("groupId", "") or source.get("roomId", "") or user_id
        reply_token = event.get("replyToken", "")

        # 自動偵測管理員
        if not ADMIN_LINE_USER_ID and user_id:
            ADMIN_LINE_USER_ID = user_id
            sm.set_config("admin_user_id", user_id)
            logger.info(f"Admin set: {user_id}")

        # 自動加入群組
        if source_type == "group" and group_id not in ALLOWED_GROUPS:
            ALLOWED_GROUPS.add(group_id)
            sm.set_config("allowed_groups", json.dumps(list(ALLOWED_GROUPS)))
            if not sm.get_config("primary_group_id"):
                sm.set_config("primary_group_id", group_id)
            logger.info(f"Group added: {group_id}")

        if event_type == "message":
            msg = event.get("message", {})
            msg_type = msg.get("type", "")

            if msg_type == "text":
                text = msg.get("text", "").strip()
                if text:
                    await _handle_text(text, group_id, user_id, reply_token)

            elif msg_type == "image":
                msg_id = msg.get("id", "")
                await _handle_image(msg_id, group_id, user_id, reply_token)

            elif msg_type == "file":
                msg_id = msg.get("id", "")
                filename = msg.get("fileName", "unknown")
                await _handle_file(msg_id, filename, group_id, user_id, reply_token)

            elif msg_type == "sticker":
                await _handle_sticker(group_id, user_id, reply_token)

        elif event_type == "postback":
            postback_data = event.get("postback", {}).get("data", "")
            if postback_data:
                await _handle_postback(postback_data, group_id, user_id, reply_token)

        elif event_type == "join":
            if line_service:
                line_service.push(group_id,
                    "大家好！我是小膳 🍳\n"
                    "我可以幫忙管理每日採購記錄、比價、出報表。\n"
                    "上傳收據照片，我就會自動辨識幫你記帳！\n"
                    "輸入「help」看完整指令。"
                )

    except Exception as e:
        logger.error(f"Event processing error: {e}", exc_info=True)


async def _handle_text(text: str, group_id: str, user_id: str, reply_token: str):
    """處理文字訊息"""
    from handlers.command_handler import handle_text

    user_name = ""
    if line_service:
        profile = line_service.get_group_member_profile(group_id, user_id)
        if profile:
            user_name = profile.get("displayName", "")

    reply = await handle_text(
        line_service, text, group_id, user_id, user_name, reply_token
    )
    if reply and line_service:
        line_service.reply(reply_token, reply)


async def _handle_image(message_id: str, group_id: str, user_id: str, reply_token: str):
    """處理圖片上傳 — 根據對話狀態路由到菜單照片或收據 OCR"""
    # 檢查是否在等待菜色照片
    state, state_data = sm.get_state(group_id)
    if state == "waiting_menu_photo":
        sm.clear_state(group_id)
        from handlers.menu_handler import handle_menu_photo
        reply = await handle_menu_photo(
            line_service, message_id, group_id, user_id, reply_token
        )
        if reply and line_service:
            line_service.reply(reply_token, reply)
        return

    # 檢查是否在等待契約照片
    if state == "waiting_contract_photo":
        # 下載圖片 → 存本地 → 呼叫契約解析
        if reply_token and line_service:
            line_service.reply(reply_token, "📄 收到契約照片，AI 辨識中...")
        image_bytes = line_service.get_content(message_id) if line_service else None
        if not image_bytes:
            if line_service:
                line_service.push(group_id, "❌ 圖片下載失敗，請重新上傳")
            return
        # Save locally
        images_dir = os.path.join(os.path.dirname(__file__), "data", "images")
        os.makedirs(images_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        local_path = os.path.join(images_dir, f"contract_{ts}.jpg")
        with open(local_path, "wb") as f:
            f.write(image_bytes)
        from handlers.command_handler import handle_contract_upload
        reply = await handle_contract_upload(local_path, group_id)
        if reply and line_service:
            line_service.push(group_id, reply)
        return

    # 從拍照按鈕進入（或直接傳圖）→ 收據/對帳單 OCR
    if state == "waiting_receipt_photo":
        sm.clear_state(group_id)  # 清除暫態，photo_handler 會設新狀態

    from handlers.photo_handler import handle_photo_received
    reply = await handle_photo_received(
        line_service, message_id, group_id, user_id, reply_token
    )
    if reply and line_service:
        line_service.reply(reply_token, reply)


async def _handle_postback(data_str: str, group_id: str, user_id: str, reply_token: str):
    """處理 Postback 事件（六宮格選單 + 子動作）"""
    from handlers.postback_handler import handle_postback

    try:
        await handle_postback(line_service, data_str, group_id, user_id, reply_token)
    except Exception as e:
        logger.error(f"Postback error: {e}", exc_info=True)
        if line_service:
            line_service.reply(reply_token, "處理發生錯誤，請稍後再試")


async def _handle_file(message_id: str, filename: str, group_id: str,
                       user_id: str, reply_token: str):
    """處理檔案上傳（Excel/PDF 自動分類歸檔）"""
    from handlers.file_handler import handle_file_received

    reply = await handle_file_received(
        line_service, message_id, filename, group_id, user_id, reply_token
    )
    if reply and line_service:
        line_service.reply(reply_token, reply)


async def _handle_sticker(group_id: str, user_id: str, reply_token: str):
    """貼圖訊息 — 僅在等待 OCR 確認時視為確認"""
    state, state_data = sm.get_state(group_id)
    if state == "waiting_ocr_confirm":
        staging_id = state_data.get("staging_id")
        if staging_id:
            from handlers.command_handler import _confirm_staging
            sm.clear_state(group_id)
            reply = await _confirm_staging(staging_id, group_id)
            if reply and line_service:
                line_service.reply(reply_token, reply)


# === 管理端點 ===

@app.get("/health")
async def health():
    """健康檢查（含 webhook + 外部 API 狀態）"""
    counts = sm.get_table_counts()
    stats = sm.get_staging_stats()
    return {
        "status": "ok",
        "bot": "shanbot",
        "version": "2.5.0",
        "port": PORT,
        "admin_set": bool(ADMIN_LINE_USER_ID),
        "groups": len(ALLOWED_GROUPS),
        "tables": counts,
        "staging": stats,
        "external_apis": api_guard.last_status if api_guard else {},
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/heartbeat")
async def manual_heartbeat():
    """手動觸發心跳報告"""
    # 會在 task_manager 裡實作
    return {"status": "triggered"}


@app.post("/market-sync")
async def manual_market_sync():
    """手動觸發行情同步"""
    from services.market_service import sync_all_market_data
    result = await sync_all_market_data()
    return {"status": "ok", "result": result}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
