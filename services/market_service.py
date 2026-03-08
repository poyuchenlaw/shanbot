"""小膳 Bot - 農產品市場行情服務

串接農委會開放資料 API，取得蔬菜、水果、豬肉、禽蛋即時批發價格。
提供價格比對與異常偵測功能，協助採購成本管控。

資料來源：
- 蔬果：農產品交易行情（FarmTransData）
- 豬肉：毛豬交易行情（PorkTransType）
- 禽蛋：白肉雞及雞蛋交易行情（PoultryTransType_BoiledChicken_Eggs）
"""

import logging
import math
import statistics
from datetime import date, datetime, timedelta
from typing import Optional

import requests

import state_manager as sm

logger = logging.getLogger("shanbot.market")

# === API 端點 ===
FARM_TRANS_URL = "https://data.moa.gov.tw/Service/OpenData/FromM/FarmTransData.aspx"
PORK_TRANS_URL = "https://data.moa.gov.tw/api/v1/PorkTransType/"
POULTRY_TRANS_URL = "https://data.moa.gov.tw/api/v1/PoultryTransType_BoiledChicken_Eggs/"

# === 種類代碼 ===
CATEGORY_VEGETABLE = "N04"  # 蔬菜
CATEGORY_FRUIT = "N05"      # 水果

# === 快取有效天數 ===
CACHE_DAYS = 7

# === HTTP 請求逾時（秒）===
REQUEST_TIMEOUT = 30

# === 價格比對門檻 ===
FIXED_THRESHOLD_PCT = 30      # 資料不足時的固定門檻（±30%）
MIN_DATA_POINTS = 30          # 切換至 Z-score 的最低資料筆數
ZSCORE_THRESHOLD = 2.5        # Z-score 異常門檻

# === 偏差等級門檻 ===
NORMAL_THRESHOLD_PCT = 10     # < 10% 正常
SLIGHT_HIGH_THRESHOLD_PCT = 20  # 10-20% 偏高


# ============================================================
#  日期格式轉換
# ============================================================

def to_roc_date(d: date = None) -> str:
    """西元日期轉民國日期（含點號），例：2026-02-18 → 115.02.18

    Args:
        d: 日期物件，預設為今天

    Returns:
        民國日期字串，格式 YYY.MM.DD
    """
    if d is None:
        d = date.today()
    roc_year = d.year - 1911
    return f"{roc_year}.{d.month:02d}.{d.day:02d}"


def to_roc_date_no_dot(d: date = None) -> str:
    """西元日期轉民國日期（無點號），例：2026-02-18 → 1150218

    Args:
        d: 日期物件，預設為今天

    Returns:
        民國日期字串，格式 YYYMMDD（無分隔符）
    """
    if d is None:
        d = date.today()
    roc_year = d.year - 1911
    return f"{roc_year}{d.month:02d}{d.day:02d}"


# ============================================================
#  API 資料擷取
# ============================================================

def fetch_vegetables(target_date: date = None) -> list[dict]:
    """取得蔬菜批發交易行情

    Args:
        target_date: 查詢日期，預設為今天

    Returns:
        蔬菜行情列表，每筆含 作物名稱、市場名稱、上價、中價、下價、平均價、交易量
        API 失敗時回傳空列表
    """
    return _fetch_farm_trans(CATEGORY_VEGETABLE, target_date)


def fetch_fruits(target_date: date = None) -> list[dict]:
    """取得水果批發交易行情

    Args:
        target_date: 查詢日期，預設為今天

    Returns:
        水果行情列表，格式同蔬菜
        API 失敗時回傳空列表
    """
    return _fetch_farm_trans(CATEGORY_FRUIT, target_date)


