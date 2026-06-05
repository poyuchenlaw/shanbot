"""Gmail inbox polling for Xiaoyu XLSX replies."""

from __future__ import annotations

import argparse
import base64
import logging
import os
import re
import sys

TOKEN_PATH = "/home/simon/.google-oauth/nomis_token.json"
XIAOYU_EMAIL = "uiy022803@gmail.com"
SHANBOT_LABEL_PREFIX = "shanbot/reply"

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

logger = logging.getLogger("shanbot.gmail_watch")


def _build_gmail_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    return build("gmail", "v1", credentials=creds)


def _ensure_label(service, label_name: str) -> str:
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for label in labels:
        if label.get("name") == label_name:
            return label["id"]

    created = (
        service.users()
        .labels()
        .create(
            userId="me",
            body={
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        )
        .execute()
    )
    return created["id"]


def _extract_week_from_subject(subject: str) -> str | None:
    match = re.search(r"\bW(\d+)\b", subject or "", re.IGNORECASE)
    if not match:
        return None
    return f"W{int(match.group(1))}"


def _decode_b64url(data: str) -> bytes:
    padded = data + ("=" * (-len(data) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _walk_parts(part: dict):
    yield part
    for child in part.get("parts", []) or []:
        yield from _walk_parts(child)


def _get_attachment_xlsx(service, msg_id: str) -> list[tuple[str, bytes]]:
    message = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    attachments = []

    for part in _walk_parts(message.get("payload", {})):
        filename = part.get("filename") or ""
        if not filename.lower().endswith(".xlsx"):
            continue

        body = part.get("body", {}) or {}
        if body.get("attachmentId"):
            att = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=msg_id, id=body["attachmentId"])
                .execute()
            )
            data = att.get("data", "")
        else:
            data = body.get("data", "")

        if data:
            attachments.append((filename, _decode_b64url(data)))

    return attachments


def _message_subject(message: dict) -> str:
    headers = message.get("payload", {}).get("headers", []) or []
    for header in headers:
        if header.get("name", "").lower() == "subject":
            return header.get("value", "")
    return ""


def _safe_filename(filename: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("_") or "reply.xlsx"


def _list_unread_reply_messages(service) -> list[dict]:
    query = f"from:{XIAOYU_EMAIL} is:unread has:attachment"
    messages = []
    page_token = None
    while True:
        kwargs = {"userId": "me", "q": query}
        if page_token:
            kwargs["pageToken"] = page_token
        result = service.users().messages().list(**kwargs).execute()
        messages.extend(result.get("messages", []) or [])
        page_token = result.get("nextPageToken")
        if not page_token:
            return messages


def poll_shanbot_replies(dry_run: bool = False) -> list[dict]:
    """Poll unread Xiaoyu replies, process XLSX attachments, and return summaries."""
    from handlers.email_reply_parser import parse_xlsx_reply

    service = _build_gmail_service()
    results = []

    for item in _list_unread_reply_messages(service):
        msg_id = item["id"]
        meta = service.users().messages().get(
            userId="me",
            id=msg_id,
            format="metadata",
            metadataHeaders=["Subject"],
        ).execute()
        subject = _message_subject(meta)
        week = _extract_week_from_subject(subject)
        thread_id = meta.get("threadId", "")

        if not week:
            logger.warning("Skip message %s: subject has no week: %s", msg_id, subject)
            results.append({"message_id": msg_id, "skipped": "missing_week", "subject": subject})
            continue

        attachments = _get_attachment_xlsx(service, msg_id)
        if not attachments:
            logger.info("Skip message %s: no xlsx attachment", msg_id)
            results.append({"message_id": msg_id, "skipped": "no_xlsx", "week": week})
            continue

        paths = []
        for filename, content in attachments:
            path = f"/tmp/shanbot_reply_{week}_{_safe_filename(filename)}"
            if dry_run:
                logger.info("[dry-run] save temp attachment for parser only: %s", path)
            with open(path, "wb") as fh:
                fh.write(content)
            paths.append(path)

        label_name = f"{SHANBOT_LABEL_PREFIX}/{week}_unconfirmed"
        if dry_run:
            logger.info("[dry-run] would label %s as %s and mark read", msg_id, label_name)
        else:
            label_id = _ensure_label(service, label_name)
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"addLabelIds": [label_id], "removeLabelIds": ["UNREAD"]},
            ).execute()

        for path in paths:
            parsed = parse_xlsx_reply(
                path,
                week=week,
                thread_id=thread_id,
                dry_run=dry_run,
                create_reply_draft=not dry_run,
            )
            parsed.update({"message_id": msg_id, "thread_id": thread_id, "week": week, "path": path})
            results.append(parsed)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll Gmail for shanbot XLSX replies")
    parser.add_argument("--dry-run", action="store_true", help="Log only; no DB writes or Gmail labels")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for result in poll_shanbot_replies(dry_run=args.dry_run):
        print(result)


if __name__ == "__main__":
    main()
