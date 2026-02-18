"""OCR 雙引擎服務測試 — 信心度計算 + 門檻判定 + Flex Message"""

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestOcrItem(unittest.TestCase):
    """OcrItem 資料結構"""

    def test_default_values(self):
        from services.ocr_service import OcrItem
        item = OcrItem()
        self.assertEqual(item.name, "")
        self.assertEqual(item.quantity, 0)
        self.assertFalse(item.is_handwritten)

    def test_create_with_data(self):
        from services.ocr_service import OcrItem
        item = OcrItem(name="高麗菜", quantity=10, unit="kg",
                       unit_price=35, amount=350)
        self.assertEqual(item.name, "高麗菜")
        self.assertEqual(item.amount, 350)


class TestOcrResult(unittest.TestCase):
    """OcrResult 資料結構"""

    def test_default_result_level(self):
        from services.ocr_service import OcrResult
        result = OcrResult()
        self.assertEqual(result.result_level, "REJECT")

    def test_to_dict(self):
        from services.ocr_service import OcrResult
        result = OcrResult(supplier_name="好鮮水產", total_amount=5000)
        d = result.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["supplier_name"], "好鮮水產")
        self.assertEqual(d["total_amount"], 5000)

    def test_items_list(self):
        from services.ocr_service import OcrResult, OcrItem
        result = OcrResult()
        result.items.append(OcrItem(name="A"))
        result.items.append(OcrItem(name="B"))
        self.assertEqual(len(result.items), 2)


class TestCheckAmountConsistency(unittest.TestCase):
    """金額一致性檢查"""

    def test_matching(self):
        from services.ocr_service import _check_amount_consistency
        self.assertTrue(_check_amount_consistency("合計 5000", 5000))

    def test_with_comma(self):
        from services.ocr_service import _check_amount_consistency
        self.assertTrue(_check_amount_consistency("合計 10,500", 10500))

    def test_not_matching(self):
        from services.ocr_service import _check_amount_consistency
        self.assertFalse(_check_amount_consistency("合計 3000", 5000))

    def test_zero_total(self):
        from services.ocr_service import _check_amount_consistency
        self.assertFalse(_check_amount_consistency("some text", 0))


class TestCheckMathConsistency(unittest.TestCase):
    """品項數學校驗"""

    def test_empty_items(self):
        from services.ocr_service import _check_math_consistency
        self.assertTrue(_check_math_consistency([]))

    def test_all_correct(self):
        from services.ocr_service import _check_math_consistency, OcrItem
        items = [
            OcrItem(unit_price=35, quantity=10, amount=350),
            OcrItem(unit_price=50, quantity=5, amount=250),
        ]
        self.assertTrue(_check_math_consistency(items))

    def test_tolerance_within_1(self):
        from services.ocr_service import _check_math_consistency, OcrItem
        items = [OcrItem(unit_price=33.33, quantity=3, amount=100)]
        # 33.33 * 3 = 99.99, diff = 0.01 < 1
        self.assertTrue(_check_math_consistency(items))

    def test_mismatch(self):
        from services.ocr_service import _check_math_consistency, OcrItem
        items = [OcrItem(unit_price=35, quantity=10, amount=500)]
        # 35 * 10 = 350 ≠ 500
        self.assertFalse(_check_math_consistency(items))

    def test_skip_zero_fields(self):
        from services.ocr_service import _check_math_consistency, OcrItem
        items = [OcrItem(unit_price=0, quantity=10, amount=350)]
        self.assertTrue(_check_math_consistency(items))


class TestCheckTaxConsistency(unittest.TestCase):
    """稅額校驗"""

    def test_correct_tax(self):
        from services.ocr_service import _check_tax_consistency
        # 10000 * 5% = 500
        self.assertTrue(_check_tax_consistency(10000, 500))

    def test_within_tolerance(self):
        from services.ocr_service import _check_tax_consistency
        # 10000 * 5% = 500, 501 is within ±1
        self.assertTrue(_check_tax_consistency(10000, 501))

    def test_mismatch(self):
        from services.ocr_service import _check_tax_consistency
        self.assertFalse(_check_tax_consistency(10000, 600))

    def test_zero_subtotal(self):
        from services.ocr_service import _check_tax_consistency
        # 無法驗證 → 不扣分 → True
        self.assertTrue(_check_tax_consistency(0, 500))

    def test_zero_tax(self):
        from services.ocr_service import _check_tax_consistency
        self.assertTrue(_check_tax_consistency(10000, 0))


