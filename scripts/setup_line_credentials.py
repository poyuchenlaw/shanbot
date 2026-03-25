#!/usr/bin/env python3
"""LINE 憑證設定工具 — 小魚取得 LINE Developers 憑證後執行此腳本"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import state_manager as sm

COMPANIES = {
    1: "福利社",
    2: "王凱",
    3: "台達2廠",
    4: "富燚",
    5: "台達1廠",
}


def setup_interactive():
    """互動式設定每家公司的 LINE 憑證"""
    sm.init_db()
    print("=" * 50)
    print("小膳 Bot — LINE 多租戶憑證設定")
    print("=" * 50)
    print()

    companies = sm.get_all_companies()
    for company in companies:
        cid = company["id"]
        name = company["short_name"]
        existing = company.get("line_channel_id", "")

        if existing:
            print(f"[{cid}] {name}: 已設定 (Channel ID: {existing[:8]}...)")
            skip = input("    要重新設定嗎？(y/N): ").strip().lower()
            if skip != "y":
                continue
        else:
            print(f"[{cid}] {name}: 尚未設定")

        print(f"\n  請輸入 {name} 的 LINE 憑證：")
        channel_id = input("    Channel ID: ").strip()
        channel_secret = input("    Channel Secret: ").strip()
        access_token = input("    Channel Access Token: ").strip()

        if channel_id and channel_secret and access_token:
            sm.update_company_line_credentials(cid, channel_id, channel_secret, access_token)
            print(f"    ✅ {name} 憑證已儲存")
        else:
            print(f"    ⏭️ 跳過 {name}（資料不完整）")
        print()

    # 同步更新 companies.json
    _sync_to_config()

    print("\n設定完成！請重啟 shanbot：")
    print("  pm2 restart shanbot")
    print("\n或呼叫 API 重新載入：")
    print("  curl -X POST http://localhost:8025/reload-companies")


def setup_from_json(json_path: str):
    """從 JSON 檔案批次設定"""
    sm.init_db()
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for c in data.get("companies", []):
        cid = c.get("id")
        channel_id = c.get("line_channel_id", "")
        channel_secret = c.get("line_channel_secret", "")
        access_token = c.get("line_channel_access_token", "")

        if cid and channel_id and channel_secret and access_token:
            sm.update_company_line_credentials(cid, channel_id, channel_secret, access_token)
            print(f"✅ {COMPANIES.get(cid, f'Company {cid}')} 憑證已設定")
        else:
            print(f"⏭️ {COMPANIES.get(cid, f'Company {cid}')} 跳過（資料不完整）")

    print("\n完成！請重啟 shanbot 或呼叫 /reload-companies")


def _sync_to_config():
    """將資料庫中的憑證同步到 companies.json"""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                               "config", "companies.json")
    companies = sm.get_all_companies()

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    for c in config.get("companies", []):
        db_company = next((x for x in companies if x["id"] == c["id"]), None)
        if db_company:
            c["line_channel_id"] = db_company.get("line_channel_id", "")
            c["line_channel_secret"] = db_company.get("line_channel_secret", "")
            c["line_channel_access_token"] = db_company.get("line_channel_access_token", "")

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print("📄 config/companies.json 已同步")


def show_status():
    """顯示憑證設定狀態"""
    sm.init_db()
    companies = sm.get_all_companies()
    print("\n公司 LINE 憑證狀態：")
    print("-" * 60)
    for c in companies:
        has_cred = bool(c.get("line_channel_id"))
        status = "✅ 已設定" if has_cred else "❌ 未設定"
        channel_hint = f" (ID: {c['line_channel_id'][:8]}...)" if has_cred else ""
        print(f"  {c['id']}. {c['short_name']:8s} {status}{channel_hint}")
    print()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "status":
            show_status()
        elif sys.argv[1] == "json" and len(sys.argv) > 2:
            setup_from_json(sys.argv[2])
        else:
            print("用法:")
            print("  python setup_line_credentials.py          # 互動式設定")
            print("  python setup_line_credentials.py status   # 查看狀態")
            print("  python setup_line_credentials.py json config/companies.json  # 從 JSON 匯入")
    else:
        setup_interactive()
