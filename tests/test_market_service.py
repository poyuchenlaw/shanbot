"""小膳 Bot - 市場行情服務 單元測試

測試範圍：
- 日期格式轉換（民國日期有點號/無點號）
- 價格比對邏輯（normal / slightly_high / overpriced）
- Z-score 異常偵測
- API 回應解析
- 快取回退機制
"""

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

# 將專案根目錄加入 path
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.market_service import (
    to_roc_date,
    to_roc_date_no_dot,
    compare_price,
    fetch_vegetables,
    fetch_fruits,
    fetch_pork,
    fetch_poultry_eggs,
    _calculate_zscore,
    _safe_float,
    _parse_roc_date,
    _fetch_farm_trans,
    cache_farm_data,
    get_cached_price,
    CATEGORY_VEGETABLE,
    CATEGORY_FRUIT,
)


class TestDateConversion(unittest.TestCase):
    """測試民國日期轉換"""

    def test_to_roc_date_basic(self):
        """基本轉換：2026-02-18 → 115.02.18"""
        d = date(2026, 2, 18)
        self.assertEqual(to_roc_date(d), "115.02.18")

    def test_to_roc_date_no_dot_basic(self):
        """無點號轉換：2026-02-18 → 1150218"""
        d = date(2026, 2, 18)
        self.assertEqual(to_roc_date_no_dot(d), "1150218")

    def test_to_roc_date_year_boundary(self):
        """跨年邊界：2026-01-01 → 115.01.01"""
        d = date(2026, 1, 1)
        self.assertEqual(to_roc_date(d), "115.01.01")

    def test_to_roc_date_no_dot_year_boundary(self):
        """跨年邊界無點號：2026-01-01 → 1150101"""
        d = date(2026, 1, 1)
        self.assertEqual(to_roc_date_no_dot(d), "1150101")

    def test_to_roc_date_end_of_year(self):
        """年末：2026-12-31 → 115.12.31"""
        d = date(2026, 12, 31)
        self.assertEqual(to_roc_date(d), "115.12.31")

    def test_to_roc_date_earlier_year(self):
        """較早年份：2024-06-15 → 113.06.15"""
        d = date(2024, 6, 15)
        self.assertEqual(to_roc_date(d), "113.06.15")

    def test_to_roc_date_no_dot_earlier_year(self):
        """較早年份無點號：2024-06-15 → 1130615"""
        d = date(2024, 6, 15)
        self.assertEqual(to_roc_date_no_dot(d), "1130615")

    def test_to_roc_date_default_today(self):
        """預設使用今天日期"""
        result = to_roc_date()
        today = date.today()
        expected = f"{today.year - 1911}.{today.month:02d}.{today.day:02d}"
        self.assertEqual(result, expected)

    def test_to_roc_date_no_dot_default_today(self):
        """無點號預設使用今天日期"""
        result = to_roc_date_no_dot()
        today = date.today()
        expected = f"{today.year - 1911}{today.month:02d}{today.day:02d}"
        self.assertEqual(result, expected)

    def test_to_roc_date_zero_padded_month(self):
        """月份零補位：2026-03-05 → 115.03.05"""
        d = date(2026, 3, 5)
        self.assertEqual(to_roc_date(d), "115.03.05")
        self.assertEqual(to_roc_date_no_dot(d), "1150305")


class TestParseRocDate(unittest.TestCase):
    """測試民國日期字串解析"""

    def test_parse_with_dots(self):
        """有點號格式：115.02.18 → 2026-02-18"""
        result = _parse_roc_date("115.02.18")
        self.assertEqual(result, date(2026, 2, 18))

    def test_parse_no_dots(self):
        """無點號格式：1150218 → 2026-02-18"""
        result = _parse_roc_date("1150218")
        self.assertEqual(result, date(2026, 2, 18))

    def test_parse_empty_string(self):
        """空字串回傳 None"""
        self.assertIsNone(_parse_roc_date(""))

    def test_parse_none(self):
        """None 回傳 None"""
        self.assertIsNone(_parse_roc_date(None))

    def test_parse_invalid_format(self):
        """無效格式回傳 None"""
        self.assertIsNone(_parse_roc_date("abc"))
        self.assertIsNone(_parse_roc_date("115-02-18"))
        self.assertIsNone(_parse_roc_date("11502"))

    def test_parse_with_whitespace(self):
        """前後有空白"""
        result = _parse_roc_date("  115.02.18  ")
        self.assertEqual(result, date(2026, 2, 18))