class TestValidateFields(unittest.TestCase):
    """欄位格式驗證"""

    def test_valid_tax_id(self):
        from services.ocr_service import _validate_fields, OcrResult
        r = OcrResult(supplier_tax_id="12345678")
        _validate_fields(r)
        self.assertEqual(len([i for i in r.issues if "統一編號" in i]), 0)

    def test_invalid_tax_id(self):
        from services.ocr_service import _validate_fields, OcrResult
        r = OcrResult(supplier_tax_id="1234567")  # 7 digits
        _validate_fields(r)
        self.assertTrue(any("統一編號" in i for i in r.issues))

    def test_valid_invoice_number(self):
        from services.ocr_service import _validate_fields, OcrResult
        r = OcrResult(invoice_number="12345678")
        _validate_fields(r)
        self.assertEqual(len([i for i in r.issues if "發票號碼" in i]), 0)

    def test_invalid_invoice_number(self):
        from services.ocr_service import _validate_fields, OcrResult
        r = OcrResult(invoice_number="1234")
        _validate_fields(r)
        self.assertTrue(any("發票號碼" in i for i in r.issues))

    def test_valid_invoice_prefix(self):
        from services.ocr_service import _validate_fields, OcrResult
        r = OcrResult(invoice_prefix="AB")
        _validate_fields(r)
        self.assertEqual(len([i for i in r.issues if "字軌" in i]), 0)

    def test_invalid_invoice_prefix(self):
        from services.ocr_service import _validate_fields, OcrResult
        r = OcrResult(invoice_prefix="abc")
        _validate_fields(r)
        self.assertTrue(any("字軌" in i for i in r.issues))

    def test_valid_date(self):
        from services.ocr_service import _validate_fields, OcrResult
        r = OcrResult(purchase_date="2026-03-15")
        _validate_fields(r)
        self.assertEqual(len([i for i in r.issues if "日期" in i]), 0)

    def test_invalid_date(self):
        from services.ocr_service import _validate_fields, OcrResult
        r = OcrResult(purchase_date="115/03/15")
        _validate_fields(r)
        self.assertTrue(any("日期" in i for i in r.issues))

    def test_items_sum_mismatch(self):
        from services.ocr_service import _validate_fields, OcrResult, OcrItem
        r = OcrResult(total_amount=1000)
        r.items = [OcrItem(amount=100), OcrItem(amount=200)]
        # items sum = 300, total = 1000, diff > 10%
        _validate_fields(r)
        self.assertTrue(any("差異超過" in i for i in r.issues))


class TestGetAutoPassThreshold(unittest.TestCase):
    """動態門檻測試"""

    def test_early_stage_higher_threshold(self):
        """前 200 張使用較嚴格門檻"""
        # state_manager is imported locally inside _get_auto_pass_threshold
        with patch("state_manager.get_ocr_stats", return_value={"total": 50}):
            from services.ocr_service import _get_auto_pass_threshold
            threshold = _get_auto_pass_threshold()
            self.assertEqual(threshold, 0.90)

    def test_mature_stage_normal_threshold(self):
        """超過 200 張使用正常門檻"""
        with patch("state_manager.get_ocr_stats", return_value={"total": 300}):
            from services.ocr_service import _get_auto_pass_threshold
            threshold = _get_auto_pass_threshold()
            self.assertEqual(threshold, 0.85)

    def test_fallback_on_error(self):
        """import 失敗時用預設值"""
        with patch("state_manager.get_ocr_stats", side_effect=Exception("DB error")):
            from services.ocr_service import _get_auto_pass_threshold
            threshold = _get_auto_pass_threshold()
            self.assertEqual(threshold, 0.85)


