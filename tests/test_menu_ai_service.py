"""menu_ai_service.py 單元測試 — Gemini 呼叫 + 菜單覈對 + 成本估算"""

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Ensure state_manager is importable (it has local imports in estimate_dish_cost)
# We pre-import it so patches can work on the module level
import state_manager  # noqa: F401


# ---------------------------------------------------------------------------
# TestCallGemini — 底層 API 呼叫
# ---------------------------------------------------------------------------
class TestCallGemini(unittest.TestCase):

    @patch("services.menu_ai_service.GEMINI_API_KEY", "test-key-123")
    @patch("services.menu_ai_service.requests.post")
    def test_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "hello world"}]}}]
        }
        mock_post.return_value = mock_resp

        from services.menu_ai_service import _call_gemini
        result = _call_gemini("test prompt")
        self.assertEqual(result, "hello world")

    @patch("services.menu_ai_service.GEMINI_API_KEY", "test-key-123")
    @patch("services.menu_ai_service.requests.post")
    def test_api_error_500(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal server error"
        mock_post.return_value = mock_resp

        from services.menu_ai_service import _call_gemini
        result = _call_gemini("test prompt")
        self.assertIsNone(result)

    @patch("services.menu_ai_service.GEMINI_API_KEY", "")
    def test_no_api_key(self):
        from services.menu_ai_service import _call_gemini
        result = _call_gemini("test prompt")
        self.assertIsNone(result)

    @patch("services.menu_ai_service.GEMINI_API_KEY", "test-key-123")
    @patch("services.menu_ai_service.requests.post", side_effect=Exception("timeout"))
    def test_network_exception(self, mock_post):
        from services.menu_ai_service import _call_gemini
        result = _call_gemini("test prompt")
        self.assertIsNone(result)

    @patch("services.menu_ai_service.GEMINI_API_KEY", "test-key-123")
    @patch("services.menu_ai_service.requests.post")
    def test_json_mode_sets_mime_type(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "{}"}]}}]
        }
        mock_post.return_value = mock_resp

        from services.menu_ai_service import _call_gemini
        _call_gemini("test", json_mode=True)

        call_kwargs = mock_post.call_args
        body = call_kwargs.kwargs["json"]
        self.assertEqual(
            body["generationConfig"]["responseMimeType"],
            "application/json",
        )

    @patch("services.menu_ai_service.GEMINI_API_KEY", "test-key-123")
    @patch("services.menu_ai_service.requests.post")
    def test_non_json_mode_no_mime(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "hi"}]}}]
        }
        mock_post.return_value = mock_resp

        from services.menu_ai_service import _call_gemini
        _call_gemini("test", json_mode=False)

        call_kwargs = mock_post.call_args
        body = call_kwargs.kwargs["json"]
        self.assertNotIn("responseMimeType", body["generationConfig"])


# ---------------------------------------------------------------------------
# TestReviewMenu — 菜單覈對
# ---------------------------------------------------------------------------
class TestReviewMenu(unittest.TestCase):

    @patch("services.menu_ai_service._call_gemini")
    def test_valid_json_response(self, mock_gemini):
        review_result = {
            "overall_score": 85,
            "summary": "整體不錯",
            "issues": [{"day": "週三", "issue": "重複", "suggestion": "換菜"}],
            "nutrition_notes": "缺鈣",
            "cost_estimate": {
                "per_person_per_day": 65,
                "total_weekly": 9100,
                "over_budget": False,
            },
        }
        mock_gemini.return_value = json.dumps(review_result, ensure_ascii=False)

        from services.menu_ai_service import review_menu
        result = review_menu([{"day": "週一", "dishes": ["紅燒肉"]}])
        self.assertEqual(result["overall_score"], 85)
        self.assertEqual(len(result["issues"]), 1)
        self.assertFalse(result["cost_estimate"]["over_budget"])

    @patch("services.menu_ai_service._call_gemini")
    def test_malformed_json_response(self, mock_gemini):
        mock_gemini.return_value = "This is not valid JSON at all"

        from services.menu_ai_service import review_menu
        result = review_menu([{"day": "週一", "dishes": ["紅燒肉"]}])
        self.assertEqual(result["overall_score"], 0)
        self.assertIn("not valid JSON", result["summary"])

    @patch("services.menu_ai_service._call_gemini", return_value=None)
    def test_gemini_returns_none(self, mock_gemini):
        from services.menu_ai_service import review_menu
        result = review_menu([])
        self.assertEqual(result["overall_score"], 0)
        self.assertIn("暫時無法使用", result["summary"])


