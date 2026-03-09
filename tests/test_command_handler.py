"""command_handler.py 單元測試 — 指令路由 + 狀態機"""

import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _run(coro):
    """同步執行 async 函數"""
    return asyncio.get_event_loop().run_until_complete(coro)


# 為 state_manager 設置暫存 DB
_original_db_path = None


def _setup_db():
    global _original_db_path
    import state_manager as sm
    _original_db_path = sm.DB_PATH
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    sm.DB_PATH = path
    sm.init_db()
    return path


def _teardown_db(path):
    import state_manager as sm
    sm.DB_PATH = _original_db_path
    try:
        os.unlink(path)
    except OSError:
        pass


class TestCommandRouting(unittest.TestCase):
    """指令路由測試"""

    def setUp(self):
        self.db_path = _setup_db()
        self.line_svc = MagicMock()

    def tearDown(self):
        _teardown_db(self.db_path)

    def test_help_command(self):
        from handlers.command_handler import handle_text
        result = _run(handle_text(self.line_svc, "help", "C001", "U001", "User", "RT001"))
        self.assertIn("小膳 Bot", result)
        self.assertIn("使用說明", result)

    def test_help_alias(self):
        from handlers.command_handler import handle_text
        result = _run(handle_text(self.line_svc, "指令", "C001", "U001", "User", "RT001"))
        self.assertIn("小膳 Bot", result)

    def test_pending_empty(self):
        from handlers.command_handler import handle_text
        result = _run(handle_text(self.line_svc, "待處理", "C001", "U001", "User", "RT001"))
        self.assertIn("沒有待處理", result)

    def test_pending_with_data(self):
        import state_manager as sm
        from handlers.command_handler import handle_text
        sid = sm.add_purchase_staging("U001", "C001", purchase_date="2026-03-15")
        sm.update_purchase_staging(sid, supplier_name="好鮮水產行", total_amount=5000)
        result = _run(handle_text(self.line_svc, "待處理", "C001", "U001", "User", "RT001"))
        self.assertIn("待處理記錄", result)
        self.assertIn("好鮮水產行", result)

    def test_stats_command(self):
        from handlers.command_handler import handle_text
        result = _run(handle_text(self.line_svc, "統計", "C001", "U001", "User", "RT001"))
        self.assertIn("統計", result)
        self.assertIn("總記錄", result)

    def test_stats_with_month(self):
        from handlers.command_handler import handle_text
        result = _run(handle_text(self.line_svc, "統計 2026-03", "C001", "U001", "User", "RT001"))
        self.assertIn("2026-03", result)

    def test_supplier_list_empty(self):
        from handlers.command_handler import handle_text
        result = _run(handle_text(self.line_svc, "供應商", "C001", "U001", "User", "RT001"))
        self.assertIn("尚未建立", result)

    def test_add_supplier(self):
        from handlers.command_handler import handle_text
        result = _run(handle_text(self.line_svc, "新增供應商 好鮮水產行 12345678",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("已新增", result)
        self.assertIn("好鮮水產行", result)
        self.assertIn("12345678", result)

    def test_supplier_list_with_data(self):
        import state_manager as sm
        from handlers.command_handler import handle_text
        sm.upsert_supplier("好鮮水產行", tax_id="12345678")
        result = _run(handle_text(self.line_svc, "供應商", "C001", "U001", "User", "RT001"))
        self.assertIn("好鮮水產行", result)

    def test_unknown_returns_none(self):
        from handlers.command_handler import handle_text
        result = _run(handle_text(self.line_svc, "今天天氣真好", "C001", "U001", "User", "RT001"))
        self.assertIsNone(result)

    def test_menu_placeholder(self):
        from handlers.command_handler import handle_text
        result = _run(handle_text(self.line_svc, "菜單", "C001", "U001", "User", "RT001"))
        self.assertIn("菜單企劃", result)


class TestConfirmDiscard(unittest.TestCase):
    """確認/捨棄採購記錄"""

    def setUp(self):
        self.db_path = _setup_db()
        self.line_svc = MagicMock()

    def tearDown(self):
        _teardown_db(self.db_path)

    def test_confirm_triggers_final(self):
        """確認 now triggers two-step: first shows final confirm prompt"""
        import state_manager as sm
        from handlers.command_handler import handle_text
        sid = sm.add_purchase_staging("U001", "C001", purchase_date="2026-03-15")
        sm.update_purchase_staging(sid, supplier_name="好鮮水產行",
                                   total_amount=5000, year_month="2026-03")
        result = _run(handle_text(self.line_svc, f"確認 #{sid}",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("最終確認", result)
        self.assertIn("好鮮水產行", result)

    def test_final_confirm_archives(self):
        """最終確認 actually archives the record"""
        import state_manager as sm
        from handlers.command_handler import handle_text
        sid = sm.add_purchase_staging("U001", "C001", purchase_date="2026-03-15")
        sm.update_purchase_staging(sid, supplier_name="好鮮水產行",
                                   total_amount=5000, year_month="2026-03")
        sm.set_state("C001", "waiting_final_confirm", {"staging_id": sid})
        result = _run(handle_text(self.line_svc, f"最終確認 #{sid}",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("已確認", result)

    def test_reject_discards(self):
        """拒絕 discards the record"""
        import state_manager as sm
        from handlers.command_handler import handle_text
        sid = sm.add_purchase_staging("U001", "C001")
        sm.update_purchase_staging(sid, year_month="2026-03")
        sm.set_state("C001", "waiting_final_confirm", {"staging_id": sid})
        result = _run(handle_text(self.line_svc, f"拒絕 #{sid}",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("不予理會", result)
        staging = sm.get_staging(sid)
        self.assertEqual(staging["status"], "discarded")

    def test_confirm_nonexistent(self):
        from handlers.command_handler import handle_text
        result = _run(handle_text(self.line_svc, "確認 #9999",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("找不到", result)

    def test_confirm_already_confirmed(self):
        import state_manager as sm
        from handlers.command_handler import handle_text
        sid = sm.add_purchase_staging("U001", "C001")
        sm.update_purchase_staging(sid, year_month="2026-03")
        sm.confirm_staging(sid)
        result = _run(handle_text(self.line_svc, f"確認 #{sid}",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("已是", result)

    def test_discard(self):
        import state_manager as sm
        from handlers.command_handler import handle_text
        sid = sm.add_purchase_staging("U001", "C001")
        result = _run(handle_text(self.line_svc, f"捨棄 #{sid}",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("已捨棄", result)
        staging = sm.get_staging(sid)
        self.assertEqual(staging["status"], "discarded")

    def test_discard_nonexistent(self):
        from handlers.command_handler import handle_text
        result = _run(handle_text(self.line_svc, "捨棄 #9999",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("找不到", result)

    def test_confirm_market_needs_handler(self):
        """菜市場採購需要經手人"""
        import state_manager as sm
        from handlers.command_handler import handle_text
        # 建立無發票供應商
        s_id = sm.upsert_supplier("菜市場阿嬤", has_invoice=False)
        sid = sm.add_purchase_staging("U001", "C001")
        sm.update_purchase_staging(sid, supplier_id=s_id, supplier_name="菜市場阿嬤",
                                   total_amount=1000, year_month="2026-03")
        result = _run(handle_text(self.line_svc, f"確認 #{sid}",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("經手人", result)
        # 驗證進入等待狀態
        state, data = sm.get_state("C001")
        self.assertEqual(state, "waiting_handler")

    def test_confirm_without_hash(self):
        """確認 1 也可以（不帶 #）— now triggers two-step"""
        import state_manager as sm
        from handlers.command_handler import handle_text
        sid = sm.add_purchase_staging("U001", "C001")
        sm.update_purchase_staging(sid, supplier_name="A", total_amount=100,
                                   year_month="2026-03")
        result = _run(handle_text(self.line_svc, f"確認 {sid}",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("最終確認", result)


class TestEditMode(unittest.TestCase):
    """修改模式"""

    def setUp(self):
        self.db_path = _setup_db()
        self.line_svc = MagicMock()

    def tearDown(self):
        _teardown_db(self.db_path)

    def test_enter_edit(self):
        import state_manager as sm
        from handlers.command_handler import handle_text
        sid = sm.add_purchase_staging("U001", "C001")
        sm.update_purchase_staging(sid, supplier_name="A", total_amount=100)
        sm.add_purchase_item(sid, "高麗菜", quantity=10, unit="kg",
                             unit_price=35, amount=350)
        result = _run(handle_text(self.line_svc, f"修改 #{sid}",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("修改記錄", result)
        self.assertIn("高麗菜", result)
        self.assertIn("請直接說要改什麼", result)

    def test_edit_supplier(self):
        import state_manager as sm
        from handlers.command_handler import handle_text
        sid = sm.add_purchase_staging("U001", "C001")
        sm.update_purchase_staging(sid, supplier_name="A", total_amount=100)
        # 進入修改模式
        _run(handle_text(self.line_svc, f"修改 #{sid}",
                         "C001", "U001", "User", "RT001"))
        # 修改供應商
        result = _run(handle_text(self.line_svc, "供應商=好鮮水產行",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("好鮮水產行", result)
        staging = sm.get_staging(sid)
        self.assertEqual(staging["supplier_name"], "好鮮水產行")

    def test_edit_total(self):
        import state_manager as sm
        from handlers.command_handler import handle_text
        sid = sm.add_purchase_staging("U001", "C001")
        sm.update_purchase_staging(sid, total_amount=100)
        _run(handle_text(self.line_svc, f"修改 #{sid}",
                         "C001", "U001", "User", "RT001"))
        result = _run(handle_text(self.line_svc, "總額=10500",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("10,500", result)
        staging = sm.get_staging(sid)
        self.assertEqual(staging["total_amount"], 10500)

    def test_edit_date(self):
        import state_manager as sm
        from handlers.command_handler import handle_text
        sid = sm.add_purchase_staging("U001", "C001")
        sm.update_purchase_staging(sid, total_amount=100)
        _run(handle_text(self.line_svc, f"修改 #{sid}",
                         "C001", "U001", "User", "RT001"))
        result = _run(handle_text(self.line_svc, "日期=2026-03-20",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("2026-03-20", result)

    def test_confirm_from_edit(self):
        """在修改模式中直接回覆「同意」→ 進入最終確認"""
        import state_manager as sm
        from handlers.command_handler import handle_text
        sid = sm.add_purchase_staging("U001", "C001")
        sm.update_purchase_staging(sid, total_amount=100)
        _run(handle_text(self.line_svc, f"修改 #{sid}",
                         "C001", "U001", "User", "RT001"))
        result = _run(handle_text(self.line_svc, "同意",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("最終確認", result)
        state, _ = sm.get_state("C001")
        self.assertEqual(state, "waiting_final_confirm")

    def test_edit_unrecognized_input(self):
        """LLM 不可用時，無法辨識的輸入應提示使用者"""
        import state_manager as sm
        from handlers.command_handler import handle_text
        sid = sm.add_purchase_staging("U001", "C001")
        sm.update_purchase_staging(sid, total_amount=100)
        _run(handle_text(self.line_svc, f"修改 #{sid}",
                         "C001", "U001", "User", "RT001"))
        result = _run(handle_text(self.line_svc, "隨便打的",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("不太確定", result)


class TestStateMachine(unittest.TestCase):
    """狀態機流程測試"""

    def setUp(self):
        self.db_path = _setup_db()
        self.line_svc = MagicMock()

    def tearDown(self):
        _teardown_db(self.db_path)

    def test_handler_response_flow(self):
        """經手人回應流程（二次確認）"""
        import state_manager as sm
        from handlers.command_handler import handle_text

        s_id = sm.upsert_supplier("菜市場阿嬤", has_invoice=False)
        sid = sm.add_purchase_staging("U001", "C001")
        sm.update_purchase_staging(sid, supplier_id=s_id, supplier_name="菜市場阿嬤",
                                   total_amount=1000, year_month="2026-03")

        # 觸發經手人流程
        _run(handle_text(self.line_svc, f"確認 #{sid}", "C001", "U001", "User", "RT001"))
        state, data = sm.get_state("C001")
        self.assertEqual(state, "waiting_handler")

        # 輸入經手人 → now triggers two-step confirm (final confirm prompt)
        result = _run(handle_text(self.line_svc, "王小美", "C001", "U001", "User", "RT001"))
        self.assertIn("王小美", result)
        self.assertIn("最終確認", result)
        state, _ = sm.get_state("C001")
        self.assertEqual(state, "waiting_final_confirm")

        # 最終確認 → actually archives
        result2 = _run(handle_text(self.line_svc, "最終確認", "C001", "U001", "User", "RT001"))
        self.assertIn("已確認", result2)
        staging = sm.get_staging(sid)
        self.assertEqual(staging["status"], "confirmed")

    def test_supplier_response_flow(self):
        """供應商名稱回應流程"""
        import state_manager as sm
        from handlers.command_handler import handle_text

        sid = sm.add_purchase_staging("U001", "C001")
        sm.set_state("C001", "waiting_supplier", {"staging_id": sid})

        result = _run(handle_text(self.line_svc, "好鮮水產行",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("好鮮水產行", result)
        staging = sm.get_staging(sid)
        self.assertEqual(staging["supplier_name"], "好鮮水產行")

    def test_confirm_response_confirm(self):
        """確認狀態 → 回覆「確認」→ 二次確認流程"""
        import state_manager as sm
        from handlers.command_handler import handle_text

        sid = sm.add_purchase_staging("U001", "C001")
        sm.update_purchase_staging(sid, supplier_name="A", total_amount=100,
                                   year_month="2026-03")
        sm.set_state("C001", "waiting_confirm", {"staging_id": sid})

        # Step 1: "確認" now shows final confirm prompt (two-step)
        result = _run(handle_text(self.line_svc, "確認",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("最終確認", result)
        state, _ = sm.get_state("C001")
        self.assertEqual(state, "waiting_final_confirm")

        # Step 2: "最終確認" → actually archives
        result2 = _run(handle_text(self.line_svc, "最終確認",
                                   "C001", "U001", "User", "RT001"))
        self.assertIn("已確認", result2)

    def test_confirm_response_discard(self):
        """確認狀態 → 回覆「捨棄」"""
        import state_manager as sm
        from handlers.command_handler import handle_text

        sid = sm.add_purchase_staging("U001", "C001")
        sm.set_state("C001", "waiting_confirm", {"staging_id": sid})

        result = _run(handle_text(self.line_svc, "捨棄",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("已捨棄", result)

    def test_confirm_response_invalid(self):
        """確認狀態 → 回覆其他"""
        import state_manager as sm
        from handlers.command_handler import handle_text

        sid = sm.add_purchase_staging("U001", "C001")
        sm.set_state("C001", "waiting_confirm", {"staging_id": sid})

        result = _run(handle_text(self.line_svc, "不知道",
                                  "C001", "U001", "User", "RT001"))
        self.assertIn("確認", result)
        self.assertIn("捨棄", result)


class TestExportCommand(unittest.TestCase):
    """匯出指令"""

    def setUp(self):
        self.db_path = _setup_db()
        self.line_svc = MagicMock()

    def tearDown(self):
        _teardown_db(self.db_path)

    @patch("handlers.command_handler.sm")
    def test_export_regex_match(self, mock_sm):
        """匯出 1-2月 格式匹配"""
        import re
        text = "匯出 1-2月"
        m = re.match(r"匯出\s*(\d{1,2})-(\d{1,2})月?", text)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "1")
        self.assertEqual(m.group(2), "2")

    @patch("handlers.command_handler.sm")
    def test_export_regex_no_month_suffix(self, mock_sm):
        """匯出 3-4 格式匹配"""
        import re
        text = "匯出 3-4"
        m = re.match(r"匯出\s*(\d{1,2})-(\d{1,2})月?", text)
        self.assertIsNotNone(m)


class TestHelp(unittest.TestCase):
    """使用說明"""

    def test_contains_all_sections(self):
        from handlers.command_handler import _show_help
        help_text = _show_help()
        self.assertIn("拍照記帳", help_text)
        self.assertIn("採購管理", help_text)
        self.assertIn("統計查詢", help_text)
        self.assertIn("供應商", help_text)
        self.assertIn("匯出", help_text)


if __name__ == "__main__":
    unittest.main()
