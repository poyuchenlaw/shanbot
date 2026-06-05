#!/usr/bin/env python3
"""
send_weekly_email_draft.py — shanbot 週報 Gmail Draft 產生器
googleapiclient + nomis_token (OAuth2)

--dry-run  (預設) 只 print MIME size
--apply    真的 create draft
--delete <draft_id>  刪舊 draft（可多次）
--list     列出所有草稿
"""
import argparse, base64, mimetypes, os, sys
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

TOKEN_PATH = "/home/simon/.google-oauth/nomis_token.json"

def build_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    return build("gmail", "v1", credentials=creds)

def build_mime(subject, to_list, cc_list, html_body, xlsx_path):
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)
    if xlsx_path:
        if not os.path.exists(xlsx_path):
            sys.exit(f"[ERROR] Attachment not found: {xlsx_path}")
        fname = os.path.basename(xlsx_path)
        ctype, _ = mimetypes.guess_type(xlsx_path)
        if not ctype:
            ctype = "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        with open(xlsx_path, "rb") as f:
            part = MIMEBase(maintype, subtype)
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", fname))
        msg.attach(part)
    return msg

def create_draft(service, mime_msg):
    raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("ascii")
    return service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()

def delete_draft(service, draft_id):
    try:
        service.users().drafts().delete(userId="me", id=draft_id).execute()
        return True
    except Exception as e:
        print(f"[WARN] delete {draft_id}: {e}", file=sys.stderr)
        return False

def list_drafts(service):
    result = service.users().drafts().list(userId="me").execute()
    for d in result.get("drafts", []):
        meta = service.users().drafts().get(userId="me", id=d["id"], format="metadata").execute()
        hdrs = {h["name"]: h["value"] for h in meta["message"].get("payload", {}).get("headers", [])}
        print(f"id={d['id']}  to={hdrs.get('To','?')[:30]}  subj={hdrs.get('Subject','?')[:60]}")

def main():
    parser = argparse.ArgumentParser(description="shanbot 週報 Gmail Draft 產生器")
    parser.add_argument("--week", default="", help="週次 e.g. W20")
    parser.add_argument("--recipients", default="uiy022803@gmail.com")
    parser.add_argument("--cc", default="poyuchen@go.thu.edu.tw")
    parser.add_argument("--subject", default=None)
    parser.add_argument("--xlsx", default=None, help="附件 xlsx 路徑")
    parser.add_argument("--html-body", default=None, dest="html_body", help="HTML body 檔案路徑")
    parser.add_argument("--html-inline", default=None, dest="html_inline", help="HTML body 字串")
    parser.add_argument("--apply", action="store_true", help="真的 create draft")
    parser.add_argument("--delete", action="append", default=[], metavar="DRAFT_ID")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    service = build_service()

    if args.list:
        list_drafts(service)
        return

    for did in args.delete:
        ok = delete_draft(service, did)
        print(f"[{'OK' if ok else 'FAIL'}] deleted {did}")

    if not any([args.subject, args.xlsx, args.html_body, args.html_inline]):
        if args.delete:
            return
        parser.print_help()
        return

    subject = args.subject or f"【小膳週報 {args.week}】週報附件"
    if args.html_body:
        html_body = open(args.html_body, encoding="utf-8").read()
    elif args.html_inline:
        html_body = args.html_inline
    else:
        html_body = f"<p>週報 {args.week} 附件請參閱。</p>"

    to_list = [r.strip() for r in args.recipients.split(",") if r.strip()]
    cc_list  = [r.strip() for r in args.cc.split(",") if r.strip()] if args.cc else []

    mime_msg = build_mime(subject, to_list, cc_list, html_body, args.xlsx)
    size_kb = len(mime_msg.as_bytes()) / 1024
    print(f"MIME size: {size_kb:.1f} KB | To: {', '.join(to_list)} | Cc: {', '.join(cc_list)}")
    print(f"Subject: {subject}")
    print(f"Attachment: {args.xlsx or '(none)'}")

    if args.apply:
        result = create_draft(service, mime_msg)
        print(f"[OK] Draft created: id={result['id']}  message_id={result['message']['id']}")
    else:
        print("[DRY-RUN] Pass --apply to create the draft.")

if __name__ == "__main__":
    main()