# ---------------------------------------------------------------------------
# TestGenerateDishDescription — 菜色描述
# ---------------------------------------------------------------------------
class TestGenerateDishDescription(unittest.TestCase):

    @patch("services.menu_ai_service._call_gemini")
    def test_valid_response(self, mock_gemini):
        desc_result = {
            "dish_name": "紅燒肉",
            "description": "傳統滬式紅燒肉",
            "ingredients": ["五花肉", "醬油", "冰糖"],
            "cooking_method": "紅燒",
            "marketing_copy": "入口即化的經典美味",
            "plating_suggestion": "白飯搭配",
        }
        mock_gemini.return_value = json.dumps(desc_result, ensure_ascii=False)

        from services.menu_ai_service import generate_dish_description
        result = generate_dish_description("紅燒肉")
        self.assertEqual(result["dish_name"], "紅燒肉")
        self.assertEqual(len(result["ingredients"]), 3)
        self.assertIn("紅燒", result["cooking_method"])

    @patch("services.menu_ai_service._call_gemini")
    def test_malformed_json_fallback(self, mock_gemini):
        mock_gemini.return_value = "紅燒肉是好吃的菜"

        from services.menu_ai_service import generate_dish_description
        result = generate_dish_description("紅燒肉")
        self.assertEqual(result["dish_name"], "紅燒肉")
        self.assertEqual(result["description"], "紅燒肉是好吃的菜")
        self.assertEqual(result["ingredients"], [])

    @patch("services.menu_ai_service._call_gemini", return_value=None)
    def test_ai_unavailable(self, mock_gemini):
        from services.menu_ai_service import generate_dish_description
        result = generate_dish_description("宮保雞丁")
        self.assertEqual(result["dish_name"], "宮保雞丁")
        self.assertIn("暫時無法使用", result["description"])


# ---------------------------------------------------------------------------
# TestEstimateDishCost — 成本估算（DB vs AI）
# ---------------------------------------------------------------------------
class TestEstimateDishCost(unittest.TestCase):
    """estimate_dish_cost uses `import state_manager as sm` locally.
    We don't need to mock sm for the ingredients_info path since it doesn't
    call any sm functions in that branch. For the AI path, sm is imported
    but not called either."""

    def test_with_ingredients_info(self):
        """有配方資料 => 直接計算，不呼叫 AI"""
        ingredients_info = [
            {"ingredient_name": "五花肉", "quantity": 10, "current_price": 120, "unit": "斤"},
            {"ingredient_name": "醬油", "quantity": 2, "current_price": 35, "unit": "瓶"},
        ]

        from services.menu_ai_service import estimate_dish_cost
        result = estimate_dish_cost("紅燒肉", ingredients_info)
        self.assertEqual(result["source"], "database")
        self.assertEqual(result["total_cost"], round(10 * 120 + 2 * 35, 0))
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0]["name"], "五花肉")

    def test_with_zero_quantity(self):
        """quantity or price is 0 => cost = 0"""
        ingredients_info = [
            {"ingredient_name": "鹽", "quantity": 0, "current_price": 20, "unit": "包"},
        ]

        from services.menu_ai_service import estimate_dish_cost
        result = estimate_dish_cost("鹽焗雞", ingredients_info)
        self.assertEqual(result["total_cost"], 0)
        self.assertEqual(result["items"][0]["cost"], 0)

    def test_with_none_values(self):
        """None quantity/price should be treated as 0"""
        ingredients_info = [
            {"ingredient_name": "糖", "quantity": None, "current_price": None, "unit": "包"},
        ]

        from services.menu_ai_service import estimate_dish_cost
        result = estimate_dish_cost("糖醋排骨", ingredients_info)
        self.assertEqual(result["total_cost"], 0)

    def test_with_name_fallback_key(self):
        """ingredient uses 'name' key instead of 'ingredient_name'"""
        ingredients_info = [
            {"name": "蒜頭", "quantity": 3, "current_price": 50, "unit": "斤"},
        ]

        from services.menu_ai_service import estimate_dish_cost
        result = estimate_dish_cost("蒜泥白肉", ingredients_info)
        self.assertEqual(result["items"][0]["name"], "蒜頭")
        self.assertEqual(result["items"][0]["cost"], 150)

    @patch("services.menu_ai_service._call_gemini")
    def test_ai_fallback_success(self, mock_gemini):
        """無配方 => AI 估算"""
        ai_result = {
            "dish_name": "宮保雞丁",
            "total_cost": 850,
            "cost_per_serving": 8.5,
            "items": [
                {"name": "雞胸肉", "quantity": 5, "unit": "斤",
                 "unit_price": 80, "cost": 400},
            ],
            "notes": "使用冷凍雞胸較便宜",
        }
        mock_gemini.return_value = json.dumps(ai_result, ensure_ascii=False)

        from services.menu_ai_service import estimate_dish_cost
        result = estimate_dish_cost("宮保雞丁")
        self.assertEqual(result["source"], "ai_estimate")
        self.assertEqual(result["total_cost"], 850)

    @patch("services.menu_ai_service._call_gemini", return_value=None)
    def test_ai_fallback_error(self, mock_gemini):
        from services.menu_ai_service import estimate_dish_cost
        result = estimate_dish_cost("未知菜")
        self.assertEqual(result["source"], "error")
        self.assertEqual(result["total_cost"], 0)

    @patch("services.menu_ai_service._call_gemini")
    def test_ai_malformed_json(self, mock_gemini):
        mock_gemini.return_value = "not json"

        from services.menu_ai_service import estimate_dish_cost
        result = estimate_dish_cost("隨便菜")
        self.assertEqual(result["source"], "error")


