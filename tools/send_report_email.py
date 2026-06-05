#!/usr/bin/env python3
"""Send shanbot report emails through Gmail API."""

from __future__ import annotations

import argparse
import base64
import mimetypes
import os
import sys
from email.message import EmailMessage
from pathlib import Path

DEFAULT_TO = "uiy022803@gmail.com"
TOKEN_PATH = "/home/simon/.google-oauth/nomis_token.json"


def _attachment_mime(path: Path) -> tuple[str, str]:
    if path.suffix.lower() == ".xlsx":
        return ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    guessed, _ = mimetypes.guess_type(str(path))
    if guessed and "/" in guessed:
        maintype, subtype = guessed.split("/", 1)
        return maintype, subtype
    return "application", "octet-stream"


def _build_message(to_addr: str, subject: str, body: str, attachments: list[Path]) -> EmailMessage:
    message = EmailMessage()
    message["To"] = to_addr
    message["Subject"] = subject
    message.set_content(body, charset="utf-8")

    for path in attachments:
        if not path.is_file():
            raise FileNotFoundError(f"attachment not found: {path}")

        maintype, subtype = _attachment_mime(path)
        message.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )

    return message


def _message_to_raw(message: EmailMessage) -> str:
    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    return encoded.rstrip("=")


def _build_gmail_service(token_path: Path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(token_path))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds)


def send_email(
    to_addr: str,
    subject: str,
    body: str,
    attachments: list[Path],
    token_path: Path,
) -> str:
    message = _build_message(to_addr, subject, body, attachments)
    service = _build_gmail_service(token_path)
    sent = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": _message_to_raw(message)})
        .execute()
    )
    message_id = sent.get("id")
    if not message_id:
        raise RuntimeError(f"Gmail send response missing id: {sent}")
    return message_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a shanbot report email through Gmail API")
    parser.add_argument("--subject", required=True, help="Email subject")
    parser.add_argument("--body", required=True, help="Email plain-text body")
    parser.add_argument("--attach", action="append", default=[], help="Attachment path; repeatable")
    parser.add_argument(
        "--to",
        default=os.environ.get("SHANBOT_REPORT_EMAIL", DEFAULT_TO),
        help=f"Recipient email (default: SHANBOT_REPORT_EMAIL or {DEFAULT_TO})",
    )
    parser.add_argument(
        "--token-path",
        default=os.environ.get("GMAIL_TOKEN_PATH", TOKEN_PATH),
        help="Gmail OAuth token path (default: GMAIL_TOKEN_PATH or VPS token path)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and validate the MIME message without calling Gmail",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    attachments = [Path(item).expanduser().resolve() for item in args.attach]
    token_path = Path(args.token_path).expanduser().resolve()

    try:
        if args.dry_run:
            message = _build_message(args.to, args.subject, args.body, attachments)
            raw = _message_to_raw(message)
            print(f"DRY_RUN bytes={len(raw)} to={args.to} attachments={len(attachments)}")
            return 0

        message_id = send_email(args.to, args.subject, args.body, attachments, token_path)
        print(f"SENT id={message_id} to={args.to}")
        return 0
    except Exception as exc:
        print(f"ERROR send_report_email: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