class TestSafeFloat(unittest.TestCase):
    """測試安全浮點數轉換"""

    def test_normal_number(self):
        self.assertEqual(_safe_float(42.5), 42.5)

    def test_string_number(self):
        self.assertEqual(_safe_float("35.2"), 35.2)

    def test_integer(self):
        self.assertEqual(_safe_float(100), 100.0)

    def test_none(self):
        self.assertEqual(_safe_float(None), 0.0)

    def test_empty_string(self):
        self.assertEqual(_safe_float(""), 0.0)

    def test_dash(self):
        self.assertEqual(_safe_float("-"), 0.0)

    def test_invalid_string(self):
        self.assertEqual(_safe_float("N/A"), 0.0)

    def test_custom_default(self):
        self.assertEqual(_safe_float(None, default=-1.0), -1.0)


class TestPriceComparison(unittest.TestCase):
    """測試價格比對邏輯"""

    @patch("services.market_service.sm")
    def test_normal_price(self, mock_sm):
        """正常價格：偏差 < 10%"""
        mock_sm.find_ingredient.return_value = {
            "id": 1, "name": "高麗菜", "category": "蔬菜",
            "current_price": 25, "market_ref_price": 25,
        }
        # 20 筆歷史資料（< 30，使用固定門檻）
        mock_sm.get_price_history.return_value = [
            {"avg_price": 25.0, "price_date": f"2026-02-{i:02d}"}
            for i in range(1, 21)
        ]

        result = compare_price("高麗菜", 26.0)
        self.assertEqual(result["alert_level"], "normal")
        self.assertAlmostEqual(result["market_avg"], 25.0)
        self.assertAlmostEqual(result["deviation_pct"], 4.0)
        self.assertEqual(result["method"], "fixed_threshold")
        self.assertFalse(result["is_anomaly"])

    @patch("services.market_service.sm")
    def test_slightly_high_price(self, mock_sm):
        """偏高價格：偏差 10-20%"""
        mock_sm.find_ingredient.return_value = {
            "id": 1, "name": "高麗菜", "category": "蔬菜",
            "current_price": 25, "market_ref_price": 25,
        }
        mock_sm.get_price_history.return_value = [
            {"avg_price": 25.0, "price_date": f"2026-02-{i:02d}"}
            for i in range(1, 21)
        ]

        # 偏差 = (29 - 25) / 25 * 100 = 16%
        result = compare_price("高麗菜", 29.0)
        self.assertEqual(result["alert_level"], "slightly_high")
        self.assertAlmostEqual(result["deviation_pct"], 16.0)

    @patch("services.market_service.sm")
    def test_overpriced(self, mock_sm):
        """偏貴價格：偏差 > 20%"""
        mock_sm.find_ingredient.return_value = {
            "id": 1, "name": "高麗菜", "category": "蔬菜",
            "current_price": 25, "market_ref_price": 25,
        }
        mock_sm.get_price_history.return_value = [
            {"avg_price": 25.0, "price_date": f"2026-02-{i:02d}"}
            for i in range(1, 21)
        ]

        # 偏差 = (35 - 25) / 25 * 100 = 40%
        result = compare_price("高麗菜", 35.0)
        self.assertEqual(result["alert_level"], "overpriced")
        self.assertAlmostEqual(result["deviation_pct"], 40.0)
        # 固定門檻 30%，40% > 30% → is_anomaly = True
        self.assertTrue(result["is_anomaly"])

    @patch("services.market_service.sm")
    def test_no_data(self, mock_sm):
        """查無食材資料"""
        mock_sm.find_ingredient.return_value = None

        result = compare_price("不存在的食材", 100)
        self.assertEqual(result["alert_level"], "no_data")
        self.assertIsNone(result["market_avg"])
        self.assertIsNone(result["deviation_pct"])

    @patch("services.market_service.sm")
    def test_no_history(self, mock_sm):
        """食材存在但無歷史資料"""
        mock_sm.find_ingredient.return_value = {
            "id": 1, "name": "高麗菜", "category": "蔬菜",
            "current_price": 25, "market_ref_price": 25,
        }
        mock_sm.get_price_history.return_value = []

        result = compare_price("高麗菜", 30)
        self.assertEqual(result["alert_level"], "no_data")

    @patch("services.market_service.sm")
    def test_negative_deviation(self, mock_sm):
        """採購價低於市場均價（負偏差）"""
        mock_sm.find_ingredient.return_value = {
            "id": 1, "name": "高麗菜", "category": "蔬菜",
            "current_price": 25, "market_ref_price": 25,
        }
        mock_sm.get_price_history.return_value = [
            {"avg_price": 25.0, "price_date": f"2026-02-{i:02d}"}
            for i in range(1, 21)
        ]

        # 偏差 = (20 - 25) / 25 * 100 = -20%，abs = 20% → overpriced
        result = compare_price("高麗菜", 20.0)
        self.assertAlmostEqual(result["deviation_pct"], -20.0)
        self.assertEqual(result["alert_level"], "overpriced")

    @patch("services.market_service.sm")
    def test_fixed_threshold_not_anomaly(self, mock_sm):
        """固定門檻期間，偏差 25%（< 30%）→ 非異常"""
        mock_sm.find_ingredient.return_value = {
            "id": 1, "name": "豬肉", "category": "肉類",
            "current_price": 80, "market_ref_price": 80,
        }
        # 少於 30 筆 → 使用固定門檻
        mock_sm.get_price_history.return_value = [
            {"avg_price": 80.0, "price_date": f"2026-02-{i:02d}"}
            for i in range(1, 11)
        ]

        # 偏差 = (100 - 80) / 80 * 100 = 25%，< 30% 固定門檻
        result = compare_price("豬肉", 100.0)
        self.assertEqual(result["method"], "fixed_threshold")
        self.assertFalse(result["is_anomaly"])
        # 但 25% > 20% → alert_level = overpriced
        self.assertEqual(result["alert_level"], "overpriced")

    @patch("services.market_service.sm")
    def test_fixed_threshold_is_anomaly(self, mock_sm):
        """固定門檻期間，偏差 > 30% → 異常"""
        mock_sm.find_ingredient.return_value = {
            "id": 1, "name": "豬肉", "category": "肉類",
            "current_price": 80, "market_ref_price": 80,
        }
        mock_sm.get_price_history.return_value = [
            {"avg_price": 80.0, "price_date": f"2026-02-{i:02d}"}
            for i in range(1, 11)
        ]

        # 偏差 = (110 - 80) / 80 * 100 = 37.5%，> 30%
        result = compare_price("豬肉", 110.0)
        self.assertEqual(result["method"], "fixed_threshold")
        self.assertTrue(result["is_anomaly"])


