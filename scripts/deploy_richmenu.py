"""部署 Rich Menu 到 LINE — 一鍵 create + upload + set_default"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", ".env"))

from services.richmenu_service import RichMenuService


def main():
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        print("ERROR: LINE_CHANNEL_ACCESS_TOKEN not set")
        return

    svc = RichMenuService(token=token)

    # 先列出現有 menus
    existing = svc.list_menus()
    print(f"Existing rich menus: {len(existing)}")
    for m in existing:
        print(f"  - {m.get('richMenuId')}: {m.get('name', 'unnamed')}")

    # 查看當前 default
    current_default = svc.get_default_id()
    print(f"Current default: {current_default}")

    # 部署
    image_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                              "assets", "richmenu.png")
    if not os.path.exists(image_path):
        print(f"ERROR: Image not found: {image_path}")
        return

    print(f"\nDeploying rich menu with image: {image_path}")
    menu_id = svc.deploy(image_path=image_path)

    if menu_id:
        print(f"\n✅ Rich Menu deployed successfully!")
        print(f"   Menu ID: {menu_id}")
        print(f"   Image: {image_path}")
        print(f"   Set as default: yes")
    else:
        print("\n❌ Deploy failed. Check logs above.")


if __name__ == "__main__":
    main()