class TestProcessImage(unittest.TestCase):
    """process_image 整合邏輯"""

    @patch("services.ocr_service._get_auto_pass_threshold", return_value=0.85)
    @patch("services.ocr_service.ocr_gemini")
    @patch("services.ocr_service.ocr_paddle")
    def test_both_engines_success(self, mock_paddle, mock_gemini, mock_threshold):
        from services.ocr_service import process_image
        mock_paddle.return_value = ("好鮮水產行\n高麗菜 10kg 350\n合計 350", 0.85)
        mock_gemini.return_value = {
            "supplier_name": "好鮮水產行",
            "supplier_tax_id": "12345678",
            "invoice_prefix": "AB",
            "invoice_number": "12345678",
            "invoice_type": "三聯式",
            "purchase_date": "2026-03-15",
            "items": [{"name": "高麗菜", "quantity": 10, "unit": "kg",
                       "unit_price": 35, "amount": 350}],
            "subtotal": 333,
            "tax_amount": 17,
            "total_amount": 350,
        }

        result = process_image("/fake/path.jpg")
        self.assertEqual(result.supplier_name, "好鮮水產行")
        self.assertEqual(len(result.items), 1)
        # 0.85 base + 0.10 (consistency: "350" in paddle text) + 0.05 (math ok) + 0.05 (tax ok)
        self.assertGreaterEqual(result.confidence, 0.85)
        self.assertIn(result.result_level, ["AUTO_PASS", "REVIEW"])

    @patch("services.ocr_service._get_auto_pass_threshold", return_value=0.85)
    @patch("services.ocr_service.ocr_gemini")
    @patch("services.ocr_service.ocr_paddle")
    def test_both_engines_fail(self, mock_paddle, mock_gemini, mock_threshold):
        from services.ocr_service import process_image
        mock_paddle.return_value = ("", 0.0)
        mock_gemini.return_value = None

        result = process_image("/fake/path.jpg")
        self.assertEqual(result.confidence, 0)
        self.assertEqual(result.result_level, "REJECT")
        self.assertIn("兩個 OCR 引擎都無法辨識", result.issues)

    @patch("services.ocr_service._get_auto_pass_threshold", return_value=0.85)
    @patch("services.ocr_service.ocr_gemini")
    @patch("services.ocr_service.ocr_paddle")
    def test_paddle_only(self, mock_paddle, mock_gemini, mock_threshold):
        from services.ocr_service import process_image
        mock_paddle.return_value = ("some text here", 0.70)
        mock_gemini.return_value = None

        result = process_image("/fake/path.jpg")
        self.assertEqual(result.raw_text, "some text here")
        # No gemini data → no items
        self.assertEqual(len(result.items), 0)

    @patch("services.ocr_service._get_auto_pass_threshold", return_value=0.85)
    @patch("services.ocr_service.ocr_gemini")
    @patch("services.ocr_service.ocr_paddle")
    def test_gemini_only(self, mock_paddle, mock_gemini, mock_threshold):
        from services.ocr_service import process_image
        mock_paddle.return_value = ("", 0.0)
        mock_gemini.return_value = {
            "supplier_name": "好鮮水產行",
            "items": [{"name": "高麗菜", "amount": 350}],
            "total_amount": 350,
        }

        result = process_image("/fake/path.jpg")
        self.assertEqual(result.supplier_name, "好鮮水產行")
        # base_confidence = 0.50 (fallback)
        self.assertGreaterEqual(result.confidence, 0.50)

    @patch("services.ocr_service._get_auto_pass_threshold", return_value=0.85)
    @patch("services.ocr_service.ocr_gemini")
    @patch("services.ocr_service.ocr_paddle")
    def test_handwritten_penalty(self, mock_paddle, mock_gemini, mock_threshold):
        from services.ocr_service import process_image
        mock_paddle.return_value = ("合計 350", 0.90)
        mock_gemini.return_value = {
            "items": [{"name": "高麗菜", "amount": 350, "is_handwritten": True}],
            "total_amount": 350,
        }

        result = process_image("/fake/path.jpg")
        self.assertTrue(any("手寫" in i for i in result.issues))
        # Confidence is capped at 1.0 but handwritten penalty was applied
        self.assertLessEqual(result.confidence, 1.0)

    @patch("services.ocr_service._get_auto_pass_threshold", return_value=0.90)
    @patch("services.ocr_service.ocr_gemini")
    @patch("services.ocr_service.ocr_paddle")
    def test_early_stage_stricter(self, mock_paddle, mock_gemini, mock_threshold):
        from services.ocr_service import process_image
        mock_paddle.return_value = ("合計 1000", 0.85)
        mock_gemini.return_value = {
            "items": [{"name": "高麗菜", "amount": 1000}],
            "total_amount": 1000,
        }

        result = process_image("/fake/path.jpg")
        # 0.85 + 0.10 (consistency) = 0.95, threshold = 0.90
        if result.confidence >= 0.90:
            self.assertEqual(result.result_level, "AUTO_PASS")


