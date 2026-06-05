"""Create Gmail auto-reply drafts for processed Xiaoyu supplier replies."""

import base64
import logging
from email.mime.text import MIMEText

TOKEN_PATH = "/home/simon/.google-oauth/nomis_token.json"

logger = logging.getLogger("shanbot.email_reply_draft")


def _build_body(
    week: str,
    aliases_learned: int,
    staging_updates: int,
    new_suppliers: int,
    processed_rows: list[dict],
) -> str:
    lines = []
    for row in processed_rows:
        supplier_name = row.get("supplier_name", "")
        if row.get("choice_type") == "new_from_remark":
            remark = row.get("remark") or row.get("canonical") or ""
            lines.append(f"  · {supplier_name} → 都不是（{remark}）")
        else:
            canonical = row.get("canonical", "")
            lines.append(f"  · {supplier_name} → {canonical}")

    if not lines:
        lines.append("  · 無可處理資料")

    return (
        f"謝謝小魚，{week} 的回覆我已經處理好了。\n\n"
        "處理結果：\n"
        f"{chr(10).join(lines)}\n\n"
        f"共學習了 {aliases_learned} 個新供應商別名，"
        f"更新了 {staging_updates} 筆帳務記錄，"
        f"新建了 {new_suppliers} 家供應商。\n\n"
        "下次遇到同樣的供應商名稱，系統會自動對應到正確的廠商，不需要再填一次。"
    )


def create_reply_draft(
    week: str,
    thread_id: str,
    aliases_learned: int,
    staging_updates: int,
    new_suppliers: int,
    processed_rows: list[dict],
) -> str | None:
    """Create a plain-text Gmail draft and return its draft id."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except Exception as exc:
        logger.error("Gmail draft dependencies unavailable: %s", exc)
        return None

    subject = (
        f"【小膳】{week} 收到妳的回覆 — 已處理 {staging_updates} 筆，"
        f"學習 {aliases_learned} 個新供應商別名"
    )
    body_text = _build_body(
        week=week,
        aliases_learned=aliases_learned,
        staging_updates=staging_updates,
        new_suppliers=new_suppliers,
        processed_rows=processed_rows,
    )

    msg = MIMEText(body_text, "plain", "utf-8")
    msg["To"] = "uiy022803@gmail.com"
    msg["Cc"] = "poyuchen@go.thu.edu.tw"
    msg["Subject"] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    draft_body = {"message": {"raw": raw}}
    if thread_id:
        draft_body["message"]["threadId"] = thread_id

    try:
        creds = Credentials.from_authorized_user_file(TOKEN_PATH)
        service = build("gmail", "v1", credentials=creds)
        result = (
            service.users()
            .drafts()
            .create(userId="me", body=draft_body)
            .execute()
        )
        draft_id = result.get("id")
        logger.info("Gmail reply draft created: %s", draft_id)
        return draft_id
    except Exception as exc:
        logger.error("create_reply_draft failed: %s", exc)
        return None
