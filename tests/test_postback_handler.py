"""postback_handler.py 單元測試 — Postback 路由 + 六宮格選單 + 子選單動作"""

import asyncio
import os
import sys
import unittest
from unittest.mock import patch, MagicMock, AsyncMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _run(coro):
    """同步執行 async 函數"""
    return asyncio.get_event_loop().run_until_complete(coro)


# ============================================================
# 1. TestParseData — _parse_data() helper
# ============================================================

class TestParseData(unittest.TestCase):
    """測試 _parse_data() 解析 postback data 字串"""

    def _parse(self, data_str):
        from handlers.postback_handler import _parse_data
        return _parse_data(data_str)

    def test_single_key_value(self):
        result = self._parse("menu=camera")
        self.assertEqual(result, {"menu": "camera"})

    def test_multiple_key_values(self):
        result = self._parse("action=report&type=expense&period=month")
        self.assertEqual(result["action"], "report")
        self.assertEqual(result["type"], "expense")
        self.assertEqual(result["period"], "month")

    def test_blank_value_preserved(self):
        result = self._parse("action=export&type=")
        self.assertIn("type", result)
        self.assertEqual(result["type"], "")

    def test_empty_string(self):
        result = self._parse("")
        self.assertEqual(result, {})

    def test_url_encoded_chars(self):
        result = self._parse("action=report&ym=2026-03")
        self.assertEqual(result["ym"], "2026-03")

    def test_id_numeric_string(self):
        result = self._parse("action=confirm&id=42")
        self.assertEqual(result["id"], "42")

    def test_complex_postback(self):
        result = self._parse("action=do_export&type=mof_txt&period=2026-01")
        self.assertEqual(result["action"], "do_export")
        self.assertEqual(result["type"], "mof_txt")
        self.assertEqual(result["period"], "2026-01")

    def test_menu_only(self):
        result = self._parse("menu=finance")
        self.assertEqual(result, {"menu": "finance"})
        self.assertNotIn("action", result)

    def test_action_with_cmd(self):
        result = self._parse("action=purchase&cmd=pending")
        self.assertEqual(result["action"], "purchase")
        self.assertEqual(result["cmd"], "pending")


# ============================================================
# 2. TestMenuRouting — 六宮格主選單
# ============================================================

class TestMenuRouting(unittest.TestCase):
    """測試六宮格選單 postback → 正確的 Flex Message"""

    def setUp(self):
        self.line_svc = MagicMock()

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_camera_menu(self, mock_sm, mock_fb):
        from handlers.postback_handler import handle_postback
        mock_fb.build_camera_menu.return_value = {"type": "bubble", "body": {}}
        _run(handle_postback(self.line_svc, "menu=camera", "G001", "U001", "RT001"))
        mock_fb.build_camera_menu.assert_called_once()
        self.line_svc.reply_flex.assert_called_once()
        args = self.line_svc.reply_flex.call_args
        self.assertEqual(args[0][0], "RT001")
        self.assertIn("拍照", args[0][1])

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_finance_menu(self, mock_sm, mock_fb):
        from handlers.postback_handler import handle_postback
        mock_fb.build_finance_menu.return_value = {"type": "carousel"}
        _run(handle_postback(self.line_svc, "menu=finance", "G001", "U001", "RT001"))
        mock_fb.build_finance_menu.assert_called_once()
        self.line_svc.reply_flex.assert_called_once()
        args = self.line_svc.reply_flex.call_args
        self.assertIn("財務", args[0][1])

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_purchase_menu(self, mock_sm, mock_fb):
        from handlers.postback_handler import handle_postback
        mock_sm.get_pending_stagings.return_value = [{"id": 1}, {"id": 2}]
        mock_fb.build_purchase_menu.return_value = {"type": "bubble"}
        _run(handle_postback(self.line_svc, "menu=purchase", "G001", "U001", "RT001"))
        mock_sm.get_pending_stagings.assert_called_once()
        mock_fb.build_purchase_menu.assert_called_once_with(2)
        self.line_svc.reply_flex.assert_called_once()
        args = self.line_svc.reply_flex.call_args
        self.assertIn("採購", args[0][1])

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_purchase_menu_empty(self, mock_sm, mock_fb):
        from handlers.postback_handler import handle_postback
        mock_sm.get_pending_stagings.return_value = []
        mock_fb.build_purchase_menu.return_value = {"type": "bubble"}
        _run(handle_postback(self.line_svc, "menu=purchase", "G001", "U001", "RT001"))
        mock_fb.build_purchase_menu.assert_called_once_with(0)

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_menu_plan_menu(self, mock_sm, mock_fb):
        from handlers.postback_handler import handle_postback
        mock_fb.build_menu_plan_menu.return_value = {"type": "carousel"}
        _run(handle_postback(self.line_svc, "menu=menu_plan", "G001", "U001", "RT001"))
        mock_fb.build_menu_plan_menu.assert_called_once()
        self.line_svc.reply_flex.assert_called_once()
        args = self.line_svc.reply_flex.call_args
        self.assertIn("菜單", args[0][1])

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_export_menu(self, mock_sm, mock_fb):
        from handlers.postback_handler import handle_postback
        mock_fb.build_export_menu.return_value = {"type": "carousel"}
        _run(handle_postback(self.line_svc, "menu=export", "G001", "U001", "RT001"))
        mock_fb.build_export_menu.assert_called_once()
        self.line_svc.reply_flex.assert_called_once()
        args = self.line_svc.reply_flex.call_args
        self.assertIn("匯出", args[0][1])

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_guide_menu(self, mock_sm, mock_fb):
        from handlers.postback_handler import handle_postback
        mock_fb.build_guide_menu.return_value = {"type": "carousel"}
        _run(handle_postback(self.line_svc, "menu=guide", "G001", "U001", "RT001"))
        mock_fb.build_guide_menu.assert_called_once()
        self.line_svc.reply_flex.assert_called_once()
        args = self.line_svc.reply_flex.call_args
        self.assertIn("說明", args[0][1])

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_unknown_menu_no_reply(self, mock_sm, mock_fb):
        """未知的 menu 值不應觸發 reply_flex"""
        from handlers.postback_handler import handle_postback
        _run(handle_postback(self.line_svc, "menu=nonexistent", "G001", "U001", "RT001"))
        self.line_svc.reply_flex.assert_not_called()