class TestZScoreDetection(unittest.TestCase):
    """測試 Z-score 異常偵測"""

    def test_zscore_normal_value(self):
        """正常值的 Z-score 應接近 0"""
        data = [25.0, 26.0, 24.0, 25.5, 24.5, 25.2, 24.8, 26.1, 25.3, 24.7]
        z = _calculate_zscore(25.0, data)
        self.assertAlmostEqual(z, 0.0, delta=0.5)

    def test_zscore_high_outlier(self):
        """極端高值的 Z-score 應顯著大於 0"""
        data = [25.0, 26.0, 24.0, 25.5, 24.5, 25.2, 24.8, 26.1, 25.3, 24.7]
        z = _calculate_zscore(35.0, data)
        self.assertGreater(z, 2.5)

    def test_zscore_low_outlier(self):
        """極端低值的 Z-score 應顯著小於 0"""
        data = [25.0, 26.0, 24.0, 25.5, 24.5, 25.2, 24.8, 26.1, 25.3, 24.7]
        z = _calculate_zscore(15.0, data)
        self.assertLess(z, -2.5)

    def test_zscore_identical_data(self):
        """所有資料相同（標準差 = 0）→ Z-score = 0"""
        data = [25.0] * 10
        z = _calculate_zscore(30.0, data)
        self.assertEqual(z, 0.0)

    def test_zscore_single_data_point(self):
        """只有一筆資料 → Z-score = 0"""
        z = _calculate_zscore(30.0, [25.0])
        self.assertEqual(z, 0.0)

    @patch("services.market_service.sm")
    def test_zscore_method_with_enough_data(self, mock_sm):
        """30+ 筆資料時使用 Z-score 方法"""
        mock_sm.find_ingredient.return_value = {
            "id": 1, "name": "高麗菜", "category": "蔬菜",
            "current_price": 25, "market_ref_price": 25,
        }
        # 35 筆資料，平均 25，標準差很小
        prices = [25.0 + (i % 5 - 2) * 0.5 for i in range(35)]
        mock_sm.get_price_history.return_value = [
            {"avg_price": p, "price_date": f"2026-01-{(i % 28) + 1:02d}"}
            for i, p in enumerate(prices)
        ]

        result = compare_price("高麗菜", 25.5)
        self.assertEqual(result["method"], "zscore")
        self.assertEqual(result["data_points"], 35)
        self.assertIn("zscore", result)

    @patch("services.market_service.sm")
    def test_zscore_detects_anomaly(self, mock_sm):
        """Z-score > 2.5σ 偵測為異常"""
        mock_sm.find_ingredient.return_value = {
            "id": 1, "name": "雞蛋", "category": "蛋豆",
            "current_price": 50, "market_ref_price": 50,
        }
        # 穩定價格在 50 附近（σ 很小）
        prices = [50.0 + (i % 3 - 1) * 0.5 for i in range(40)]
        mock_sm.get_price_history.return_value = [
            {"avg_price": p, "price_date": f"2026-01-{(i % 28) + 1:02d}"}
            for i, p in enumerate(prices)
        ]

        # 購入價 70 → 遠超均值，Z-score 應 > 2.5
        result = compare_price("雞蛋", 70.0)
        self.assertEqual(result["method"], "zscore")
        self.assertTrue(result["is_anomaly"])