def _fetch_farm_trans(category_code: str, target_date: date = None) -> list[dict]:
    """從 FarmTransData API 取得農產品交易行情（蔬菜/水果通用）

    API 回傳裸 JSON 陣列，欄位為中文：
    種類代碼, 作物代號, 作物名稱, 市場代號, 市場名稱, 上價, 中價, 下價, 平均價, 交易量

    Args:
        category_code: 種類代碼（N04=蔬菜, N05=水果）
        target_date: 查詢日期

    Returns:
        符合種類代碼的交易資料列表
    """
    if target_date is None:
        target_date = date.today()

    roc_date = to_roc_date(target_date)

    try:
        resp = requests.get(
            FARM_TRANS_URL,
            params={
                "$top": "9999",
                "StartDate": roc_date,
                "EndDate": roc_date,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f"FarmTransData API 請求失敗 (種類={category_code}): {e}")
        return []
    except ValueError as e:
        logger.error(f"FarmTransData API 回應解析失敗: {e}")
        return []

    # 篩選指定種類
    filtered = [
        item for item in data
        if item.get("種類代碼", "").strip() == category_code
    ]

    logger.info(
        f"FarmTransData 取得 {len(filtered)} 筆資料 "
        f"(種類={category_code}, 日期={roc_date}, 原始={len(data)}筆)"
    )
    return filtered


def fetch_pork(target_date: date = None) -> list[dict]:
    """取得豬肉批發交易行情

    API 回傳包裝格式：{"RS": "OK", "Data": [...]}
    Data 內欄位為英文：TransDate, TypeName, AvgPrice, MaxPrice, MinPrice, ...

    Args:
        target_date: 查詢日期，預設為今天

    Returns:
        豬肉交易資料列表
        API 失敗時回傳空列表
    """
    if target_date is None:
        target_date = date.today()

    roc_no_dot = to_roc_date_no_dot(target_date)

    try:
        resp = requests.get(
            PORK_TRANS_URL,
            params={"TransDate": roc_no_dot},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.RequestException as e:
        logger.error(f"PorkTransType API 請求失敗: {e}")
        return []
    except ValueError as e:
        logger.error(f"PorkTransType API 回應解析失敗: {e}")
        return []

    # 解析包裝格式
    if isinstance(result, dict):
        if result.get("RS") != "OK":
            logger.warning(f"PorkTransType API 回傳非 OK 狀態: RS={result.get('RS')}")
            return []
        data = result.get("Data", [])
    elif isinstance(result, list):
        # 容錯：若 API 變更為裸陣列
        data = result
    else:
        logger.warning(f"PorkTransType API 回傳未預期格式: {type(result)}")
        return []

    logger.info(f"PorkTransType 取得 {len(data)} 筆資料 (日期={roc_no_dot})")
    return data


def fetch_poultry_eggs() -> list[dict]:
    """取得禽蛋（白肉雞、雞蛋）交易行情

    API 回傳裸 JSON 陣列，主要欄位：
    日期, 白肉雞(2.0Kg以上), 雞蛋(產地價), ...

    Returns:
        禽蛋交易資料列表（最近 30 筆）
        API 失敗時回傳空列表
    """
    try:
        resp = requests.get(
            POULTRY_TRANS_URL,
            params={"$top": "30"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f"PoultryTransType API 請求失敗: {e}")
        return []
    except ValueError as e:
        logger.error(f"PoultryTransType API 回應解析失敗: {e}")
        return []

    if not isinstance(data, list):
        logger.warning(f"PoultryTransType API 回傳非陣列格式: {type(data)}")
        return []

    logger.info(f"PoultryTransType 取得 {len(data)} 筆資料")
    return data


# ============================================================
#  快取與資料持久化
# ============================================================

def _safe_float(value, default: float = 0.0) -> float:
    """安全轉換浮點數，處理空字串與非數值"""
    if value is None or value == "" or value == "-":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def cache_farm_data(data: list[dict], source: str, target_date: date = None):
    """將蔬果行情資料寫入 price_history 快取

    每筆資料對應一個食材 × 市場 × 日期的記錄。
    若食材不在 ingredients 表中則跳過（不自動建立）。

    Args:
        data: FarmTransData API 回傳的資料列表
        source: 資料來源標記（如 'moa_vegetable', 'moa_fruit'）
        target_date: 資料日期
    """
    if target_date is None:
        target_date = date.today()

    date_str = target_date.isoformat()
    cached_count = 0

    for item in data:
        crop_name = item.get("作物名稱", "").strip()
        if not crop_name:
            continue

        # 查找對應食材
        ingredient = sm.find_ingredient(crop_name)
        if not ingredient:
            continue

        avg_price = _safe_float(item.get("平均價"))
        high_price = _safe_float(item.get("上價"))
        low_price = _safe_float(item.get("下價"))
        volume = _safe_float(item.get("交易量"))
        market_name = item.get("市場名稱", "").strip()

        # 跳過無效價格（平均價為 0 通常表示休市或無資料）
        if avg_price <= 0:
            continue

        try:
            sm.add_price_history(
                ingredient_id=ingredient["id"],
                price_date=date_str,
                source=source,
                avg_price=avg_price,
                high_price=high_price,
                low_price=low_price,
                market_name=market_name,
                volume=volume,
            )
            cached_count += 1
        except Exception as e:
            logger.warning(f"快取農產品價格失敗 ({crop_name}): {e}")

    logger.info(f"快取 {source} 共 {cached_count}/{len(data)} 筆")


def cache_pork_data(data: list[dict], target_date: date = None):
    """將豬肉行情資料寫入 price_history 快取

    Args:
        data: PorkTransType API 回傳的資料列表
        target_date: 資料日期
    """
    if target_date is None:
        target_date = date.today()

    date_str = target_date.isoformat()
    cached_count = 0

    for item in data:
        type_name = item.get("TypeName", "").strip()
        if not type_name:
            continue

        ingredient = sm.find_ingredient(type_name)
        if not ingredient:
            # 嘗試用「豬肉」做模糊匹配
            if "豬" in type_name:
                ingredient = sm.find_ingredient("豬肉")
            if not ingredient:
                continue

        avg_price = _safe_float(item.get("AvgPrice"))
        high_price = _safe_float(item.get("MaxPrice"))
        low_price = _safe_float(item.get("MinPrice"))
        market_name = item.get("MarketName", "").strip()
        volume = _safe_float(item.get("TradeVolume"))

        if avg_price <= 0:
            continue

        try:
            sm.add_price_history(
                ingredient_id=ingredient["id"],
                price_date=date_str,
                source="moa_pork",
                avg_price=avg_price,
                high_price=high_price,
                low_price=low_price,
                market_name=market_name,
                volume=volume,
            )
            cached_count += 1
        except Exception as e:
            logger.warning(f"快取豬肉價格失敗 ({type_name}): {e}")

    logger.info(f"快取 moa_pork 共 {cached_count}/{len(data)} 筆")


def cache_poultry_data(data: list[dict]):
    """將禽蛋行情資料寫入 price_history 快取

    禽蛋 API 回傳的每筆記錄包含多個品項（白肉雞、雞蛋等），
    需拆解為個別食材的價格記錄。

    Args:
        data: PoultryTransType API 回傳的資料列表
    """
    # 欄位對照：API 欄位名稱 → 食材搜尋關鍵字
    field_mapping = {
        "白肉雞(2.0Kg以上)": "白肉雞",
        "雞蛋(產地價)": "雞蛋",
    }

    cached_count = 0

    for item in data:
        # 解析日期：民國日期格式 YYY.MM.DD
        raw_date = item.get("日期", "").strip()
        item_date = _parse_roc_date(raw_date)
        if not item_date:
            continue

        date_str = item_date.isoformat()

        for field_name, search_name in field_mapping.items():
            price = _safe_float(item.get(field_name))
            if price <= 0:
                continue

            ingredient = sm.find_ingredient(search_name)
            if not ingredient:
                continue

            try:
                sm.add_price_history(
                    ingredient_id=ingredient["id"],
                    price_date=date_str,
                    source="moa_poultry",
                    avg_price=price,
                    market_name="產地",
                )
                cached_count += 1
            except Exception as e:
                logger.warning(f"快取禽蛋價格失敗 ({search_name}): {e}")

    logger.info(f"快取 moa_poultry 共 {cached_count} 筆")


def _parse_roc_date(roc_str: str) -> Optional[date]:
    """解析民國日期字串（支援有點號/無點號格式）

    Args:
        roc_str: 民國日期字串，如 '115.02.18' 或 '1150218'

    Returns:
        date 物件，解析失敗回傳 None
    """
    if not roc_str:
        return None

    try:
        roc_str = roc_str.strip()
        if "." in roc_str:
            parts = roc_str.split(".")
            if len(parts) != 3:
                return None
            roc_year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        elif len(roc_str) == 7:
            # 格式 YYYMMDD（民國三位數年）
            roc_year = int(roc_str[:3])
            month = int(roc_str[3:5])
            day = int(roc_str[5:7])
        else:
            return None

        western_year = roc_year + 1911
        return date(western_year, month, day)
    except (ValueError, IndexError):
        return None


# ============================================================
#  每日同步
# ============================================================

def _sync_all_market_data_sync(target_date: date = None):
    """同步所有市場行情資料（同步版本，由 async wrapper 透過 to_thread 呼叫）

    依序取得蔬菜、水果、豬肉、禽蛋行情並寫入快取。
    任一 API 失敗不影響其他 API 的取得。

    Args:
        target_date: 同步日期，預設為今天
    """
    if target_date is None:
        target_date = date.today()

    logger.info(f"開始同步市場行情資料: {target_date.isoformat()}")

    # 1. 蔬菜
    try:
        veg_data = fetch_vegetables(target_date)
        if veg_data:
            cache_farm_data(veg_data, "moa_vegetable", target_date)
    except Exception as e:
        logger.error(f"同步蔬菜行情失敗: {e}")

    # 2. 水果
    try:
        fruit_data = fetch_fruits(target_date)
        if fruit_data:
            cache_farm_data(fruit_data, "moa_fruit", target_date)
    except Exception as e:
        logger.error(f"同步水果行情失敗: {e}")

    # 3. 豬肉
    try:
        pork_data = fetch_pork(target_date)
        if pork_data:
            cache_pork_data(pork_data, target_date)
    except Exception as e:
        logger.error(f"同步豬肉行情失敗: {e}")

    # 4. 禽蛋（不指定日期，API 自動回傳近期資料）
    try:
        poultry_data = fetch_poultry_eggs()
        if poultry_data:
            cache_poultry_data(poultry_data)
    except Exception as e:
        logger.error(f"同步禽蛋行情失敗: {e}")

    logger.info("市場行情資料同步完成")


async def sync_all_market_data(target_date: date = None):
    """Async wrapper — 透過 to_thread 避免阻塞 event loop"""
    import asyncio
    return await asyncio.to_thread(_sync_all_market_data_sync, target_date)


# ============================================================
#  價格比對與異常偵測
# ============================================================

def compare_price(item_name: str, purchase_price: float) -> dict:
    """比對採購價格與市場行情，偵測異常

    演算法分兩階段：
    1. 冷啟動期（< 30 筆資料）：使用固定門檻 ±30% 判斷
    2. 穩定期（>= 30 筆資料）：使用 Z-score 偵測異常（> 2.5σ）

    偏差等級：
    - normal:       偏差 < 10%
    - slightly_high: 偏差 10-20%
    - overpriced:    偏差 > 20%

    Args:
        item_name: 食材名稱
        purchase_price: 採購單價

    Returns:
        比對結果字典，含以下欄位：
        - item_name: 食材名稱
        - purchase_price: 採購價
        - market_avg: 市場均價（無資料時為 None）
        - deviation_pct: 偏差百分比（無資料時為 None）
        - alert_level: 'normal' / 'slightly_high' / 'overpriced' / 'no_data'
        - method: 使用的偵測方法（'fixed_threshold' / 'zscore'）
        - data_points: 歷史資料筆數
        - is_anomaly: Z-score 方法下是否為異常值
    """
    result = {
        "item_name": item_name,
        "purchase_price": purchase_price,
        "market_avg": None,
        "deviation_pct": None,
        "alert_level": "no_data",
        "method": None,
        "data_points": 0,
        "is_anomaly": False,
    }

    # 查找食材
    ingredient = sm.find_ingredient(item_name)
    if not ingredient:
        logger.info(f"找不到食材「{item_name}」，無法比價")
        return result

    # 取得歷史價格（最多 90 天，取得足夠資料進行統計）
    history = sm.get_price_history(ingredient["id"], days=90)
    if not history:
        # 嘗試使用快取（CACHE_DAYS 天內的資料）
        logger.info(f"食材「{item_name}」無歷史價格資料")
        return result

    # 提取有效的平均價格
    prices = [
        h["avg_price"] for h in history
        if h.get("avg_price") is not None and h["avg_price"] > 0
    ]

    result["data_points"] = len(prices)

    if not prices:
        return result

    # 計算市場均價
    market_avg = statistics.mean(prices)
    result["market_avg"] = round(market_avg, 2)

    # 計算偏差百分比
    if market_avg > 0:
        deviation_pct = ((purchase_price - market_avg) / market_avg) * 100
        result["deviation_pct"] = round(deviation_pct, 2)
    else:
        return result

    # 判斷偏差等級
    abs_deviation = abs(deviation_pct)
    if abs_deviation < NORMAL_THRESHOLD_PCT:
        result["alert_level"] = "normal"
    elif abs_deviation < SLIGHT_HIGH_THRESHOLD_PCT:
        result["alert_level"] = "slightly_high"
    else:
        result["alert_level"] = "overpriced"

    # 選擇異常偵測方法
    if len(prices) < MIN_DATA_POINTS:
        # 冷啟動期：固定門檻
        result["method"] = "fixed_threshold"
        result["is_anomaly"] = abs_deviation > FIXED_THRESHOLD_PCT
    else:
        # 穩定期：Z-score 偵測
        result["method"] = "zscore"
        z_score = _calculate_zscore(purchase_price, prices)
        result["zscore"] = round(z_score, 2)
        result["is_anomaly"] = abs(z_score) > ZSCORE_THRESHOLD

    return result


def _calculate_zscore(value: float, data: list[float]) -> float:
    """計算 Z-score（標準分數）

    Z = (X - μ) / σ
    σ = 0 時回傳 0（所有價格相同，無法判斷異常）

    Args:
        value: 要檢驗的值
        data: 歷史資料列表

    Returns:
        Z-score 值
    """
    if len(data) < 2:
        return 0.0

    mean = statistics.mean(data)
    stdev = statistics.stdev(data)

    if stdev == 0:
        return 0.0

    return (value - mean) / stdev


# ============================================================
#  快取回退查詢
# ============================================================

def get_cached_price(item_name: str, days: int = None) -> Optional[dict]:
    """從快取取得食材的最近市場行情

    當 API 無法取得即時資料時，回退至快取資料。
    預設查詢 CACHE_DAYS（7 天）內的資料。

    Args:
        item_name: 食材名稱
        days: 查詢天數，預設為 CACHE_DAYS

    Returns:
        最近一筆市場行情字典，或 None
    """
    if days is None:
        days = CACHE_DAYS

    ingredient = sm.find_ingredient(item_name)
    if not ingredient:
        return None

    history = sm.get_price_history(ingredient["id"], days=days)
    if not history:
        return None

    # 回傳最近一筆有效資料
    for record in history:
        if record.get("avg_price") and record["avg_price"] > 0:
            return record

    return None


async def get_today_summary() -> str:
    """取得今日行情摘要，回傳格式化文字供 LINE 顯示

    Returns:
        格式化的行情文字摘要，或 None（無資料時）
    """
    import asyncio

    summary = await asyncio.to_thread(get_market_summary)
    if not summary or not summary.get("categories"):
        return None

    lines = [f"📊 今日農產品行情（{summary['roc_date']}）", ""]

    for cat_name, cat_data in summary["categories"].items():
        count = cat_data.get("count", 0)
        source = cat_data.get("source", "")
        if count == 0:
            lines.append(f"【{cat_name}】休市或無資料")
            continue

        lines.append(f"【{cat_name}】{count} 筆")
        sample = cat_data.get("sample", [])
        for item in sample:
            name = item.get("name", "")
            avg_price = item.get("avg_price", 0)
            if name and avg_price > 0:
                lines.append(f"  {name}：${avg_price:.1f}/kg")
        lines.append("")

    return "\n".join(lines)


async def get_item_price_info(item_name: str) -> str:
    """查詢特定食材的市場行情，回傳格式化文字

    Args:
        item_name: 食材名稱

    Returns:
        格式化的價格資訊文字，或 None（無資料時）
    """
    # 先嘗試從快取取得
    cached = get_cached_price(item_name)
    if cached:
        lines = [
            f"📈 「{item_name}」行情",
            f"  市場：{cached.get('market_name', '未知')}",
            f"  均價：${cached.get('avg_price', 0):.1f}/kg",
        ]
        if cached.get("high_price"):
            lines.append(f"  上價：${cached['high_price']:.1f}")
        if cached.get("low_price"):
            lines.append(f"  下價：${cached['low_price']:.1f}")
        if cached.get("price_date"):
            lines.append(f"  日期：{cached['price_date']}")

        # 附加歷史比對資訊
        ingredient = sm.find_ingredient(item_name)
        if ingredient:
            history = sm.get_price_history(ingredient["id"], days=30)
            prices = [h["avg_price"] for h in history
                      if h.get("avg_price") and h["avg_price"] > 0]
            if len(prices) >= 2:
                avg_30d = statistics.mean(prices)
                lines.append(f"  30日均價：${avg_30d:.1f}")
                if prices[0] > 0:
                    trend = ((prices[0] - avg_30d) / avg_30d) * 100
                    trend_icon = "📈" if trend > 0 else "📉" if trend < 0 else "➡️"
                    lines.append(f"  趨勢：{trend_icon} {trend:+.1f}%")

        return "\n".join(lines)

    # 快取無資料，嘗試即時查詢蔬果 API
    import asyncio
    veg_data = await asyncio.to_thread(fetch_vegetables)
    fruit_data = await asyncio.to_thread(fetch_fruits)
    all_data = veg_data + fruit_data

    matches = [
        item for item in all_data
        if item_name in item.get("作物名稱", "")
    ]

    if not matches:
        return None

    lines = [f"📈 「{item_name}」今日行情", ""]
    seen = set()
    for item in matches[:5]:
        crop = item.get("作物名稱", "").strip()
        market = item.get("市場名稱", "").strip()
        key = f"{crop}-{market}"
        if key in seen:
            continue
        seen.add(key)
        avg_p = _safe_float(item.get("平均價"))
        high_p = _safe_float(item.get("上價"))
        low_p = _safe_float(item.get("下價"))
        lines.append(f"  {crop}（{market}）")
        lines.append(f"    均價 ${avg_p:.1f} ｜上 ${high_p:.1f} ｜下 ${low_p:.1f}")

    return "\n".join(lines)


def get_market_summary(target_date: date = None) -> dict:
    """取得指定日期的市場行情摘要

    彙整蔬菜、水果、豬肉、禽蛋四大類的行情概況。
    API 失敗時自動回退至快取資料。

    Args:
        target_date: 查詢日期，預設為今天

    Returns:
        行情摘要字典，含各類別的資料筆數與代表品項
    """
    if target_date is None:
        target_date = date.today()

    summary = {
        "date": target_date.isoformat(),
        "roc_date": to_roc_date(target_date),
        "categories": {},
    }

    # 蔬菜
    veg_data = fetch_vegetables(target_date)
    if veg_data:
        summary["categories"]["蔬菜"] = {
            "count": len(veg_data),
            "source": "api",
            "sample": _extract_top_items(veg_data, "作物名稱", "平均價", n=5),
        }
    else:
        summary["categories"]["蔬菜"] = {"count": 0, "source": "cache_or_empty"}

    # 水果
    fruit_data = fetch_fruits(target_date)
    if fruit_data:
        summary["categories"]["水果"] = {
            "count": len(fruit_data),
            "source": "api",
            "sample": _extract_top_items(fruit_data, "作物名稱", "平均價", n=5),
        }
    else:
        summary["categories"]["水果"] = {"count": 0, "source": "cache_or_empty"}

    # 豬肉
    pork_data = fetch_pork(target_date)
    if pork_data:
        summary["categories"]["豬肉"] = {
            "count": len(pork_data),
            "source": "api",
        }
    else:
        summary["categories"]["豬肉"] = {"count": 0, "source": "cache_or_empty"}

    # 禽蛋
    poultry_data = fetch_poultry_eggs()
    if poultry_data:
        summary["categories"]["禽蛋"] = {
            "count": len(poultry_data),
            "source": "api",
        }
    else:
        summary["categories"]["禽蛋"] = {"count": 0, "source": "cache_or_empty"}

    return summary


def _extract_top_items(data: list[dict], name_key: str, price_key: str,
                       n: int = 5) -> list[dict]:
    """從行情資料中提取交易量最大的前 N 個品項

    Args:
        data: 行情資料列表
        name_key: 品項名稱欄位
        price_key: 價格欄位
        n: 取前幾名

    Returns:
        精簡的品項列表 [{name, avg_price}]
    """
    # 依交易量排序（降序）
    sorted_data = sorted(
        data,
        key=lambda x: _safe_float(x.get("交易量", 0)),
        reverse=True,
    )

    seen = set()
    result = []
    for item in sorted_data:
        name = item.get(name_key, "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        result.append({
            "name": name,
            "avg_price": _safe_float(item.get(price_key)),
        })
        if len(result) >= n:
            break

    return result