# ---------------------------------------------------------------------------
# TestSuggestAlternatives — 替代菜色建議
# ---------------------------------------------------------------------------
class TestSuggestAlternatives(unittest.TestCase):

    @patch("services.menu_ai_service._call_gemini")
    def test_valid_response(self, mock_gemini):
        alternatives = [
            {"name": "滷肉", "reason": "成本低", "estimated_cost_pct": "低 30%"},
            {"name": "燉肉", "reason": "相似口味", "estimated_cost_pct": "低 20%"},
            {"name": "雞腿排", "reason": "蛋白質相當", "estimated_cost_pct": "低 15%"},
        ]
        mock_gemini.return_value = json.dumps(alternatives, ensure_ascii=False)

        from services.menu_ai_service import suggest_alternatives
        result = suggest_alternatives("紅燒肉", reason="cost")
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["name"], "滷肉")

    @patch("services.menu_ai_service._call_gemini", return_value=None)
    def test_ai_unavailable(self, mock_gemini):
        from services.menu_ai_service import suggest_alternatives
        result = suggest_alternatives("紅燒肉")
        self.assertEqual(result, [])

    @patch("services.menu_ai_service._call_gemini")
    def test_malformed_json(self, mock_gemini):
        mock_gemini.return_value = "Here are some alternatives..."

        from services.menu_ai_service import suggest_alternatives
        result = suggest_alternatives("紅燒肉")
        self.assertEqual(result, [])

    @patch("services.menu_ai_service._call_gemini")
    def test_reason_supply(self, mock_gemini):
        """reason='supply' should produce different prompt text"""
        mock_gemini.return_value = "[]"

        from services.menu_ai_service import suggest_alternatives
        suggest_alternatives("紅燒肉", reason="supply")
        prompt = mock_gemini.call_args[0][0]
        self.assertIn("食材不足", prompt)

    @patch("services.menu_ai_service._call_gemini")
    def test_custom_reason(self, mock_gemini):
        mock_gemini.return_value = "[]"

        from services.menu_ai_service import suggest_alternatives
        suggest_alternatives("紅燒肉", reason="季節限定")
        prompt = mock_gemini.call_args[0][0]
        self.assertIn("季節限定", prompt)


# ---------------------------------------------------------------------------
# TestAnalyzeDishPhoto — 菜色照片分析 (Stage 1)
# ---------------------------------------------------------------------------
class TestAnalyzeDishPhoto(unittest.TestCase):

    @patch("services.menu_ai_service._call_gemini_multimodal")
    def test_valid_analysis(self, mock_mm):
        analysis = {
            "dish_name": "宮保雞丁",
            "ingredients": ["雞丁", "花生", "辣椒"],
            "style": "川菜",
            "color_tone": "紅棕暖色",
            "plating_assessment": "擺盤整潔",
            "improvement_suggestions": "可加蔥花點綴",
            "background_suggestion": "深色木板",
        }
        mock_mm.return_value = json.dumps(analysis, ensure_ascii=False)

        from services.menu_ai_service import analyze_dish_photo
        result = analyze_dish_photo(b"fake_image_bytes")
        self.assertEqual(result["dish_name"], "宮保雞丁")
        self.assertEqual(len(result["ingredients"]), 3)
        self.assertEqual(result["style"], "川菜")

    @patch("services.menu_ai_service._call_gemini_multimodal", return_value=None)
    def test_api_failure(self, mock_mm):
        from services.menu_ai_service import analyze_dish_photo
        result = analyze_dish_photo(b"fake")
        self.assertEqual(result["dish_name"], "未識別菜色")

    @patch("services.menu_ai_service._call_gemini_multimodal")
    def test_malformed_json(self, mock_mm):
        mock_mm.return_value = "This is not JSON"
        from services.menu_ai_service import analyze_dish_photo
        result = analyze_dish_photo(b"fake")
        self.assertEqual(result["dish_name"], "未識別菜色")
        self.assertIn("This is not JSON", result["style"])