class TestFetchVegetables(unittest.TestCase):
    """測試蔬菜行情 API 呼叫"""

    @patch("services.market_service.requests.get")
    def test_fetch_vegetables_success(self, mock_get):
        """成功取得蔬菜資料"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "種類代碼": "N04",
                "作物名稱": "甘藍",
                "市場名稱": "台北一",
                "上價": "30.5",
                "中價": "25.0",
                "下價": "20.0",
                "平均價": "25.2",
                "交易量": "15000",
            },
            {
                "種類代碼": "N04",
                "作物名稱": "青江菜",
                "市場名稱": "台北一",
                "上價": "22.0",
                "中價": "18.0",
                "下價": "15.0",
                "平均價": "18.3",
                "交易量": "8000",
            },
            {
                "種類代碼": "N05",  # 水果，應被過濾
                "作物名稱": "蘋果",
                "市場名稱": "台北一",
                "上價": "80.0",
                "中價": "60.0",
                "下價": "45.0",
                "平均價": "61.7",
                "交易量": "3000",
            },
        ]
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = fetch_vegetables(date(2026, 2, 18))

        # 應只回傳 N04（蔬菜），過濾掉 N05（水果）
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["作物名稱"], "甘藍")
        self.assertEqual(result[1]["作物名稱"], "青江菜")

        # 驗證 API 呼叫參數
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        self.assertIn("StartDate", call_args.kwargs.get("params", call_args[1].get("params", {})))

    @patch("services.market_service.requests.get")
    def test_fetch_vegetables_api_error(self, mock_get):
        """API 請求失敗回傳空列表"""
        import requests as real_requests
        mock_get.side_effect = real_requests.ConnectionError("Connection timeout")

        result = fetch_vegetables(date(2026, 2, 18))
        self.assertEqual(result, [])

    @patch("services.market_service.requests.get")
    def test_fetch_vegetables_http_error(self, mock_get):
        """HTTP 錯誤回傳空列表"""
        import requests as real_requests
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = real_requests.HTTPError("500 Server Error")
        mock_get.return_value = mock_response

        result = fetch_vegetables(date(2026, 2, 18))
        self.assertEqual(result, [])

    @patch("services.market_service.requests.get")
    def test_fetch_vegetables_invalid_json(self, mock_get):
        """JSON 解析失敗回傳空列表"""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_get.return_value = mock_response

        result = fetch_vegetables(date(2026, 2, 18))
        self.assertEqual(result, [])


class TestFetchFruits(unittest.TestCase):
    """測試水果行情 API 呼叫"""

    @patch("services.market_service.requests.get")
    def test_fetch_fruits_filters_correctly(self, mock_get):
        """正確篩選水果種類代碼 N05"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"種類代碼": "N04", "作物名稱": "高麗菜", "平均價": "25"},
            {"種類代碼": "N05", "作物名稱": "香蕉", "平均價": "18"},
            {"種類代碼": "N05", "作物名稱": "蘋果", "平均價": "60"},
        ]
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = fetch_fruits(date(2026, 2, 18))
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["作物名稱"], "香蕉")
        self.assertEqual(result[1]["作物名稱"], "蘋果")


