"""Unit tests for handlers/file_handler.py — 檔案上傳分類處理"""

import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from handlers.file_handler import (
    classify_by_filename,
    detect_file_type,
    inspect_excel_content,
    inspect_pdf_content,
    build_smart_filename,
    CATEGORY_LABELS,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ============================================================
# 1. TestClassifyByFilename
# ============================================================

class TestClassifyByFilename(unittest.TestCase):
    """測試檔名自動分類邏輯"""

    def test_payroll_keywords(self):
        self.assertEqual(classify_by_filename("2026年2月薪資表.xlsx"), "payroll")
        self.assertEqual(classify_by_filename("salary_report.xlsx"), "payroll")
        self.assertEqual(classify_by_filename("工資明細.pdf"), "payroll")

    def test_lease_keywords(self):
        self.assertEqual(classify_by_filename("店面租約2026.pdf"), "general")
        self.assertEqual(classify_by_filename("lease_agreement.pdf"), "general")
        self.assertEqual(classify_by_filename("房租收據.pdf"), "general")

    def test_contract_keywords(self):
        self.assertEqual(classify_by_filename("供餐合約.pdf"), "revenue")
        self.assertEqual(classify_by_filename("contract_2026.xlsx"), "revenue")

    def test_asset_keywords(self):
        self.assertEqual(classify_by_filename("折舊計算表.xlsx"), "fixed_asset")
        self.assertEqual(classify_by_filename("資產清單.xlsx"), "fixed_asset")
        self.assertEqual(classify_by_filename("asset_list.xlsx"), "fixed_asset")

    def test_insurance_keywords(self):
        self.assertEqual(classify_by_filename("火險保單.pdf"), "general")
        self.assertEqual(classify_by_filename("insurance_policy.pdf"), "general")

    def test_financing_keywords(self):
        self.assertEqual(classify_by_filename("銀行借款合約.pdf"), "financing")
        self.assertEqual(classify_by_filename("loan_agreement.pdf"), "financing")

    def test_expenditure_keywords(self):
        self.assertEqual(classify_by_filename("採購單據.xlsx"), "expenditure")
        self.assertEqual(classify_by_filename("purchase_order.xlsx"), "expenditure")

    def test_unknown_defaults_to_general(self):
        self.assertEqual(classify_by_filename("random_file.xlsx"), "general")
        self.assertEqual(classify_by_filename("report.pdf"), "general")

    def test_case_insensitive(self):
        self.assertEqual(classify_by_filename("SALARY_2026.xlsx"), "payroll")
        self.assertEqual(classify_by_filename("Lease_Agreement.PDF"), "general")


# ============================================================
# 2. TestDetectFileType
# ============================================================

class TestDetectFileType(unittest.TestCase):
    """測試副檔名偵測"""

    def test_excel_types(self):
        self.assertEqual(detect_file_type("data.xlsx"), "excel")
        self.assertEqual(detect_file_type("data.xls"), "excel")
        self.assertEqual(detect_file_type("data.csv"), "excel")

    def test_pdf_type(self):
        self.assertEqual(detect_file_type("report.pdf"), "pdf")
        self.assertEqual(detect_file_type("REPORT.PDF"), "pdf")

    def test_image_types(self):
        self.assertEqual(detect_file_type("photo.jpg"), "image")
        self.assertEqual(detect_file_type("photo.png"), "image")

    def test_other_types(self):
        self.assertEqual(detect_file_type("document.docx"), "other")
        self.assertEqual(detect_file_type("file.txt"), "other")


# ============================================================
# 3. TestCategoryLabels
# ============================================================

class TestCategoryLabels(unittest.TestCase):
    """確認所有分類都有中文名稱"""

    def test_all_categories_have_labels(self):
        expected_cats = [
            "revenue", "expenditure", "payroll", "production",
            "financing", "investment", "fixed_asset", "general",
        ]
        for cat in expected_cats:
            self.assertIn(cat, CATEGORY_LABELS, f"Missing label for {cat}")
            self.assertTrue(len(CATEGORY_LABELS[cat]) > 0)


# ============================================================
# 4. TestHandleFileReceived
# ============================================================

class TestHandleFileReceived(unittest.TestCase):
    """測試完整檔案上傳流程（mock 外部依賴）"""

    def setUp(self):
        self.line_service = MagicMock()
        self.line_service.get_content.return_value = b"fake excel content"
        self.line_service.reply_flex.return_value = True
        self.tmpdir = tempfile.mkdtemp()

    @patch("handlers.file_handler.FILES_DIR")
    @patch("handlers.file_handler.sm")
    def test_unsupported_format_returns_message(self, mock_sm, mock_dir):
        mock_dir.__str__ = lambda x: self.tmpdir
        from handlers.file_handler import handle_file_received
        result = _run(handle_file_received(
            self.line_service, "msg123", "document.docx",
            "group1", "user1", "token1"
        ))
        self.assertIn("目前支援", result)

    @patch("handlers.file_handler.FILES_DIR", new_callable=lambda: property(lambda s: tempfile.mkdtemp()))
    @patch("handlers.file_handler.sm")
    def test_excel_file_calls_add_financial_document(self, mock_sm, _):
        mock_sm.add_financial_document.return_value = 42
        from handlers.file_handler import handle_file_received

        with patch("handlers.file_handler.FILES_DIR", self.tmpdir):
            result = _run(handle_file_received(
                self.line_service, "msg123", "薪資表2月.xlsx",
                "group1", "user1", "token1"
            ))

        mock_sm.add_financial_document.assert_called_once()
        call_kwargs = mock_sm.add_financial_document.call_args
        # 確認分類為 payroll
        self.assertEqual(call_kwargs[1].get("doc_category") or call_kwargs[0][4], "payroll")

    @patch("handlers.file_handler.sm")
    def test_download_failure_returns_error(self, mock_sm):
        self.line_service.get_content.return_value = None
        from handlers.file_handler import handle_file_received
        result = _run(handle_file_received(
            self.line_service, "msg123", "file.xlsx",
            "group1", "user1", "token1"
        ))
        self.assertIn("下載失敗", result)


# ============================================================
# 5. TestBuildSmartFilename
# ============================================================

class TestBuildSmartFilename(unittest.TestCase):
    """測試智能重命名"""

    def test_adds_category_prefix(self):
        result = build_smart_filename("data.xlsx", "payroll", "", "2026-02")
        self.assertEqual(result, "202602_薪資表_data.xlsx")

    def test_no_duplicate_category(self):
        result = build_smart_filename("薪資表.xlsx", "payroll", "", "2026-02")
        self.assertEqual(result, "202602_薪資表.xlsx")

    def test_general_category(self):
        result = build_smart_filename("report.pdf", "general", "", "2026-02")
        self.assertEqual(result, "202602_一般文件_report.pdf")

    def test_preserves_extension(self):
        result = build_smart_filename("file.pdf", "financing", "", "2026-03")
        self.assertTrue(result.endswith(".pdf"))
        self.assertIn("融資", result)


# ============================================================
# 6. TestInspectExcelContent
# ============================================================

class TestInspectExcelContent(unittest.TestCase):
    """測試 Excel 內容檢視"""

    def test_with_payroll_excel(self):
        """建立含薪資關鍵字的 Excel 測試檔"""
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not installed")

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "1月薪資"
        ws.append(["員工", "薪資", "勞保", "健保", "實發"])
        ws.append(["王小明", 35000, 1000, 500, 33500])

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            wb.save(f.name)
            path = f.name

        try:
            result = inspect_excel_content(path)
            self.assertEqual(result["sheet_names"], ["1月薪資"])
            self.assertIn("1月薪資", result["headers"])
            self.assertEqual(result["suggested_category"], "payroll")
            self.assertTrue(any("薪資" in kw for kw in result["content_keywords"]))
        finally:
            os.unlink(path)

    def test_with_empty_excel(self):
        """空 Excel 應回傳空結果"""
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not installed")

        wb = openpyxl.Workbook()
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            wb.save(f.name)
            path = f.name

        try:
            result = inspect_excel_content(path)
            self.assertEqual(result["sheet_names"], ["Sheet"])
            self.assertIsNone(result["suggested_category"])
        finally:
            os.unlink(path)


# ============================================================
# 7. TestInspectPdfContent
# ============================================================

class TestInspectPdfContent(unittest.TestCase):
    """測試 PDF 內容檢視"""

    def test_with_text_pdf(self):
        """建立含文字的 PDF 測試檔（用英文關鍵字，因 PyMuPDF 預設字型不支援中文）"""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            self.skipTest("PyMuPDF not installed")

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "salary report\npurchase order invoice details")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            doc.save(f.name)
            path = f.name
        doc.close()

        try:
            result = inspect_pdf_content(path)
            self.assertEqual(result["page_count"], 1)
            # 'salary' maps to payroll
            self.assertEqual(result["suggested_category"], "payroll")
            self.assertTrue(len(result["content_summary"]) > 0)
        finally:
            os.unlink(path)

    def test_nonexistent_file(self):
        """不存在的檔案應回傳空結果"""
        result = inspect_pdf_content("/tmp/nonexistent_test_file.pdf")
        self.assertEqual(result["page_count"], 0)
        self.assertIsNone(result["suggested_category"])


if __name__ == "__main__":
    unittest.main()
