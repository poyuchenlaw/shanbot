"""菜單企劃 — 處理菜單編輯、菜色圖片生成、成本試算的對話狀態"""

import logging
import os

import state_manager as sm

logger = logging.getLogger("shanbot.menu_handler")


async def handle_menu_photo(line_service, message_id: str, group_id: str,
                            user_id: str, reply_token: str) -> str | None:
    """處理菜色照片上傳 — 三段式：分析 → 增強圖 → 行銷文案"""
    from datetime import datetime

    # 0. 下載照片
    image_bytes = line_service.get_content(message_id)
    if not image_bytes:
        return "❌ 圖片下載失敗，請重新上傳"

    # 回覆「處理中」提示
    if reply_token:
        line_service.reply(reply_token,
                           "📸 收到菜色照片！正在 AI 分析中...\n"
                           "（分析 → 增強 → 文案，約需 15-30 秒）")

    # 1. Stage 1: Gemini Vision 分析
    analysis = {}
    try:
        from services.menu_ai_service import analyze_dish_photo
        analysis = analyze_dish_photo(image_bytes)
        logger.info(f"Dish analysis: {analysis.get('dish_name', 'unknown')}")
    except Exception as e:
        logger.error(f"Dish analysis error: {e}")
        analysis = {"dish_name": "菜色", "ingredients": [], "style": ""}

    # 2. 儲存原圖
    IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "images")
    os.makedirs(IMAGES_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = analysis.get("dish_name", "dish").replace(" ", "_").replace("/", "_")[:20]
    orig_filename = f"menu_orig_{safe_name}_{ts}.jpg"
    orig_path = os.path.join(IMAGES_DIR, orig_filename)
    with open(orig_path, "wb") as f:
        f.write(image_bytes)

    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")
    original_url = f"{PUBLIC_BASE_URL.rstrip('/')}/images/{orig_filename}" if PUBLIC_BASE_URL else ""

    # 3. Stage 2: 生成增強圖
    enhanced_url = ""
    try:
        from services.menu_ai_service import generate_enhanced_dish_prompt, _call_imagen_api
        prompt = generate_enhanced_dish_prompt(analysis)
        img_bytes = _call_imagen_api(prompt)
        if img_bytes:
            enh_filename = f"menu_enh_{safe_name}_{ts}.png"
            enh_path = os.path.join(IMAGES_DIR, enh_filename)
            with open(enh_path, "wb") as f:
                f.write(img_bytes)
            enhanced_url = f"{PUBLIC_BASE_URL.rstrip('/')}/images/{enh_filename}" if PUBLIC_BASE_URL else ""
            logger.info(f"Enhanced image saved: {enh_path}")
    except Exception as e:
        logger.error(f"Enhanced image error: {e}")

    # 4. Stage 3: 行銷文案
    copy = {}
    try:
        from services.menu_ai_service import generate_marketing_copy
        copy = generate_marketing_copy(analysis)
    except Exception as e:
        logger.error(f"Marketing copy error: {e}")
        copy = {"tagline": analysis.get("dish_name", ""), "copy": "", "hashtags": []}

    # 5. GDrive 同步
    try:
        from services.gdrive_service import init_folder_structure, _year_month_path
        import shutil
        ym = datetime.now().strftime("%Y-%m")
        init_folder_structure(ym)
        _, month_path = _year_month_path(ym)
        dest_dir = os.path.join(month_path, "菜單企劃")
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(orig_path, os.path.join(dest_dir, orig_filename))
        if enhanced_url:
            enh_path_local = os.path.join(IMAGES_DIR, f"menu_enh_{safe_name}_{ts}.png")
            if os.path.exists(enh_path_local):
                shutil.copy2(enh_path_local, os.path.join(dest_dir, f"menu_enh_{safe_name}_{ts}.png"))
    except Exception as e:
        logger.warning(f"GDrive sync skipped: {e}")

    # 6. 組裝 Flex 回覆
    try:
        from services.flex_builder import build_menu_marketing_flex
        flex = build_menu_marketing_flex(
            original_url=original_url,
            enhanced_url=enhanced_url,
            analysis=analysis,
            copy=copy,
        )
        if line_service:
            line_service.push_flex(
                group_id,
                f"📸 {analysis.get('dish_name', '菜色')} — 行銷海報",
                flex,
            )
            # 額外推送可儲存的增強圖
            if enhanced_url:
                line_service.push_image(group_id, enhanced_url)
            elif original_url:
                line_service.push_image(group_id, original_url)
        return None  # 已自行推送
    except Exception as e:
        logger.warning(f"Marketing flex build failed: {e}")

    # Fallback 文字
    lines = [f"📸 {analysis.get('dish_name', '菜色')} — 行銷海報", ""]
    if copy.get("tagline"):
        lines.append(f"💬 {copy['tagline']}")
    if copy.get("copy"):
        lines.append(f"\n{copy['copy']}")
    if copy.get("hashtags"):
        lines.append(f"\n{' '.join(copy['hashtags'][:6])}")
    if enhanced_url:
        lines.append(f"\n🖼️ 增強圖：{enhanced_url}")
    if line_service:
        line_service.push(group_id, "\n".join(lines))
    return None


async def handle_menu_edit(line_service, text: str, group_id: str, state_data: dict) -> str:
    """處理菜單編輯模式的回應"""
    if text.strip() in ("完成菜單", "完成", "結束"):
        sm.clear_state(group_id)
        return "✅ 菜單編輯完成！\n點選「查看菜單」確認結果。"

    # 解析菜單輸入：週一午：紅燒肉、炒青菜、蛋花湯
    import re
    match = re.match(r"(週[一二三四五六日])(午|晚)?[：:](.+)", text.strip())
    if not match:
        return ("格式不正確。請使用：\n"
                "  週一午：紅燒肉、炒青菜、蛋花湯\n"
                "或輸入「完成菜單」結束")

    day_name = match.group(1)
    meal = match.group(2) or "午"
    dishes_str = match.group(3)
    dishes = [d.strip() for d in re.split(r"[、,，]", dishes_str) if d.strip()]

    day_map = {"週一": "1", "週二": "2", "週三": "3", "週四": "4",
               "週五": "5", "週六": "6", "週日": "7"}
    day_num = day_map.get(day_name, "1")
    meal_type = "lunch" if meal == "午" else "dinner"

    # 計算實際日期（本週）
    from datetime import datetime, timedelta
    now = datetime.now()
    current_weekday = now.isoweekday()
    target_weekday = int(day_num)
    diff = target_weekday - current_weekday
    target_date = (now + timedelta(days=diff)).strftime("%Y-%m-%d")

    # 寫入排程
    for i, dish in enumerate(dishes):
        slot = f"slot_{i+1}"
        # 嘗試匹配已知配方
        recipe = _find_recipe(dish)
        recipe_id = recipe["id"] if recipe else None
        sm.add_menu_schedule(target_date, slot, recipe_id=recipe_id,
                            meal_type=meal_type)

    return (f"✅ {day_name}{meal}餐已更新：\n"
            f"  {' / '.join(dishes)}\n"
            f"日期：{target_date}\n\n"
            "繼續輸入其他天的菜單，或「完成菜單」結束")


async def handle_dish_name(line_service, text: str, group_id: str,
                           state_data: dict, reply_token: str = "") -> str | None:
    """處理菜色圖片生成 — 接收菜名，生成描述 + Imagen 3 圖片"""
    dish_name = text.strip()
    if not dish_name or len(dish_name) > 20:
        return "請輸入有效的菜名（1-20 字）"

    sm.clear_state(group_id)

    # 先回覆「生成中」提示（因為圖片生成需要時間）
    if line_service and reply_token:
        line_service.reply(reply_token, f"🎨 正在為「{dish_name}」生成菜色圖片，請稍候...")

    # 1. 生成文字描述
    desc_result = {}
    try:
        from services.menu_ai_service import generate_dish_description
        desc_result = generate_dish_description(dish_name)
    except Exception as e:
        logger.error(f"Dish description error: {e}")

    desc = desc_result.get("description", "")
    marketing = desc_result.get("marketing_copy", "")
    ingredients = desc_result.get("ingredients", [])
    method = desc_result.get("cooking_method", "")

    # 2. 生成圖片
    image_url = ""
    gdrive_note = ""
    try:
        from services.menu_ai_service import generate_dish_image
        img_result = generate_dish_image(dish_name)
        if img_result.get("success"):
            image_url = img_result.get("image_url", "")
            local_path = img_result.get("local_path", "")
            if local_path:
                gdrive_note = "☁️ 圖片已存到 GDrive 菜單企劃資料夾"
            logger.info(f"Dish image OK: {dish_name} → {image_url or local_path}")
        else:
            logger.warning(f"Dish image failed: {img_result.get('error')}")
    except Exception as e:
        logger.error(f"Dish image error: {e}")

    # 3. 建構 Flex Message（含圖片 hero）+ 推送
    try:
        from services.flex_builder import build_menu_dish_flex
        flex = build_menu_dish_flex(
            dish_name=dish_name,
            ingredients=ingredients,
            total_cost=0,
            description=desc,
            image_url=image_url,
        )

        # 加入行銷文案和烹調方式
        extra = []
        if marketing:
            extra.append({"type": "text", "text": f"💬 {marketing}",
                          "size": "sm", "color": "#555555", "wrap": True, "margin": "md"})
        if method:
            extra.append({"type": "text", "text": f"👨‍🍳 {method}",
                          "size": "xs", "color": "#888888", "wrap": True})
        if gdrive_note:
            extra.append({"type": "text", "text": gdrive_note,
                          "size": "xxs", "color": "#AAAAAA", "wrap": True, "margin": "md"})
        if extra:
            flex["body"]["contents"].extend(extra)

        # reply_token 已用於「生成中」提示，改用 push 發送結果
        if line_service:
            line_service.push_flex(group_id, f"🎨 {dish_name} — 菜色圖片", flex)

            # 如有圖片 URL，額外推送可儲存的圖片
            if image_url:
                line_service.push_image(group_id, image_url)

        return None  # 已自行推送，不需上層回覆

    except Exception as e:
        logger.warning(f"Flex build failed, falling back to text push: {e}")

    # 4. Fallback 純文字推送
    lines = [f"🎨 {dish_name}", ""]
    if desc:
        lines.append(f"📝 {desc}")
    if marketing:
        lines.append(f"💬 {marketing}")
    if method:
        lines.append(f"👨‍🍳 {method}")
    if ingredients:
        lines.append(f"\n🥬 主要食材：{', '.join(ingredients[:8])}")
    if image_url:
        lines.append(f"\n🖼️ 圖片：{image_url}")
    elif gdrive_note:
        lines.append(f"\n{gdrive_note}")

    if line_service:
        line_service.push(group_id, "\n".join(lines))

    return None


async def handle_cost_input(line_service, text: str, group_id: str, state_data: dict) -> str:
    """處理成本試算 — 接收菜名或食材清單"""
    sm.clear_state(group_id)
    dish_name = text.strip()

    if not dish_name:
        return "請輸入菜名或食材清單"

    # 先查 DB 是否有已知配方
    recipe = _find_recipe(dish_name)
    if recipe:
        bom = sm.get_recipe_bom(recipe["id"])
        if bom:
            from services.menu_ai_service import estimate_dish_cost
            result = estimate_dish_cost(dish_name, bom)
            return _format_cost_result(result)

    # 用 AI 估算
    try:
        from services.menu_ai_service import estimate_dish_cost
        result = estimate_dish_cost(dish_name)
        return _format_cost_result(result)
    except Exception as e:
        logger.error(f"Cost calc error: {e}")
        return f"🧮 {dish_name}\n\n成本試算暫時無法使用，請稍後再試。"


def _format_cost_result(result: dict) -> str:
    """格式化成本試算結果"""
    name = result.get("dish_name", "")
    total = result.get("total_cost", 0)
    items = result.get("items", [])
    source = result.get("source", "")
    notes = result.get("notes", "")

    lines = [f"🧮 {name} — 食材成本試算", ""]

    if items:
        lines.append("食材明細：")
        for item in items[:10]:
            n = item.get("name", "")
            q = item.get("quantity", 0)
            u = item.get("unit", "")
            up = item.get("unit_price", 0)
            c = item.get("cost", 0)
            lines.append(f"  • {n} {q}{u} @${up:.0f} = ${c:.0f}")
        lines.append("")

    lines.append(f"💵 總成本：${total:,.0f}")

    if source == "ai_estimate":
        lines.append("📌 此為 AI 估算，實際成本以進貨價為準")
    elif source == "database":
        lines.append("📌 依據系統記錄的最新進貨價計算")

    if notes:
        lines.append(f"\n💡 {notes}")

    return "\n".join(lines)


def _find_recipe(name: str) -> dict | None:
    """模糊匹配配方"""
    recipes = sm.get_all_recipes()
    for r in recipes:
        if r["name"] == name or name in r["name"]:
            return r
    return None


# === 菜單 Excel 模板 + 匯入（Batch 2 新增）===

async def handle_menu_template(line_service, group_id: str) -> str | None:
    """建立菜單 Excel 模板 — 由 command_handler 路由呼叫"""
    from datetime import datetime
    try:
        from services.salary_service import generate_menu_template
        ym = datetime.now().strftime("%Y-%m")
        filepath = generate_menu_template(ym)
        return (
            f"✅ 菜單排程表已建立\n"
            f"📅 月份：{ym}\n"
            f"📁 路徑：{filepath}\n\n"
            f"請到 Google Drive 開啟 Excel 填寫菜單\n"
            f"填完後回覆「菜單完成」匯入系統"
        )
    except Exception as e:
        logger.error(f"Menu template error: {e}", exc_info=True)
        return f"建立菜單表格失敗：{str(e)}"


async def handle_menu_import(line_service, group_id: str) -> str | None:
    """匯入已填寫的菜單 — 由 command_handler 路由呼叫"""
    from datetime import datetime
    try:
        from services.salary_service import parse_menu_excel
        from services.gdrive_service import GDRIVE_LOCAL

        ym = datetime.now().strftime("%Y-%m")
        parts = ym.split("-")
        year = parts[0]
        month = f"{int(parts[1]):02d}月"
        filepath = os.path.join(GDRIVE_LOCAL, year, month, "菜單企劃", f"菜單_{ym}.xlsx")

        if not os.path.exists(filepath):
            return (
                f"找不到菜單檔案\n"
                f"預期路徑：{filepath}\n\n"
                f"請先輸入「菜單表格」建立模板，填寫後再回覆「菜單完成」"
            )

        records = parse_menu_excel(filepath)
        if not records:
            return "菜單表格是空的，請先填寫菜色後再匯入"

        # Import to DB
        imported = 0
        for rec in records:
            try:
                sm.add_menu_schedule(
                    schedule_date=rec["date"],
                    slot=rec["slot"],
                    meal_type=rec["meal_type"],
                )
                imported += 1
            except Exception as e:
                logger.warning(f"Menu import row error: {e}")

        dates = sorted(set(r["date"] for r in records))
        lunch_count = sum(1 for r in records if r["meal_type"] == "lunch")
        dinner_count = sum(1 for r in records if r["meal_type"] == "dinner")

        return (
            f"✅ 菜單匯入完成 — {ym}\n"
            f"📅 涵蓋 {len(dates)} 天\n"
            f"🍱 午餐菜色 {lunch_count} 道\n"
            f"🍽️ 晚餐菜色 {dinner_count} 道\n"
            f"📊 共 {len(records)} 筆記錄"
        )
    except Exception as e:
        logger.error(f"Menu import error: {e}", exc_info=True)
        return f"匯入菜單失敗：{str(e)}"