class TestFetchPork(unittest.TestCase):
    """測試豬肉行情 API 呼叫"""

    @patch("services.market_service.requests.get")
    def test_fetch_pork_wrapped_format(self, mock_get):
        """正確解析包裝格式 {"RS":"OK","Data":[...]}"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "RS": "OK",
            "Data": [
                {
                    "TypeName": "規格豬",
                    "AvgPrice": "75.5",
                    "MaxPrice": "82.0",
                    "MinPrice": "68.0",
                    "MarketName": "台北",
                    "TradeVolume": "2500",
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = fetch_pork(date(2026, 2, 18))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["TypeName"], "規格豬")

        # 驗證使用無點號日期
        call_args = mock_get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params", {})
        self.assertEqual(params["TransDate"], "1150218")

    @patch("services.market_service.requests.get")
    def test_fetch_pork_not_ok(self, mock_get):
        """RS != OK 回傳空列表"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"RS": "NoData", "Data": []}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = fetch_pork(date(2026, 2, 18))
        self.assertEqual(result, [])

    @patch("services.market_service.requests.get")
    def test_fetch_pork_api_failure(self, mock_get):
        """API 失敗回傳空列表"""
        import requests as real_requests
        mock_get.side_effect = real_requests.ConnectionError("Network error")

        result = fetch_pork(date(2026, 2, 18))
        self.assertEqual(result, [])


class TestFetchPoultryEggs(unittest.TestCase):
    """測試禽蛋行情 API 呼叫"""

    @patch("services.market_service.requests.get")
    def test_fetch_poultry_success(self, mock_get):
        """成功取得禽蛋資料"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "日期": "115.02.18",
                "白肉雞(2.0Kg以上)": "42.5",
                "雞蛋(產地價)": "32.0",
            },
            {
                "日期": "115.02.17",
                "白肉雞(2.0Kg以上)": "42.0",
                "雞蛋(產地價)": "31.5",
            },
        ]
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = fetch_poultry_eggs()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["日期"], "115.02.18")

        # 驗證使用 $top=30 參數
        call_args = mock_get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params", {})
        self.assertEqual(params["$top"], "30")

    @patch("services.market_service.requests.get")
    def test_fetch_poultry_non_list_response(self, mock_get):
        """非陣列回應回傳空列表"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"error": "unexpected"}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = fetch_poultry_eggs()
        self.assertEqual(result, [])