# ============================================================
# 3. TestReportActions — 財務報表子動作
# ============================================================

class TestReportActions(unittest.TestCase):
    """測試 action=report 的各類型報表"""

    def setUp(self):
        self.line_svc = MagicMock()

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_financial_index(self, mock_sm, mock_fb):
        from handlers.postback_handler import handle_postback
        mock_sm.get_staging_stats.return_value = {
            "total_count": 10, "confirmed_count": 8, "total_amount": 50000
        }
        mock_fb.build_stats_flex.return_value = {"type": "bubble"}
        _run(handle_postback(
            self.line_svc, "action=report&type=financial_index",
            "G001", "U001", "RT001"))
        mock_sm.get_staging_stats.assert_called_once()
        mock_fb.build_stats_flex.assert_called_once()
        self.line_svc.reply_flex.assert_called_once()
        args = self.line_svc.reply_flex.call_args
        self.assertIn("財報索引", args[0][1])

    @patch("handlers.postback_handler.sm")
    def test_expense_report_month(self, mock_sm):
        from handlers.postback_handler import handle_postback
        staging = {"id": 1, "supplier_name": "A"}
        mock_sm.get_stagings_by_month.return_value = [staging]
        mock_sm.get_purchase_items.return_value = [
            {"category": "蔬菜", "amount": 3000},
            {"category": "肉類", "amount": 5000},
        ]
        _run(handle_postback(
            self.line_svc, "action=report&type=expense&period=month&ym=2026-03",
            "G001", "U001", "RT001"))
        mock_sm.get_stagings_by_month.assert_called_once_with("2026-03")
        self.line_svc.reply.assert_called_once()
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("費用一覽", msg)
        self.assertIn("蔬菜", msg)
        self.assertIn("肉類", msg)
        self.assertIn("8,000", msg)

    @patch("handlers.postback_handler.sm")
    def test_expense_report_no_data(self, mock_sm):
        from handlers.postback_handler import handle_postback
        mock_sm.get_stagings_by_month.return_value = []
        _run(handle_postback(
            self.line_svc, "action=report&type=expense&period=month&ym=2026-03",
            "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("無資料", msg)

    @patch("handlers.postback_handler.sm")
    def test_expense_bimonth(self, mock_sm):
        """雙月報表 — 呼叫兩個月份"""
        from handlers.postback_handler import handle_postback
        mock_sm.get_stagings_by_month.return_value = []
        _run(handle_postback(
            self.line_svc, "action=report&type=expense&period=bimonth&ym=2026-03",
            "G001", "U001", "RT001"))
        # bimonth 會查詢兩個月份
        self.assertGreaterEqual(mock_sm.get_stagings_by_month.call_count, 2)

    @patch("handlers.postback_handler.sm")
    def test_income_report_with_data(self, mock_sm):
        from handlers.postback_handler import handle_postback
        mock_sm.get_income_summary.return_value = [
            {"amount": 100000, "description": "午餐營收"},
            {"amount": 50000, "description": "外燴收入"},
        ]
        _run(handle_postback(
            self.line_svc, "action=report&type=income&ym=2026-03",
            "G001", "U001", "RT001"))
        mock_sm.get_income_summary.assert_called_once_with("2026-03")
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("收入一覽", msg)
        self.assertIn("午餐營收", msg)
        self.assertIn("100,000", msg)
        self.assertIn("150,000", msg)  # 合計

    @patch("handlers.postback_handler.sm")
    def test_income_report_no_data(self, mock_sm):
        from handlers.postback_handler import handle_postback
        mock_sm.get_income_summary.return_value = []
        _run(handle_postback(
            self.line_svc, "action=report&type=income&ym=2026-03",
            "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("尚未建立", msg)

    @patch("handlers.postback_handler.sm")
    def test_unknown_report_type(self, mock_sm):
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "action=report&type=unknown_xyz",
            "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("未知報表類型", msg)

    @patch("handlers.postback_handler.sm")
    def test_expense_default_ym(self, mock_sm):
        """未提供 ym 時應自動使用當月"""
        from handlers.postback_handler import handle_postback
        from datetime import datetime
        mock_sm.get_stagings_by_month.return_value = []
        _run(handle_postback(
            self.line_svc, "action=report&type=expense",
            "G001", "U001", "RT001"))
        called_ym = mock_sm.get_stagings_by_month.call_args[0][0]
        expected_ym = datetime.now().strftime("%Y-%m")
        self.assertEqual(called_ym, expected_ym)


# ============================================================
# 4. TestPurchaseActions — 採購管理子動作
# ============================================================

class TestPurchaseActions(unittest.TestCase):
    """測試 action=purchase 的各指令"""

    def setUp(self):
        self.line_svc = MagicMock()

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_pending_list(self, mock_sm, mock_fb):
        from handlers.postback_handler import handle_postback
        pendings = [
            {"id": 1, "supplier_name": "A", "total_amount": 1000, "status": "pending"},
            {"id": 2, "supplier_name": "B", "total_amount": 2000, "status": "pending"},
        ]
        mock_sm.get_pending_stagings.return_value = pendings
        mock_fb.build_pending_list_flex.return_value = {"type": "carousel"}
        _run(handle_postback(
            self.line_svc, "action=purchase&cmd=pending",
            "G001", "U001", "RT001"))
        mock_sm.get_pending_stagings.assert_called_once_with("G001")
        mock_fb.build_pending_list_flex.assert_called_once_with(pendings)
        self.line_svc.reply_flex.assert_called_once()
        alt_text = self.line_svc.reply_flex.call_args[0][1]
        self.assertIn("2", alt_text)

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_pending_list_empty(self, mock_sm, mock_fb):
        from handlers.postback_handler import handle_postback
        mock_sm.get_pending_stagings.return_value = []
        mock_fb.build_pending_list_flex.return_value = {"type": "bubble"}
        _run(handle_postback(
            self.line_svc, "action=purchase&cmd=pending",
            "G001", "U001", "RT001"))
        alt_text = self.line_svc.reply_flex.call_args[0][1]
        self.assertIn("0", alt_text)

    @patch("handlers.postback_handler.sm")
    def test_market_summary_success(self, mock_sm):
        from handlers.postback_handler import handle_postback
        with patch("handlers.postback_handler.get_market_summary",
                   create=True) as mock_market:
            # We need to patch the import inside the function
            pass
        # Market is imported inside the function, patch at module level
        with patch.dict("sys.modules", {
            "services.market_service": MagicMock(
                get_market_summary=MagicMock(return_value={
                    "蔬菜": [
                        {"品名": "高麗菜", "平均價": 25},
                        {"品名": "白菜", "平均價": 20},
                    ],
                    "水果": [
                        {"品名": "蘋果", "平均價": 80},
                    ],
                })
            )
        }):
            _run(handle_postback(
                self.line_svc, "action=purchase&cmd=market",
                "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("農產品行情", msg)
        self.assertIn("高麗菜", msg)

    @patch("handlers.postback_handler.sm")
    def test_market_no_data(self, mock_sm):
        from handlers.postback_handler import handle_postback
        with patch.dict("sys.modules", {
            "services.market_service": MagicMock(
                get_market_summary=MagicMock(return_value=None)
            )
        }):
            _run(handle_postback(
                self.line_svc, "action=purchase&cmd=market",
                "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("暫無", msg)

    @patch("handlers.postback_handler.sm")
    def test_market_exception(self, mock_sm):
        from handlers.postback_handler import handle_postback
        with patch.dict("sys.modules", {
            "services.market_service": MagicMock(
                get_market_summary=MagicMock(side_effect=Exception("API down"))
            )
        }):
            _run(handle_postback(
                self.line_svc, "action=purchase&cmd=market",
                "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("暫時無法使用", msg)

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_suppliers_list(self, mock_sm, mock_fb):
        from handlers.postback_handler import handle_postback
        suppliers = [
            {"id": 1, "name": "好鮮水產行"},
            {"id": 2, "name": "大同蔬果"},
        ]
        mock_sm.get_all_suppliers.return_value = suppliers
        mock_fb.build_supplier_list_flex.return_value = {"type": "carousel"}
        _run(handle_postback(
            self.line_svc, "action=purchase&cmd=suppliers",
            "G001", "U001", "RT001"))
        mock_sm.get_all_suppliers.assert_called_once()
        mock_fb.build_supplier_list_flex.assert_called_once_with(suppliers)
        self.line_svc.reply_flex.assert_called_once()
        alt_text = self.line_svc.reply_flex.call_args[0][1]
        self.assertIn("2", alt_text)

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_price_compare_with_data(self, mock_sm, mock_fb):
        from handlers.postback_handler import handle_postback
        comparisons = [{"ingredient": "高麗菜", "purchase_price": 30, "market_price": 25}]
        mock_sm.get_price_comparisons.return_value = comparisons
        mock_fb.build_price_compare_flex.return_value = {"type": "bubble"}
        _run(handle_postback(
            self.line_svc, "action=purchase&cmd=price_compare",
            "G001", "U001", "RT001"))
        mock_sm.get_price_comparisons.assert_called_once()
        mock_fb.build_price_compare_flex.assert_called_once_with(comparisons)
        self.line_svc.reply_flex.assert_called_once()

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_price_compare_no_data(self, mock_sm, mock_fb):
        from handlers.postback_handler import handle_postback
        mock_sm.get_price_comparisons.return_value = []
        _run(handle_postback(
            self.line_svc, "action=purchase&cmd=price_compare",
            "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("尚無足夠", msg)
        mock_fb.build_price_compare_flex.assert_not_called()

    @patch("handlers.postback_handler.sm")
    def test_unknown_purchase_cmd(self, mock_sm):
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "action=purchase&cmd=nonexistent",
            "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("未知的採購指令", msg)


# ============================================================
# 5. TestExportActions — 匯出中心
# ============================================================

class TestExportActions(unittest.TestCase):
    """測試匯出流程：type select → period picker → do_export"""

    def setUp(self):
        self.line_svc = MagicMock()

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_export_select_monthly(self, mock_sm, mock_fb):
        from handlers.postback_handler import handle_postback
        mock_fb.build_export_period_picker.return_value = {"type": "bubble"}
        _run(handle_postback(
            self.line_svc, "action=export&type=monthly",
            "G001", "U001", "RT001"))
        mock_fb.build_export_period_picker.assert_called_once_with("monthly")
        self.line_svc.reply_flex.assert_called_once()

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_export_select_annual(self, mock_sm, mock_fb):
        from handlers.postback_handler import handle_postback
        mock_fb.build_export_period_picker.return_value = {"type": "bubble"}
        _run(handle_postback(
            self.line_svc, "action=export&type=annual",
            "G001", "U001", "RT001"))
        mock_fb.build_export_period_picker.assert_called_once_with("annual")

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_export_select_default_type(self, mock_sm, mock_fb):
        """未指定 type 預設 monthly"""
        from handlers.postback_handler import handle_postback
        mock_fb.build_export_period_picker.return_value = {"type": "bubble"}
        _run(handle_postback(
            self.line_svc, "action=export",
            "G001", "U001", "RT001"))
        mock_fb.build_export_period_picker.assert_called_once_with("monthly")

    @patch("handlers.postback_handler.sm")
    def test_do_export_monthly_success(self, mock_sm):
        from handlers.postback_handler import handle_postback
        with patch.dict("sys.modules", {
            "services.report_service": MagicMock(
                generate_monthly_report=MagicMock(
                    return_value="/data/exports/2026-03/report.xlsx")
            )
        }):
            _run(handle_postback(
                self.line_svc, "action=do_export&type=monthly&period=2026-03",
                "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("月報表已生成", msg)
        self.assertIn("report.xlsx", msg)

    @patch("handlers.postback_handler.sm")
    def test_do_export_monthly_no_data(self, mock_sm):
        from handlers.postback_handler import handle_postback
        with patch.dict("sys.modules", {
            "services.report_service": MagicMock(
                generate_monthly_report=MagicMock(return_value=None)
            )
        }):
            _run(handle_postback(
                self.line_svc, "action=do_export&type=monthly&period=2026-03",
                "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("無可匯出", msg)

    @patch("handlers.postback_handler.sm")
    def test_do_export_annual_success(self, mock_sm):
        from handlers.postback_handler import handle_postback
        with patch.dict("sys.modules", {
            "services.report_service": MagicMock(
                generate_annual_report=MagicMock(
                    return_value="/data/exports/2026/annual.xlsx")
            )
        }):
            _run(handle_postback(
                self.line_svc, "action=do_export&type=annual&period=2026-01",
                "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("年報表已生成", msg)

    @patch("handlers.postback_handler.sm")
    def test_do_export_annual_no_data(self, mock_sm):
        from handlers.postback_handler import handle_postback
        with patch.dict("sys.modules", {
            "services.report_service": MagicMock(
                generate_annual_report=MagicMock(return_value=None)
            )
        }):
            _run(handle_postback(
                self.line_svc, "action=do_export&type=annual&period=2026-01",
                "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("無可匯出", msg)

    @patch("handlers.postback_handler.sm")
    def test_do_export_mof_txt_success(self, mock_sm):
        from handlers.postback_handler import handle_postback
        mock_tax_svc = MagicMock()
        mock_tax_svc.validate_before_export.return_value = (True, [])
        mock_tax_svc.export_mof_txt.return_value = "/data/exports/2026-01/mof.txt"
        with patch.dict("sys.modules", {
            "services.tax_export_service": mock_tax_svc
        }):
            _run(handle_postback(
                self.line_svc, "action=do_export&type=mof_txt&period=2026-01",
                "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("稅務申報檔已生成", msg)

    @patch("handlers.postback_handler.sm")
    def test_do_export_mof_txt_validation_fail(self, mock_sm):
        from handlers.postback_handler import handle_postback
        mock_tax_svc = MagicMock()
        mock_tax_svc.validate_before_export.return_value = (
            False, ["缺少發票號碼", "供應商統編不正確"])
        with patch.dict("sys.modules", {
            "services.tax_export_service": mock_tax_svc
        }):
            _run(handle_postback(
                self.line_svc, "action=do_export&type=mof_txt&period=2026-01",
                "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("驗證未通過", msg)
        self.assertIn("缺少發票號碼", msg)
        self.assertIn("供應商統編不正確", msg)

    @patch("handlers.postback_handler.sm")
    def test_do_export_accounting_success(self, mock_sm):
        from handlers.postback_handler import handle_postback
        mock_tax_svc = MagicMock()
        mock_tax_svc.export_winton_excel.return_value = "/data/exports/2026-01/winton.xlsx"
        with patch.dict("sys.modules", {
            "services.tax_export_service": mock_tax_svc
        }):
            _run(handle_postback(
                self.line_svc, "action=do_export&type=accounting&period=2026-01",
                "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("會計匯出已生成", msg)

    @patch("handlers.postback_handler.sm")
    def test_do_export_handler_cert_success(self, mock_sm):
        from handlers.postback_handler import handle_postback
        mock_tax_svc = MagicMock()
        mock_tax_svc.export_handler_cert.return_value = "/data/exports/2026-01/cert.pdf"
        with patch.dict("sys.modules", {
            "services.tax_export_service": mock_tax_svc
        }):
            _run(handle_postback(
                self.line_svc, "action=do_export&type=handler_cert&period=2026-01",
                "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("經手人憑證已生成", msg)

    @patch("handlers.postback_handler.sm")
    def test_do_export_handler_cert_no_data(self, mock_sm):
        from handlers.postback_handler import handle_postback
        mock_tax_svc = MagicMock()
        mock_tax_svc.export_handler_cert.return_value = None
        with patch.dict("sys.modules", {
            "services.tax_export_service": mock_tax_svc
        }):
            _run(handle_postback(
                self.line_svc, "action=do_export&type=handler_cert&period=2026-01",
                "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("無需經手人憑證", msg)

    @patch("handlers.postback_handler.sm")
    def test_do_export_no_period(self, mock_sm):
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "action=do_export&type=monthly&period=",
            "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("請指定匯出期間", msg)

    @patch("handlers.postback_handler.sm")
    def test_do_export_unknown_type(self, mock_sm):
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "action=do_export&type=unknown_type&period=2026-01",
            "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("未知的匯出類型", msg)

    @patch("handlers.postback_handler.sm")
    def test_do_export_exception(self, mock_sm):
        from handlers.postback_handler import handle_postback
        with patch.dict("sys.modules", {
            "services.report_service": MagicMock(
                generate_monthly_report=MagicMock(
                    side_effect=Exception("DB connection lost"))
            )
        }):
            _run(handle_postback(
                self.line_svc, "action=do_export&type=monthly&period=2026-03",
                "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("匯出發生錯誤", msg)
        self.assertIn("DB connection lost", msg)


# ============================================================
# 6. TestQuickActions — 快速確認/修改/捨棄
# ============================================================

class TestQuickActions(unittest.TestCase):
    """測試 pending list flex 按鈕觸發的 confirm/edit/discard"""

    def setUp(self):
        self.line_svc = MagicMock()

    # --- confirm ---

    @patch("handlers.postback_handler.sm")
    def test_confirm_success(self, mock_sm):
        from handlers.postback_handler import handle_postback
        mock_sm.get_staging.return_value = {
            "id": 42, "status": "pending", "supplier_name": "好鮮水產行",
            "total_amount": 5000, "supplier_id": 1,
        }
        mock_sm.get_supplier.return_value = {"has_uniform_invoice": True}
        mock_sm.get_purchase_items.return_value = [
            {"ingredient_id": 10, "unit_price": 35},
        ]
        _run(handle_postback(
            self.line_svc, "action=confirm&id=42",
            "G001", "U001", "RT001"))
        mock_sm.confirm_staging.assert_called_once_with(42)
        mock_sm.update_ingredient_price.assert_called_once_with(10, 35)
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("#42", msg)
        self.assertIn("已確認", msg)
        self.assertIn("好鮮水產行", msg)
        self.assertIn("5,000", msg)

    @patch("handlers.postback_handler.sm")
    def test_confirm_invalid_id(self, mock_sm):
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "action=confirm&id=0",
            "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("無效的記錄編號", msg)
        mock_sm.confirm_staging.assert_not_called()

    @patch("handlers.postback_handler.sm")
    def test_confirm_not_found(self, mock_sm):
        from handlers.postback_handler import handle_postback
        mock_sm.get_staging.return_value = None
        _run(handle_postback(
            self.line_svc, "action=confirm&id=999",
            "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("找不到記錄", msg)

    @patch("handlers.postback_handler.sm")
    def test_confirm_already_confirmed(self, mock_sm):
        from handlers.postback_handler import handle_postback
        mock_sm.get_staging.return_value = {
            "id": 42, "status": "confirmed", "supplier_id": 1,
        }
        _run(handle_postback(
            self.line_svc, "action=confirm&id=42",
            "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("已是", msg)
        self.assertIn("confirmed", msg)
        mock_sm.confirm_staging.assert_not_called()

    @patch("handlers.postback_handler.sm")
    def test_confirm_needs_handler(self, mock_sm):
        """無統一發票供應商 + 無經手人 → 要求填寫經手人"""
        from handlers.postback_handler import handle_postback
        mock_sm.get_staging.return_value = {
            "id": 42, "status": "pending", "supplier_id": 5,
            "handler_name": "",
        }
        mock_sm.get_supplier.return_value = {"has_uniform_invoice": False}
        _run(handle_postback(
            self.line_svc, "action=confirm&id=42",
            "G001", "U001", "RT001"))
        mock_sm.set_state.assert_called_once_with(
            "G001", "waiting_handler", {"staging_id": 42})
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("經手人", msg)
        mock_sm.confirm_staging.assert_not_called()

    @patch("handlers.postback_handler.sm")
    def test_confirm_with_handler_already_set(self, mock_sm):
        """無統一發票但已有經手人 → 直接確認"""
        from handlers.postback_handler import handle_postback
        mock_sm.get_staging.return_value = {
            "id": 42, "status": "pending", "supplier_name": "菜市場阿嬤",
            "total_amount": 1000, "supplier_id": 5,
            "handler_name": "王小美",
        }
        mock_sm.get_supplier.return_value = {"has_uniform_invoice": False}
        mock_sm.get_purchase_items.return_value = []
        _run(handle_postback(
            self.line_svc, "action=confirm&id=42",
            "G001", "U001", "RT001"))
        mock_sm.confirm_staging.assert_called_once_with(42)
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("已確認", msg)

    @patch("handlers.postback_handler.sm")
    def test_confirm_updates_multiple_ingredient_prices(self, mock_sm):
        """確認時更新多個食材價格"""
        from handlers.postback_handler import handle_postback
        mock_sm.get_staging.return_value = {
            "id": 10, "status": "pending", "supplier_name": "大同蔬果",
            "total_amount": 8000, "supplier_id": 2,
        }
        mock_sm.get_supplier.return_value = {"has_uniform_invoice": True}
        mock_sm.get_purchase_items.return_value = [
            {"ingredient_id": 1, "unit_price": 30},
            {"ingredient_id": 2, "unit_price": 50},
            {"ingredient_id": None, "unit_price": 25},  # 無 ingredient_id，不更新
        ]
        _run(handle_postback(
            self.line_svc, "action=confirm&id=10",
            "G001", "U001", "RT001"))
        self.assertEqual(mock_sm.update_ingredient_price.call_count, 2)
        mock_sm.update_ingredient_price.assert_any_call(1, 30)
        mock_sm.update_ingredient_price.assert_any_call(2, 50)

    @patch("handlers.postback_handler.sm")
    def test_confirm_no_supplier_record(self, mock_sm):
        """supplier 查不到（None）→ 直接確認不檢查經手人"""
        from handlers.postback_handler import handle_postback
        mock_sm.get_staging.return_value = {
            "id": 7, "status": "pending", "supplier_name": "X",
            "total_amount": 300, "supplier_id": None,
        }
        mock_sm.get_supplier.return_value = None
        mock_sm.get_purchase_items.return_value = []
        _run(handle_postback(
            self.line_svc, "action=confirm&id=7",
            "G001", "U001", "RT001"))
        mock_sm.confirm_staging.assert_called_once_with(7)

    # --- edit ---

    @patch("handlers.postback_handler.sm")
    def test_edit_success(self, mock_sm):
        from handlers.postback_handler import handle_postback
        mock_sm.get_staging.return_value = {
            "id": 42, "status": "pending", "supplier_name": "A",
        }
        _run(handle_postback(
            self.line_svc, "action=edit&id=42",
            "G001", "U001", "RT001"))
        mock_sm.set_state.assert_called_once_with(
            "G001", "waiting_edit", {"staging_id": 42})
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("修改模式", msg)
        self.assertIn("#42", msg)

    @patch("handlers.postback_handler.sm")
    def test_edit_not_found(self, mock_sm):
        from handlers.postback_handler import handle_postback
        mock_sm.get_staging.return_value = None
        _run(handle_postback(
            self.line_svc, "action=edit&id=999",
            "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("找不到記錄", msg)
        mock_sm.set_state.assert_not_called()

    # --- discard ---

    @patch("handlers.postback_handler.sm")
    def test_discard_success(self, mock_sm):
        from handlers.postback_handler import handle_postback
        mock_sm.get_staging.return_value = {
            "id": 42, "status": "pending",
        }
        _run(handle_postback(
            self.line_svc, "action=discard&id=42",
            "G001", "U001", "RT001"))
        mock_sm.update_purchase_staging.assert_called_once_with(42, status="discarded")
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("#42", msg)
        self.assertIn("已捨棄", msg)

    @patch("handlers.postback_handler.sm")
    def test_discard_not_found(self, mock_sm):
        from handlers.postback_handler import handle_postback
        mock_sm.get_staging.return_value = None
        _run(handle_postback(
            self.line_svc, "action=discard&id=999",
            "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("找不到記錄", msg)
        mock_sm.update_purchase_staging.assert_not_called()


# ============================================================
# 7. TestMenuActions — 菜單企劃子動作
# ============================================================

class TestMenuActions(unittest.TestCase):
    """測試 action=menu 的子指令"""

    def setUp(self):
        self.line_svc = MagicMock()

    @patch("handlers.postback_handler.sm")
    def test_view_current_with_data(self, mock_sm):
        from handlers.postback_handler import handle_postback
        mock_sm.get_menu_schedule.return_value = [
            {"recipe_name": "紅燒肉", "schedule_date": "2026-03-01", "meal_type": "午"},
            {"recipe_name": "三杯雞", "schedule_date": "2026-03-02", "meal_type": "午"},
        ]
        _run(handle_postback(
            self.line_svc, "action=menu&cmd=view_current",
            "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("菜單", msg)
        self.assertIn("紅燒肉", msg)
        self.assertIn("三杯雞", msg)

    @patch("handlers.postback_handler.sm")
    def test_view_current_no_data(self, mock_sm):
        from handlers.postback_handler import handle_postback
        mock_sm.get_menu_schedule.return_value = []
        _run(handle_postback(
            self.line_svc, "action=menu&cmd=view_current",
            "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("尚未建立", msg)

    @patch("handlers.postback_handler.sm")
    def test_edit_menu(self, mock_sm):
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "action=menu&cmd=edit",
            "G001", "U001", "RT001"))
        mock_sm.set_state.assert_called_once_with("G001", "waiting_menu_edit", {})
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("菜單編輯模式", msg)
        self.assertIn("完成菜單", msg)

    @patch("handlers.postback_handler.sm")
    def test_gen_image(self, mock_sm):
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "action=menu&cmd=gen_image",
            "G001", "U001", "RT001"))
        mock_sm.set_state.assert_called_once_with("G001", "waiting_dish_name", {})
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("菜色圖片生成", msg)

    @patch("handlers.postback_handler.sm")
    def test_cost_calc(self, mock_sm):
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "action=menu&cmd=cost_calc",
            "G001", "U001", "RT001"))
        mock_sm.set_state.assert_called_once_with("G001", "waiting_cost_input", {})
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("食材成本試算", msg)

    @patch("handlers.postback_handler.sm")
    def test_unknown_menu_cmd(self, mock_sm):
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "action=menu&cmd=nonexistent",
            "G001", "U001", "RT001"))
        msg = self.line_svc.reply.call_args[0][1]
        self.assertIn("未知的菜單指令", msg)


# ============================================================
# 8. TestAltText — _alt_text() helper
# ============================================================

class TestAltText(unittest.TestCase):
    """測試 _alt_text() 標籤對照"""

    def _alt(self, menu):
        from handlers.postback_handler import _alt_text
        return _alt_text(menu)

    def test_camera(self):
        self.assertIn("拍照", self._alt("camera"))

    def test_finance(self):
        self.assertIn("財務", self._alt("finance"))

    def test_purchase(self):
        self.assertIn("採購", self._alt("purchase"))

    def test_menu_plan(self):
        self.assertIn("菜單", self._alt("menu_plan"))

    def test_export(self):
        self.assertIn("匯出", self._alt("export"))

    def test_finance_upload(self):
        self.assertIn("財務資料", self._alt("finance_upload"))

    def test_reports(self):
        self.assertIn("報表", self._alt("reports"))

    def test_guide(self):
        self.assertIn("說明", self._alt("guide"))

    def test_unknown_fallback(self):
        result = self._alt("nonexistent")
        self.assertEqual(result, "小膳選單")


# ============================================================
# 9. TestUnknownPostback — 未知動作
# ============================================================

class TestUnknownPostback(unittest.TestCase):
    """測試完全未知的 postback data"""

    def setUp(self):
        self.line_svc = MagicMock()

    @patch("handlers.postback_handler.sm")
    def test_unknown_action_logs_warning(self, mock_sm):
        from handlers.postback_handler import handle_postback
        with patch("handlers.postback_handler.logger") as mock_logger:
            _run(handle_postback(
                self.line_svc, "something=random",
                "G001", "U001", "RT001"))
            mock_logger.warning.assert_called_once()
            self.assertIn("something=random",
                          mock_logger.warning.call_args[0][0])

    @patch("handlers.postback_handler.sm")
    def test_no_menu_no_action(self, mock_sm):
        """無 menu 也無 action → 不觸發任何 reply"""
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "foo=bar",
            "G001", "U001", "RT001"))
        self.line_svc.reply.assert_not_called()
        self.line_svc.reply_flex.assert_not_called()


# ============================================================
# 10. TestFinanceUploadMenu — v2.2 finance_upload 路由
# ============================================================

class TestFinanceUploadMenu(unittest.TestCase):
    """測試 menu=finance_upload 路由"""

    def setUp(self):
        self.line_svc = MagicMock()

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_finance_upload_menu(self, mock_sm, mock_fb):
        mock_fb.build_finance_upload_menu.return_value = {"type": "carousel", "contents": []}
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "menu=finance_upload",
            "G001", "U001", "RT001"))
        mock_fb.build_finance_upload_menu.assert_called_once()
        self.line_svc.reply_flex.assert_called_once()


# ============================================================
# 11. TestReportsMenu — v2.2 reports 路由
# ============================================================

class TestReportsMenu(unittest.TestCase):
    """測試 menu=reports 路由"""

    def setUp(self):
        self.line_svc = MagicMock()

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_reports_menu(self, mock_sm, mock_fb):
        mock_fb.build_reports_menu.return_value = {"type": "carousel", "contents": []}
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "menu=reports",
            "G001", "U001", "RT001"))
        mock_fb.build_reports_menu.assert_called_once()
        self.line_svc.reply_flex.assert_called_once()


# ============================================================
# 12. TestFinanceDocsActions — v2.2 finance_docs 動作
# ============================================================

class TestFinanceDocsActions(unittest.TestCase):
    """測試 action=finance_docs 子路由"""

    def setUp(self):
        self.line_svc = MagicMock()

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_list_command(self, mock_sm, mock_fb):
        mock_sm.get_financial_documents.return_value = []
        mock_fb.build_finance_doc_list_flex.return_value = {"type": "bubble"}
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "action=finance_docs&cmd=list",
            "G001", "U001", "RT001"))
        mock_sm.get_financial_documents.assert_called_once()
        self.line_svc.reply_flex.assert_called_once()

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_summary_command(self, mock_sm, mock_fb):
        mock_sm.get_financial_doc_summary.return_value = {
            "year_month": "2026-02", "total": 0, "confirmed": 0, "categories": {},
        }
        mock_fb.build_finance_doc_summary_flex.return_value = {"type": "bubble"}
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "action=finance_docs&cmd=summary",
            "G001", "U001", "RT001"))
        self.line_svc.reply_flex.assert_called_once()

    @patch("handlers.postback_handler.sm")
    def test_search_sets_state(self, mock_sm):
        mock_sm.get_financial_documents.return_value = []
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "action=finance_docs&cmd=search",
            "G001", "U001", "RT001"))
        mock_sm.set_state.assert_called_once_with("G001", "waiting_finance_search", {})

    @patch("handlers.postback_handler.sm")
    def test_confirm_month(self, mock_sm):
        mock_sm.get_financial_documents.return_value = [
            {"id": 1, "status": "pending"},
            {"id": 2, "status": "confirmed"},
        ]
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "action=finance_docs&cmd=confirm_month",
            "G001", "U001", "RT001"))
        # 只有 id=1 should be updated
        mock_sm.update_financial_document.assert_called_once()
        self.line_svc.reply.assert_called_once()


# ============================================================
# 13. TestFileActions — v2.2 file_confirm / file_reclassify
# ============================================================

class TestFileActions(unittest.TestCase):
    """測試 file_confirm, file_reclassify, file_set_category"""

    def setUp(self):
        self.line_svc = MagicMock()

    @patch("handlers.postback_handler.sm")
    def test_file_confirm(self, mock_sm):
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "action=file_confirm&id=7",
            "G001", "U001", "RT001"))
        mock_sm.update_financial_document.assert_called_once()
        self.line_svc.reply.assert_called_once()
        self.assertIn("確認", self.line_svc.reply.call_args[0][1])

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_file_reclassify(self, mock_sm, mock_fb):
        mock_fb.build_file_reclassify_flex.return_value = {"type": "bubble"}
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "action=file_reclassify&id=7",
            "G001", "U001", "RT001"))
        mock_fb.build_file_reclassify_flex.assert_called_once_with(7)
        self.line_svc.reply_flex.assert_called_once()

    @patch("handlers.postback_handler.sm")
    def test_file_set_category(self, mock_sm):
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "action=file_set_category&id=7&cat=payroll",
            "G001", "U001", "RT001"))
        mock_sm.update_financial_document.assert_called_once_with(7, doc_category="payroll")
        self.assertIn("人力資源", self.line_svc.reply.call_args[0][1])


# ============================================================
# 14. TestGenReportActions — v2.2 四大報表路由
# ============================================================

class TestGenReportActions(unittest.TestCase):
    """測試 action=gen_report 和 action=do_gen_report"""

    def setUp(self):
        self.line_svc = MagicMock()

    @patch("handlers.postback_handler.fb")
    @patch("handlers.postback_handler.sm")
    def test_gen_report_shows_period_picker(self, mock_sm, mock_fb):
        mock_fb.build_report_period_picker.return_value = {"type": "bubble"}
        from handlers.postback_handler import handle_postback
        _run(handle_postback(
            self.line_svc, "action=gen_report&type=balance_sheet",
            "G001", "U001", "RT001"))
        mock_fb.build_report_period_picker.assert_called_once_with("balance_sheet")
        self.line_svc.reply_flex.assert_called_once()


if __name__ == "__main__":
    unittest.main()
