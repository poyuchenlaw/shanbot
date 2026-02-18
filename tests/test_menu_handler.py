"""menu_handler.py 單元測試 — 菜單編輯 / 菜色命名 / 成本試算 / 格式化"""

import asyncio
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _run(coro):
    """同步執行 coroutine"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# TestMenuEdit — 菜單編輯解析
# ---------------------------------------------------------------------------
class TestMenuEdit(unittest.TestCase):

    @patch("handlers.menu_handler.sm")
    def test_parse_standard_format(self, mock_sm):
        """'週一午：紅燒肉、炒青菜' => 解析成功"""
        mock_sm.get_all_recipes.return_value = []
        mock_sm.add_menu_schedule.return_value = 1

        from handlers.menu_handler import handle_menu_edit
        result = _run(handle_menu_edit(None, "週一午：紅燒肉、炒青菜", "g1", {}))
        self.assertIn("週一", result)
        self.assertIn("午餐已更新", result)
        self.assertIn("紅燒肉", result)
        self.assertIn("炒青菜", result)
        self.assertEqual(mock_sm.add_menu_schedule.call_count, 2)

    @patch("handlers.menu_handler.sm")
    def test_parse_with_colon_variant(self, mock_sm):
        """半形冒號也能解析"""
        mock_sm.get_all_recipes.return_value = []
        mock_sm.add_menu_schedule.return_value = 1

        from handlers.menu_handler import handle_menu_edit
        result = _run(handle_menu_edit(None, "週三午:滷肉飯、味噌湯", "g1", {}))
        self.assertIn("週三", result)
        self.assertIn("滷肉飯", result)

    @patch("handlers.menu_handler.sm")
    def test_parse_dinner(self, mock_sm):
        """'週五晚：' => meal_type = dinner"""
        mock_sm.get_all_recipes.return_value = []
        mock_sm.add_menu_schedule.return_value = 1

        from handlers.menu_handler import handle_menu_edit
        result = _run(handle_menu_edit(None, "週五晚：牛肉麵", "g1", {}))
        self.assertIn("週五", result)
        self.assertIn("晚餐已更新", result)
        # Verify meal_type argument
        call_kwargs = mock_sm.add_menu_schedule.call_args
        self.assertEqual(call_kwargs.kwargs.get("meal_type", call_kwargs[1].get("meal_type", "")), "dinner")

    @patch("handlers.menu_handler.sm")
    def test_parse_default_lunch(self, mock_sm):
        """省略午/晚 => 預設午餐"""
        mock_sm.get_all_recipes.return_value = []
        mock_sm.add_menu_schedule.return_value = 1

        from handlers.menu_handler import handle_menu_edit
        result = _run(handle_menu_edit(None, "週二：燒鴨、炒麵", "g1", {}))
        self.assertIn("週二", result)
        self.assertIn("午餐已更新", result)

    @patch("handlers.menu_handler.sm")
    def test_invalid_format(self, mock_sm):
        """不合格式 => 提示訊息"""
        from handlers.menu_handler import handle_menu_edit
        result = _run(handle_menu_edit(None, "隨便打的文字", "g1", {}))
        self.assertIn("格式不正確", result)

    @patch("handlers.menu_handler.sm")
    def test_finish_keyword(self, mock_sm):
        """'完成菜單' => 清除狀態，結束"""
        from handlers.menu_handler import handle_menu_edit
        result = _run(handle_menu_edit(None, "完成菜單", "g1", {}))
        self.assertIn("菜單編輯完成", result)
        mock_sm.clear_state.assert_called_once_with("g1")

    @patch("handlers.menu_handler.sm")
    def test_finish_keyword_short(self, mock_sm):
        """'完成' 也能結束"""
        from handlers.menu_handler import handle_menu_edit
        result = _run(handle_menu_edit(None, "完成", "g1", {}))
        self.assertIn("菜單編輯完成", result)

    @patch("handlers.menu_handler.sm")
    def test_finish_keyword_end(self, mock_sm):
        """'結束' 也能結束"""
        from handlers.menu_handler import handle_menu_edit
        result = _run(handle_menu_edit(None, "結束", "g1", {}))
        self.assertIn("菜單編輯完成", result)

    @patch("handlers.menu_handler.sm")
    def test_recipe_match(self, mock_sm):
        """已知配方 => recipe_id 非 None"""
        mock_sm.get_all_recipes.return_value = [
            {"id": 42, "name": "紅燒肉"},
        ]
        mock_sm.add_menu_schedule.return_value = 1

        from handlers.menu_handler import handle_menu_edit
        _run(handle_menu_edit(None, "週一午：紅燒肉", "g1", {}))

        call_args = mock_sm.add_menu_schedule.call_args
        # recipe_id should be 42
        self.assertEqual(call_args[1].get("recipe_id") or call_args[0][2] if len(call_args[0]) > 2 else call_args.kwargs.get("recipe_id"), 42)

    @patch("handlers.menu_handler.sm")
    def test_comma_separator_chinese(self, mock_sm):
        """中文逗號也能分隔菜色"""
        mock_sm.get_all_recipes.return_value = []
        mock_sm.add_menu_schedule.return_value = 1

        from handlers.menu_handler import handle_menu_edit
        result = _run(handle_menu_edit(None, "週四午：魚排，炒青菜，紫菜湯", "g1", {}))
        self.assertEqual(mock_sm.add_menu_schedule.call_count, 3)


# ---------------------------------------------------------------------------
# TestDishName — 菜色命名 / 描述
# ---------------------------------------------------------------------------
class TestDishName(unittest.TestCase):

    @patch("handlers.menu_handler.sm")
    @patch("handlers.menu_handler.generate_dish_description", create=True)
    def test_valid_dish_name(self, mock_desc, mock_sm):
        """正常菜名 => 回傳 None（push 模式）"""
        mock_desc_module = MagicMock()
        mock_desc_module.return_value = {
            "description": "經典家常菜",
            "marketing_copy": "媽媽的味道",
            "ingredients": ["高麗菜", "蒜頭"],
            "cooking_method": "快炒",
        }

        with patch("services.menu_ai_service.generate_dish_description",
                    mock_desc_module):
            from handlers.menu_handler import handle_dish_name
            result = _run(handle_dish_name(None, "炒高麗菜", "g1", {}))

        # Now returns None (uses push instead of return)
        self.assertIsNone(result)
        mock_sm.clear_state.assert_called()

    @patch("handlers.menu_handler.sm")
    def test_too_long_name(self, mock_sm):
        """超過 20 字 => 提示"""
        from handlers.menu_handler import handle_dish_name
        result = _run(handle_dish_name(None, "這是一道非常長的菜名超過二十個字真的太長了吧", "g1", {}))
        self.assertIn("1-20 字", result)

    @patch("handlers.menu_handler.sm")
    def test_empty_name(self, mock_sm):
        """空字串 => 提示"""
        from handlers.menu_handler import handle_dish_name
        result = _run(handle_dish_name(None, "", "g1", {}))
        self.assertIn("1-20 字", result)

    @patch("handlers.menu_handler.sm")
    def test_whitespace_only(self, mock_sm):
        """純空白 => 提示"""
        from handlers.menu_handler import handle_dish_name
        result = _run(handle_dish_name(None, "   ", "g1", {}))
        self.assertIn("1-20 字", result)

    @patch("handlers.menu_handler.sm")
    def test_ai_error_fallback(self, mock_sm):
        """AI 出錯 => 回傳 None（push fallback）"""
        with patch("services.menu_ai_service.generate_dish_description",
                    side_effect=Exception("API down")):
            from handlers.menu_handler import handle_dish_name
            result = _run(handle_dish_name(None, "紅燒肉", "g1", {}))

        # Returns None (push mode fallback)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# TestCostInput — 成本試算入口
# ---------------------------------------------------------------------------
class TestCostInput(unittest.TestCase):

    @patch("handlers.menu_handler.sm")
    def test_empty_input(self, mock_sm):
        from handlers.menu_handler import handle_cost_input
        result = _run(handle_cost_input(None, "", "g1", {}))
        self.assertIn("請輸入菜名", result)

    @patch("handlers.menu_handler.sm")
    def test_known_recipe_with_bom(self, mock_sm):
        """DB 有配方 + BOM => 直接計算"""
        mock_sm.get_all_recipes.return_value = [{"id": 10, "name": "紅燒肉"}]
        mock_sm.get_recipe_bom.return_value = [
            {"ingredient_name": "五花肉", "quantity": 10,
             "current_price": 100, "unit": "斤"},
        ]

        with patch("services.menu_ai_service.estimate_dish_cost") as mock_cost:
            mock_cost.return_value = {
                "dish_name": "紅燒肉",
                "total_cost": 1000,
                "items": [{"name": "五花肉", "quantity": 10, "unit": "斤",
                           "unit_price": 100, "cost": 1000}],
                "source": "database",
            }
            from handlers.menu_handler import handle_cost_input
            result = _run(handle_cost_input(None, "紅燒肉", "g1", {}))

        self.assertIn("紅燒肉", result)
        self.assertIn("1,000", result)

    @patch("handlers.menu_handler.sm")
    def test_unknown_dish_ai_fallback(self, mock_sm):
        """DB 無配方 => AI 估算"""
        mock_sm.get_all_recipes.return_value = []

        with patch("services.menu_ai_service.estimate_dish_cost") as mock_cost:
            mock_cost.return_value = {
                "dish_name": "隨便菜",
                "total_cost": 500,
                "items": [],
                "source": "ai_estimate",
            }
            from handlers.menu_handler import handle_cost_input
            result = _run(handle_cost_input(None, "隨便菜", "g1", {}))

        self.assertIn("AI 估算", result)

    @patch("handlers.menu_handler.sm")
    def test_ai_exception(self, mock_sm):
        """AI 也出錯 => fallback 訊息"""
        mock_sm.get_all_recipes.return_value = []

        with patch("services.menu_ai_service.estimate_dish_cost",
                    side_effect=Exception("boom")):
            from handlers.menu_handler import handle_cost_input
            result = _run(handle_cost_input(None, "爆炸菜", "g1", {}))

        self.assertIn("暫時無法使用", result)


# ---------------------------------------------------------------------------
# TestFormatCostResult — 成本結果格式化
# ---------------------------------------------------------------------------
class TestFormatCostResult(unittest.TestCase):

    def test_with_items(self):
        from handlers.menu_handler import _format_cost_result
        result = _format_cost_result({
            "dish_name": "紅燒肉",
            "total_cost": 1200,
            "items": [
                {"name": "五花肉", "quantity": 10, "unit": "斤",
                 "unit_price": 100, "cost": 1000},
                {"name": "醬油", "quantity": 2, "unit": "瓶",
                 "unit_price": 100, "cost": 200},
            ],
            "source": "database",
        })
        self.assertIn("紅燒肉", result)
        self.assertIn("食材明細", result)
        self.assertIn("五花肉", result)
        self.assertIn("1,200", result)
        self.assertIn("系統記錄", result)

    def test_without_items(self):
        from handlers.menu_handler import _format_cost_result
        result = _format_cost_result({
            "dish_name": "未知菜",
            "total_cost": 0,
            "items": [],
            "source": "error",
        })
        self.assertIn("未知菜", result)
        self.assertNotIn("食材明細", result)

    def test_ai_estimate_source(self):
        from handlers.menu_handler import _format_cost_result
        result = _format_cost_result({
            "dish_name": "宮保雞丁",
            "total_cost": 850,
            "items": [{"name": "雞肉", "quantity": 5, "unit": "斤",
                        "unit_price": 80, "cost": 400}],
            "source": "ai_estimate",
        })
        self.assertIn("AI 估算", result)

    def test_with_notes(self):
        from handlers.menu_handler import _format_cost_result
        result = _format_cost_result({
            "dish_name": "Test",
            "total_cost": 100,
            "items": [],
            "source": "ai_estimate",
            "notes": "建議使用冷凍肉",
        })
        self.assertIn("建議使用冷凍肉", result)

    def test_no_notes_no_source(self):
        from handlers.menu_handler import _format_cost_result
        result = _format_cost_result({
            "dish_name": "Simple",
            "total_cost": 50,
            "items": [],
            "source": "",
        })
        self.assertNotIn("AI 估算", result)
        self.assertNotIn("系統記錄", result)

    def test_items_capped_at_10(self):
        """超過 10 項只顯示前 10"""
        from handlers.menu_handler import _format_cost_result
        items = [{"name": f"食材{i}", "quantity": 1, "unit": "kg",
                  "unit_price": 10, "cost": 10} for i in range(15)]
        result = _format_cost_result({
            "dish_name": "大鍋菜",
            "total_cost": 150,
            "items": items,
            "source": "database",
        })
        # Count bullet points
        bullet_count = result.count("•")
        self.assertEqual(bullet_count, 10)


# ---------------------------------------------------------------------------
# TestHandleMenuPhoto — 菜色照片上傳流程
# ---------------------------------------------------------------------------
class TestHandleMenuPhoto(unittest.TestCase):

    def test_download_failure(self):
        """圖片下載失敗 → 回傳錯誤訊息"""
        mock_ls = MagicMock()
        mock_ls.get_content.return_value = None

        from handlers.menu_handler import handle_menu_photo
        result = _run(handle_menu_photo(mock_ls, "msg1", "g1", "u1", "rt1"))
        self.assertEqual(result, "❌ 圖片下載失敗，請重新上傳")

    def test_full_flow_mock(self):
        """完整流程 mock — 分析 + 增強 + 文案 → push"""
        import tempfile
        mock_ls = MagicMock()
        mock_ls.get_content.return_value = b"FAKE_IMAGE_BYTES"

        analysis = {
            "dish_name": "宮保雞丁",
            "ingredients": ["雞肉", "花生"],
            "style": "川菜",
            "color_tone": "暖色",
            "background_suggestion": "dark wood",
        }
        copy = {
            "tagline": "一口入魂",
            "copy": "經典川味",
            "hashtags": ["#美食"],
        }

        _real_os_path_join = os.path.join

        with tempfile.TemporaryDirectory() as tmpdir:
            # Redirect IMAGES_DIR to tmpdir by replacing the computed path
            fake_images_dir = tmpdir

            with patch("services.menu_ai_service.analyze_dish_photo", return_value=analysis), \
                 patch("services.menu_ai_service.generate_enhanced_dish_prompt", return_value="test prompt"), \
                 patch("services.menu_ai_service._call_imagen_api", return_value=b"ENHANCED_PNG"), \
                 patch("services.menu_ai_service.generate_marketing_copy", return_value=copy), \
                 patch("services.gdrive_service.init_folder_structure", side_effect=ImportError("no")):
                # Monkey-patch IMAGES_DIR calculation inside handle_menu_photo
                orig_dirname = os.path.dirname
                with patch.object(os.path, "dirname", side_effect=lambda p: tmpdir):
                    from handlers.menu_handler import handle_menu_photo
                    result = _run(handle_menu_photo(mock_ls, "msg1", "g1", "u1", "rt1"))

        # Should return None (push mode)
        self.assertIsNone(result)
        # Should have called reply for "processing" message
        mock_ls.reply.assert_called_once()

    def test_analysis_error_fallback(self):
        """分析失敗 → 仍應繼續流程"""
        import tempfile
        mock_ls = MagicMock()
        mock_ls.get_content.return_value = b"FAKE_IMAGE"

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("services.menu_ai_service.analyze_dish_photo", side_effect=Exception("API down")), \
                 patch("services.menu_ai_service.generate_enhanced_dish_prompt", return_value="prompt"), \
                 patch("services.menu_ai_service._call_imagen_api", return_value=None), \
                 patch("services.menu_ai_service.generate_marketing_copy", return_value={"tagline": "", "copy": "", "hashtags": []}), \
                 patch("services.gdrive_service.init_folder_structure", side_effect=ImportError("no")), \
                 patch.object(os.path, "dirname", side_effect=lambda p: tmpdir):
                from handlers.menu_handler import handle_menu_photo
                result = _run(handle_menu_photo(mock_ls, "msg1", "g1", "u1", "rt1"))

        # Should not crash
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