class TestCacheFallback(unittest.TestCase):
    """測試快取回退機制"""

    @patch("services.market_service.sm")
    def test_cache_fallback_on_api_failure(self, mock_sm):
        """API 失敗時從快取取得資料"""
        mock_sm.find_ingredient.return_value = {
            "id": 1, "name": "高麗菜", "category": "蔬菜",
            "current_price": 25, "market_ref_price": 25,
        }
        mock_sm.get_price_history.return_value = [
            {
                "id": 1,
                "ingredient_id": 1,
                "price_date": "2026-02-17",
                "source": "moa_vegetable",
                "market_name": "台北一",
                "avg_price": 25.0,
                "high_price": 30.0,
                "low_price": 20.0,
                "purchase_price": None,
                "volume": 15000,
            },
        ]

        result = get_cached_price("高麗菜")
        self.assertIsNotNone(result)
        self.assertEqual(result["avg_price"], 25.0)
        self.assertEqual(result["source"], "moa_vegetable")

    @patch("services.market_service.sm")
    def test_cache_fallback_no_ingredient(self, mock_sm):
        """食材不存在時回傳 None"""
        mock_sm.find_ingredient.return_value = None

        result = get_cached_price("不存在食材")
        self.assertIsNone(result)

    @patch("services.market_service.sm")
    def test_cache_fallback_no_history(self, mock_sm):
        """無快取資料時回傳 None"""
        mock_sm.find_ingredient.return_value = {
            "id": 1, "name": "高麗菜", "category": "蔬菜",
            "current_price": 25, "market_ref_price": 25,
        }
        mock_sm.get_price_history.return_value = []

        result = get_cached_price("高麗菜")
        self.assertIsNone(result)

    @patch("services.market_service.sm")
    def test_cache_skips_zero_price(self, mock_sm):
        """跳過平均價為 0 的記錄"""
        mock_sm.find_ingredient.return_value = {
            "id": 1, "name": "高麗菜", "category": "蔬菜",
            "current_price": 25, "market_ref_price": 25,
        }
        mock_sm.get_price_history.return_value = [
            {
                "id": 1,
                "ingredient_id": 1,
                "price_date": "2026-02-18",
                "source": "moa_vegetable",
                "avg_price": 0,  # 無效價格
                "high_price": 0,
                "low_price": 0,
                "purchase_price": None,
                "volume": 0,
                "market_name": "",
            },
            {
                "id": 2,
                "ingredient_id": 1,
                "price_date": "2026-02-17",
                "source": "moa_vegetable",
                "avg_price": 25.0,  # 有效
                "high_price": 30.0,
                "low_price": 20.0,
                "purchase_price": None,
                "volume": 15000,
                "market_name": "台北一",
            },
        ]

        result = get_cached_price("高麗菜")
        self.assertIsNotNone(result)
        self.assertEqual(result["avg_price"], 25.0)
        self.assertEqual(result["price_date"], "2026-02-17")


