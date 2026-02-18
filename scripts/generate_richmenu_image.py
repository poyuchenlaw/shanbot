"""生成 Rich Menu 圖片 — 2500×1686 六宮格（含浮水印圖示）"""

from PIL import Image, ImageDraw, ImageFont
import os

# 尺寸
W, H = 2500, 1686
CELL_W = W // 3          # 833
CELL_H = H // 2          # 843

# 顏色
BG = "#FFFFFF"
BORDER = "#E0E0E0"
GREEN = "#06C755"       # LINE 綠
BROWN = "#8B5E3C"       # 暖棕
WARM = "#FFF8F0"        # 暖底

# 六格定義（圖示用文字替代 emoji）
CELLS = [
    {"icon": "[ 拍 ]", "title": "拍照記帳",   "sub": "上傳收據辨識",  "bg": GREEN},
    {"icon": "[ 資 ]", "title": "財務資料",   "sub": "上傳/分類/確認", "bg": BROWN},
    {"icon": "[ 購 ]", "title": "採購管理",   "sub": "確認/修改/比價", "bg": GREEN},
    {"icon": "[ 菜 ]", "title": "菜單企劃",   "sub": "AI 菜單/成本",  "bg": BROWN},
    {"icon": "[ 表 ]", "title": "報表生成",   "sub": "四大報表/匯出", "bg": GREEN},
    {"icon": "[ 用 ]", "title": "使用說明",   "sub": "功能教學",      "bg": BROWN},
]