# ---------------------------------------------------------------------------
# TestGenerateEnhancedDishPrompt — Stage 2: 增強 prompt
# ---------------------------------------------------------------------------
class TestGenerateEnhancedDishPrompt(unittest.TestCase):

    def test_prompt_contains_dish_info(self):
        from services.menu_ai_service import generate_enhanced_dish_prompt
        analysis = {
            "dish_name": "三杯雞",
            "ingredients": ["雞腿", "九層塔", "麻油"],
            "style": "台式",
            "color_tone": "深棕色",
            "background_suggestion": "dark wooden table",
        }
        prompt = generate_enhanced_dish_prompt(analysis)
        self.assertIn("三杯雞", prompt)
        self.assertIn("雞腿", prompt)
        self.assertIn("Studio lighting", prompt)
        self.assertIn("dark wooden table", prompt)

    def test_prompt_with_empty_analysis(self):
        from services.menu_ai_service import generate_enhanced_dish_prompt
        prompt = generate_enhanced_dish_prompt({})
        # Should not crash, should contain default text
        self.assertIn("Professional food photography", prompt)


# ---------------------------------------------------------------------------
# TestGenerateMarketingCopy — Stage 3: 行銷文案
# ---------------------------------------------------------------------------
class TestGenerateMarketingCopy(unittest.TestCase):

    @patch("services.menu_ai_service._call_gemini")
    def test_valid_copy(self, mock_gemini):
        copy_result = {
            "tagline": "一口入魂的幸福味",
            "copy": "嚴選在地食材，以慢火精燉出的經典美味",
            "hashtags": ["#美食", "#台灣味", "#宮保雞丁"],
        }
        mock_gemini.return_value = json.dumps(copy_result, ensure_ascii=False)

        from services.menu_ai_service import generate_marketing_copy
        result = generate_marketing_copy({"dish_name": "宮保雞丁"})
        self.assertEqual(result["tagline"], "一口入魂的幸福味")
        self.assertEqual(len(result["hashtags"]), 3)

    @patch("services.menu_ai_service._call_gemini", return_value=None)
    def test_api_failure(self, mock_gemini):
        from services.menu_ai_service import generate_marketing_copy
        result = generate_marketing_copy({"dish_name": "紅燒肉"})
        self.assertEqual(result["tagline"], "紅燒肉")
        self.assertIn("暫時無法使用", result["copy"])


# ---------------------------------------------------------------------------
# TestCallImagenApi — 圖片生成 API
# ---------------------------------------------------------------------------
class TestCallImagenApi(unittest.TestCase):

    @patch("services.menu_ai_service.GEMINI_API_KEY", "test-key")
    @patch("services.menu_ai_service.requests.post")
    def test_success(self, mock_post):
        import base64
        fake_img = base64.b64encode(b"PNG_DATA").decode()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "predictions": [{"bytesBase64Encoded": fake_img, "mimeType": "image/png"}]
        }
        mock_post.return_value = mock_resp

        from services.menu_ai_service import _call_imagen_api
        result = _call_imagen_api("test prompt")
        self.assertEqual(result, b"PNG_DATA")

    @patch("services.menu_ai_service.GEMINI_API_KEY", "test-key")
    @patch("services.menu_ai_service.requests.post")
    def test_api_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "error"
        mock_post.return_value = mock_resp

        from services.menu_ai_service import _call_imagen_api
        result = _call_imagen_api("test prompt")
        self.assertIsNone(result)

    @patch("services.menu_ai_service.GEMINI_API_KEY", "")
    def test_no_api_key(self):
        from services.menu_ai_service import _call_imagen_api
        result = _call_imagen_api("test prompt")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# TestCallGeminiMultimodal — 多模態 API
# ---------------------------------------------------------------------------
class TestCallGeminiMultimodal(unittest.TestCase):

    @patch("services.menu_ai_service.GEMINI_API_KEY", "test-key-123")
    @patch("services.menu_ai_service.requests.post")
    def test_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": '{"dish_name":"test"}'}]}}]
        }
        mock_post.return_value = mock_resp

        from services.menu_ai_service import _call_gemini_multimodal
        result = _call_gemini_multimodal("prompt", b"image_bytes")
        self.assertIn("dish_name", result)

        # Verify image was sent
        call_body = mock_post.call_args.kwargs["json"]
        parts = call_body["contents"][0]["parts"]
        self.assertEqual(len(parts), 2)
        self.assertIn("inlineData", parts[1])

    @patch("services.menu_ai_service.GEMINI_API_KEY", "")
    def test_no_api_key(self):
        from services.menu_ai_service import _call_gemini_multimodal
        result = _call_gemini_multimodal("prompt", b"image")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