class TestCacheFarmData(unittest.TestCase):
    """測試農產品資料快取寫入"""

    @patch("services.market_service.sm")
    def test_cache_farm_data_writes_to_db(self, mock_sm):
        """正確將行情資料寫入 price_history"""
        mock_sm.find_ingredient.return_value = {
            "id": 1, "name": "甘藍", "category": "蔬菜",
        }

        data = [
            {
                "種類代碼": "N04",
                "作物名稱": "甘藍",
                "市場名稱": "台北一",
                "上價": "30.5",
                "中價": "25.0",
                "下價": "20.0",
                "平均價": "25.2",
                "交易量": "15000",
            },
        ]

        cache_farm_data(data, "moa_vegetable", date(2026, 2, 18))

        mock_sm.add_price_history.assert_called_once_with(
            ingredient_id=1,
            price_date="2026-02-18",
            source="moa_vegetable",
            avg_price=25.2,
            high_price=30.5,
            low_price=20.0,
            market_name="台北一",
            volume=15000.0,
        )

    @patch("services.market_service.sm")
    def test_cache_farm_data_skips_unknown_ingredient(self, mock_sm):
        """跳過未知食材"""
        mock_sm.find_ingredient.return_value = None

        data = [
            {
                "種類代碼": "N04",
                "作物名稱": "不明食材",
                "市場名稱": "台北一",
                "平均價": "25.2",
            },
        ]

        cache_farm_data(data, "moa_vegetable", date(2026, 2, 18))
        mock_sm.add_price_history.assert_not_called()

    @patch("services.market_service.sm")
    def test_cache_farm_data_skips_zero_price(self, mock_sm):
        """跳過平均價為 0 的記錄"""
        mock_sm.find_ingredient.return_value = {
            "id": 1, "name": "甘藍", "category": "蔬菜",
        }

        data = [
            {
                "種類代碼": "N04",
                "作物名稱": "甘藍",
                "市場名稱": "台北一",
                "上價": "0",
                "中價": "0",
                "下價": "0",
                "平均價": "0",
                "交易量": "0",
            },
        ]

        cache_farm_data(data, "moa_vegetable", date(2026, 2, 18))
        mock_sm.add_price_history.assert_not_called()

    @patch("services.market_service.sm")
    def test_cache_farm_data_empty_crop_name(self, mock_sm):
        """跳過空白作物名稱"""
        data = [{"種類代碼": "N04", "作物名稱": "", "平均價": "25"}]

        cache_farm_data(data, "moa_vegetable", date(2026, 2, 18))
        mock_sm.find_ingredient.assert_not_called()


class TestEdgeCases(unittest.TestCase):
    """測試邊界情況"""

    @patch("services.market_service.sm")
    def test_compare_price_with_all_zero_history(self, mock_sm):
        """歷史價格全為 0 時回傳 no_data"""
        mock_sm.find_ingredient.return_value = {
            "id": 1, "name": "測試", "category": "其他",
            "current_price": 0, "market_ref_price": 0,
        }
        mock_sm.get_price_history.return_value = [
            {"avg_price": 0, "price_date": f"2026-02-{i:02d}"}
            for i in range(1, 10)
        ]

        result = compare_price("測試", 25.0)
        # 所有 avg_price = 0 被過濾後 prices 為空
        self.assertEqual(result["alert_level"], "no_data")

    @patch("services.market_service.sm")
    def test_compare_price_with_none_prices(self, mock_sm):
        """歷史價格含 None 時正確過濾"""
        mock_sm.find_ingredient.return_value = {
            "id": 1, "name": "測試", "category": "其他",
            "current_price": 25, "market_ref_price": 25,
        }
        mock_sm.get_price_history.return_value = [
            {"avg_price": None, "price_date": "2026-02-01"},
            {"avg_price": 25.0, "price_date": "2026-02-02"},
            {"avg_price": 0, "price_date": "2026-02-03"},
            {"avg_price": 26.0, "price_date": "2026-02-04"},
        ]

        result = compare_price("測試", 25.5)
        # 有效資料只有 25.0 和 26.0，均值 25.5
        self.assertEqual(result["data_points"], 2)
        self.assertAlmostEqual(result["market_avg"], 25.5)

    def test_fetch_farm_trans_with_default_date(self):
        """不指定日期時使用今天"""
        with patch("services.market_service.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = []
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            _fetch_farm_trans(CATEGORY_VEGETABLE)

            # 確認呼叫了 API
            mock_get.assert_called_once()
            call_args = mock_get.call_args
            params = call_args.kwargs.get("params") or call_args[1].get("params", {})
            today_roc = to_roc_date(date.today())
            self.assertEqual(params["StartDate"], today_roc)
            self.assertEqual(params["EndDate"], today_roc)


if __name__ == "__main__":
    unittest.main()