def find_font(size):
    """找到系統 CJK 字型"""
    candidates = [
        os.path.expanduser("~/.local/share/fonts/NotoSansCJKtc-Regular.otf"),
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()


def _draw_watermark_camera(draw, cx, cy, size, fill):
    """相機圖示 — 拍照記帳"""
    s = size
    # 機身
    draw.rounded_rectangle(
        [cx - s, cy - s * 0.6, cx + s, cy + s * 0.7],
        radius=s * 0.15, outline=fill, width=max(3, s // 12)
    )
    # 鏡頭圓
    r = s * 0.35
    draw.ellipse([cx - r, cy - r + s * 0.05, cx + r, cy + r + s * 0.05],
                 outline=fill, width=max(3, s // 12))
    # 觀景窗
    draw.rectangle(
        [cx - s * 0.3, cy - s * 0.6 - s * 0.25, cx + s * 0.3, cy - s * 0.6],
        outline=fill, width=max(2, s // 15)
    )


def _draw_watermark_coins(draw, cx, cy, size, fill):
    """錢幣圖示 — 財務總覽"""
    s = size
    w = max(3, s // 12)
    # 後方硬幣
    draw.ellipse([cx - s * 0.2, cy - s * 0.7, cx + s * 1.0, cy + s * 0.5],
                 outline=fill, width=w)
    # 前方硬幣
    draw.ellipse([cx - s * 0.9, cy - s * 0.4, cx + s * 0.3, cy + s * 0.8],
                 outline=fill, width=w)
    # $ 符號
    font_s = find_font(int(s * 0.7))
    bbox = draw.textbbox((0, 0), "$", font=font_s)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((cx - s * 0.3 - tw // 2, cy + s * 0.2 - th // 2 - 5),
              "$", fill=fill, font=font_s)


def _draw_watermark_cart(draw, cx, cy, size, fill):
    """購物車圖示 — 採購管理"""
    s = size
    w = max(3, s // 12)
    # 車身
    pts = [
        (cx - s * 0.8, cy - s * 0.6),
        (cx - s * 0.5, cy - s * 0.6),
        (cx - s * 0.3, cy + s * 0.3),
        (cx + s * 0.8, cy + s * 0.3),
        (cx + s * 0.9, cy - s * 0.4),
        (cx - s * 0.35, cy - s * 0.4),
    ]
    draw.line(pts, fill=fill, width=w)
    # 輪子
    wr = s * 0.12
    draw.ellipse([cx - s * 0.15 - wr, cy + s * 0.45 - wr,
                  cx - s * 0.15 + wr, cy + s * 0.45 + wr],
                 outline=fill, width=w)
    draw.ellipse([cx + s * 0.55 - wr, cy + s * 0.45 - wr,
                  cx + s * 0.55 + wr, cy + s * 0.45 + wr],
                 outline=fill, width=w)


def _draw_watermark_utensils(draw, cx, cy, size, fill):
    """刀叉圖示 — 菜單企劃"""
    s = size
    w = max(3, s // 12)
    # 叉子（左）
    draw.line([(cx - s * 0.4, cy - s * 0.8), (cx - s * 0.4, cy + s * 0.8)],
              fill=fill, width=w)
    # 叉齒
    for dx in [-0.15, 0, 0.15]:
        draw.line([(cx - s * 0.4 + s * dx, cy - s * 0.8),
                   (cx - s * 0.4 + s * dx, cy - s * 0.3)],
                  fill=fill, width=max(2, w - 1))
    # 刀（右）
    draw.line([(cx + s * 0.4, cy - s * 0.8), (cx + s * 0.4, cy + s * 0.8)],
              fill=fill, width=w)
    # 刀刃弧線
    draw.arc([cx + s * 0.15, cy - s * 0.8, cx + s * 0.65, cy - s * 0.1],
             start=-30, end=90, fill=fill, width=w)


def _draw_watermark_chart(draw, cx, cy, size, fill):
    """長條圖圖示 — 匯出報表"""
    s = size
    w = max(3, s // 10)
    bar_w = s * 0.25
    gap = s * 0.1
    # 三根長條
    heights = [s * 0.6, s * 1.0, s * 0.8]
    base_y = cy + s * 0.5
    start_x = cx - (3 * bar_w + 2 * gap) / 2
    for i, h in enumerate(heights):
        x0 = start_x + i * (bar_w + gap)
        draw.rectangle([x0, base_y - h, x0 + bar_w, base_y],
                       outline=fill, width=w)
    # 底線
    draw.line([(start_x - gap, base_y), (start_x + 3 * bar_w + 2 * gap + gap, base_y)],
              fill=fill, width=w)


def _draw_watermark_book(draw, cx, cy, size, fill):
    """書本圖示 — 使用說明"""
    s = size
    w = max(3, s // 12)
    # 書本外框
    draw.rounded_rectangle(
        [cx - s * 0.8, cy - s * 0.7, cx + s * 0.8, cy + s * 0.7],
        radius=s * 0.1, outline=fill, width=w
    )
    # 書脊（中線）
    draw.line([(cx, cy - s * 0.7), (cx, cy + s * 0.7)],
              fill=fill, width=w)
    # 頁面線條（左）
    for dy in [-0.3, 0, 0.3]:
        draw.line([(cx - s * 0.6, cy + s * dy), (cx - s * 0.15, cy + s * dy)],
                  fill=fill, width=max(2, w - 1))
    # 頁面線條（右）
    for dy in [-0.3, 0, 0.3]:
        draw.line([(cx + s * 0.15, cy + s * dy), (cx + s * 0.6, cy + s * dy)],
                  fill=fill, width=max(2, w - 1))


# 浮水印繪製器（對應六格順序）
WATERMARK_DRAWERS = [
    _draw_watermark_camera,
    _draw_watermark_coins,
    _draw_watermark_cart,
    _draw_watermark_utensils,
    _draw_watermark_chart,
    _draw_watermark_book,
]


def generate():
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    font_title = find_font(80)
    font_sub = find_font(44)
    font_icon = find_font(100)

    for idx, cell in enumerate(CELLS):
        col = idx % 3
        row = idx // 3
        x0 = col * CELL_W
        y0 = row * CELL_H
        x1 = x0 + CELL_W
        y1 = y0 + CELL_H

        # 背景色（淺色漸層感）
        bg_color = cell["bg"]
        # 用較淺的底色
        light_bg = "#E8F5E9" if bg_color == GREEN else "#FFF3E0"
        draw.rectangle([x0, y0, x1, y1], fill=light_bg)

        # 頂部色條
        bar_h = 12
        draw.rectangle([x0, y0, x1, y0 + bar_h], fill=bg_color)

        # 圖標圓形背景 + 文字
        icon_text = cell["icon"]
        # 畫圓形背景
        circle_r = 90
        cx = x0 + CELL_W // 2
        cy = y0 + 230
        draw.ellipse([cx - circle_r, cy - circle_r, cx + circle_r, cy + circle_r],
                     fill=bg_color)
        # 圓心文字
        icon_char = icon_text[2]  # 取中間的字
        try:
            ib = draw.textbbox((0, 0), icon_char, font=font_icon)
            iw = ib[2] - ib[0]
            ih = ib[3] - ib[1]
        except Exception:
            iw, ih = 100, 100
        draw.text((cx - iw // 2, cy - ih // 2 - 10), icon_char,
                  fill="#FFFFFF", font=font_icon)

        # 標題
        title_text = cell["title"]
        try:
            title_bbox = draw.textbbox((0, 0), title_text, font=font_title)
            tw = title_bbox[2] - title_bbox[0]
        except Exception:
            tw = len(title_text) * 80
        tx = x0 + (CELL_W - tw) // 2
        ty = cy + circle_r + 60
        draw.text((tx, ty), title_text, fill=bg_color, font=font_title)

        # 副標題
        sub_text = cell["sub"]
        try:
            sub_bbox = draw.textbbox((0, 0), sub_text, font=font_sub)
            sw = sub_bbox[2] - sub_bbox[0]
        except Exception:
            sw = len(sub_text) * 42
        sx = x0 + (CELL_W - sw) // 2
        sy = ty + 100
        draw.text((sx, sy), sub_text, fill="#666666", font=font_sub)

        # 邊框
        draw.rectangle([x0, y0, x1, y1], outline=BORDER, width=3)

        # === 浮水印圖示（右下角，半透明感） ===
        wm_size = 60  # 圖示基本尺寸
        wm_cx = x1 - 100  # 右下角偏移
        wm_cy = y1 - 90
        # 半透明色（較淡的主色調）
        if bg_color == GREEN:
            wm_fill = "#A5D6A7"  # 淡綠
        else:
            wm_fill = "#D7CCC8"  # 淡棕
        WATERMARK_DRAWERS[idx](draw, wm_cx, wm_cy, wm_size, wm_fill)

    # 儲存
    out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           "assets")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "richmenu.png")
    img.save(out_path, "PNG")
    print(f"Generated: {out_path}")
    print(f"Size: {os.path.getsize(out_path)} bytes")
    return out_path


if __name__ == "__main__":
    generate()