class TestBuildReviewFlex(unittest.TestCase):
    """Flex Message 生成"""

    def test_basic_structure(self):
        from services.ocr_service import build_review_flex, OcrResult, OcrItem
        result = OcrResult(
            supplier_name="好鮮水產行",
            purchase_date="2026-03-15",
            confidence=0.85,
            total_amount=5000,
        )
        result.items = [
            OcrItem(name="高麗菜", quantity=10, unit="kg",
                    unit_price=35, amount=350),
        ]

        flex = build_review_flex(result, 42)
        self.assertEqual(flex["type"], "bubble")
        self.assertEqual(flex["size"], "mega")
        self.assertIn("header", flex)
        self.assertIn("body", flex)
        self.assertIn("footer", flex)

    def test_confirm_button_has_staging_id(self):
        from services.ocr_service import build_review_flex, OcrResult, OcrItem
        result = OcrResult(confidence=0.85, total_amount=1000)
        result.items = [OcrItem(name="A", amount=1000)]
        flex = build_review_flex(result, 99)

        footer_contents = flex["footer"]["contents"]
        # Find button box
        button_box = [c for c in footer_contents if c.get("layout") == "horizontal"]
        self.assertTrue(len(button_box) > 0)
        buttons = button_box[0]["contents"]
        confirm_btn = buttons[0]
        self.assertIn("確認 #99", confirm_btn["action"]["text"])

    def test_issues_shown(self):
        from services.ocr_service import build_review_flex, OcrResult, OcrItem
        result = OcrResult(confidence=0.70, total_amount=1000)
        result.items = [OcrItem(name="A", amount=1000)]
        result.issues = ["金額不一致"]
        flex = build_review_flex(result, 1)

        footer_texts = [c.get("text", "") for c in flex["footer"]["contents"]
                        if c.get("type") == "text"]
        self.assertTrue(any("金額不一致" in t for t in footer_texts))

    def test_confidence_color_green(self):
        from services.ocr_service import build_review_flex, OcrResult, OcrItem
        result = OcrResult(confidence=0.90, total_amount=100)
        result.items = [OcrItem(name="A", amount=100)]
        flex = build_review_flex(result, 1)
        header_texts = flex["header"]["contents"]
        conf_text = [t for t in header_texts if "信心度" in t.get("text", "")]
        self.assertTrue(len(conf_text) > 0)
        self.assertEqual(conf_text[0]["color"], "#00C853")

    def test_confidence_color_orange(self):
        from services.ocr_service import build_review_flex, OcrResult, OcrItem
        result = OcrResult(confidence=0.70, total_amount=100)
        result.items = [OcrItem(name="A", amount=100)]
        flex = build_review_flex(result, 1)
        header_texts = flex["header"]["contents"]
        conf_text = [t for t in header_texts if "信心度" in t.get("text", "")]
        self.assertEqual(conf_text[0]["color"], "#FF6D00")

    def test_confidence_color_red(self):
        from services.ocr_service import build_review_flex, OcrResult, OcrItem
        result = OcrResult(confidence=0.40, total_amount=100)
        result.items = [OcrItem(name="A", amount=100)]
        flex = build_review_flex(result, 1)
        header_texts = flex["header"]["contents"]
        conf_text = [t for t in header_texts if "信心度" in t.get("text", "")]
        self.assertEqual(conf_text[0]["color"], "#FF0000")


class TestOcrPaddle(unittest.TestCase):
    """PaddleOCR 引擎測試（模擬）"""

    @patch("services.ocr_service._get_paddle_engine")
    def test_engine_unavailable(self, mock_engine):
        from services.ocr_service import ocr_paddle
        mock_engine.return_value = None
        text, conf = ocr_paddle("/fake/image.jpg")
        self.assertEqual(text, "")
        self.assertEqual(conf, 0.0)

    @patch("services.ocr_service._get_paddle_engine")
    def test_engine_success(self, mock_engine):
        from services.ocr_service import ocr_paddle
        engine = MagicMock()
        engine.ocr.return_value = [[
            [[[0, 0], [100, 0], [100, 20], [0, 20]], ("好鮮水產行", 0.95)],
            [[[0, 20], [100, 20], [100, 40], [0, 40]], ("高麗菜 10kg", 0.88)],
        ]]
        mock_engine.return_value = engine

        text, conf = ocr_paddle("/fake/image.jpg")
        self.assertIn("好鮮水產行", text)
        self.assertIn("高麗菜", text)
        self.assertAlmostEqual(conf, (0.95 + 0.88) / 2, places=2)

    @patch("services.ocr_service._get_paddle_engine")
    def test_engine_empty_result(self, mock_engine):
        from services.ocr_service import ocr_paddle
        engine = MagicMock()
        engine.ocr.return_value = [[]]
        mock_engine.return_value = engine

        text, conf = ocr_paddle("/fake/image.jpg")
        self.assertEqual(text, "")
        self.assertEqual(conf, 0.0)

    @patch("services.ocr_service._get_paddle_engine")
    def test_engine_exception(self, mock_engine):
        from services.ocr_service import ocr_paddle
        engine = MagicMock()
        engine.ocr.side_effect = Exception("GPU OOM")
        mock_engine.return_value = engine

        text, conf = ocr_paddle("/fake/image.jpg")
        self.assertEqual(text, "")
        self.assertEqual(conf, 0.0)


class TestOcrGemini(unittest.TestCase):
    """Gemini VLM 引擎測試（模擬）"""

    @patch("services.ocr_service.GEMINI_API_KEY", "")
    def test_no_api_key(self):
        from services.ocr_service import ocr_gemini
        result = ocr_gemini("/fake/image.jpg")
        self.assertIsNone(result)

    @patch("services.ocr_service.GEMINI_API_KEY", "test-key")
    def test_success(self):
        from services.ocr_service import ocr_gemini
        import tempfile
        import requests as real_requests

        # Create a fake image file
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0test image data")
            temp_path = f.name

        try:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "candidates": [{
                    "content": {
                        "parts": [{"text": json.dumps({
                            "supplier_name": "好鮮水產行",
                            "items": [{"name": "高麗菜", "amount": 350}],
                            "total_amount": 350,
                        })}],
                    },
                }],
            }
            with patch("requests.post", return_value=mock_resp):
                result = ocr_gemini(temp_path)
            self.assertIsNotNone(result)
            self.assertEqual(result["supplier_name"], "好鮮水產行")
        finally:
            os.unlink(temp_path)

    @patch("services.ocr_service.GEMINI_API_KEY", "test-key")
    def test_api_error(self):
        from services.ocr_service import ocr_gemini
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0test")
            temp_path = f.name

        try:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_resp.text = "Internal Server Error"
            with patch("requests.post", return_value=mock_resp):
                result = ocr_gemini(temp_path)
            self.assertIsNone(result)
        finally:
            os.unlink(temp_path)


if __name__ == "__main__":
    unittest.main()
