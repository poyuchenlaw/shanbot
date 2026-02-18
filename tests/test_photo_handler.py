"""photo_handler.py 單元測試 — 稅務扣抵自動分類"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestClassifyTaxDeduction(unittest.TestCase):
    """測試 _classify_tax_deduction() 五種情境"""

    def _classify(self, ocr_result):
        from handlers.photo_handler import _classify_tax_deduction
        return _classify_tax_deduction(ocr_result)

    def test_triplicate_with_tax_id(self):
        """有統編 + 三聯式 → 可扣抵 (deduction=1, format=21)"""
        result = self._classify({
            "supplier_tax_id": "12345678",
            "invoice_type": "三聯式",
        })
        self.assertEqual(result["deduction_code"], "1")
        self.assertEqual(result["tax_type"], "1")
        self.assertEqual(result["invoice_format_code"], "21")

    def test_electronic_with_tax_id(self):
        """有統編 + 電子發票 → 可扣抵 (deduction=1, format=25)"""
        result = self._classify({
            "supplier_tax_id": "87654321",
            "invoice_type": "電子發票",
        })
        self.assertEqual(result["deduction_code"], "1")
        self.assertEqual(result["tax_type"], "1")
        self.assertEqual(result["invoice_format_code"], "25")

    def test_duplicate_with_tax_id(self):
        """有統編 + 二聯式 → 不可扣抵 (deduction=2, format=22)"""
        result = self._classify({
            "supplier_tax_id": "12345678",
            "invoice_type": "二聯式",
        })
        self.assertEqual(result["deduction_code"], "2")
        self.assertEqual(result["tax_type"], "1")
        self.assertEqual(result["invoice_format_code"], "22")

    def test_receipt_no_tax_id(self):
        """無統編 收據 → 不可扣抵 (deduction=2, format=22)"""
        result = self._classify({
            "supplier_tax_id": "",
            "invoice_type": "收據",
        })
        self.assertEqual(result["deduction_code"], "2")
        self.assertEqual(result["tax_type"], "1")
        self.assertEqual(result["invoice_format_code"], "22")

    def test_tax_exempt(self):
        """免稅品項 → 不可扣抵 (deduction=2, tax_type=3, format=22)"""
        result = self._classify({
            "supplier_tax_id": "12345678",
            "invoice_type": "免稅",
        })
        self.assertEqual(result["deduction_code"], "2")
        self.assertEqual(result["tax_type"], "3")
        self.assertEqual(result["invoice_format_code"], "22")

    def test_empty_tax_id_whitespace(self):
        """統編為空白字串 → 視為無統編"""
        result = self._classify({
            "supplier_tax_id": "   ",
            "invoice_type": "三聯式",
        })
        self.assertEqual(result["deduction_code"], "2")

    def test_missing_invoice_type(self):
        """invoice_type 缺失 → fallback"""
        result = self._classify({
            "supplier_tax_id": "",
        })
        self.assertEqual(result["deduction_code"], "2")
        self.assertEqual(result["tax_type"], "1")

    def test_triplicate_english_alias(self):
        """英文別名 triplicate"""
        result = self._classify({
            "supplier_tax_id": "12345678",
            "invoice_type": "triplicate",
        })
        self.assertEqual(result["deduction_code"], "1")
        self.assertEqual(result["invoice_format_code"], "21")

    def test_electronic_english_alias(self):
        """英文別名 electronic"""
        result = self._classify({
            "supplier_tax_id": "12345678",
            "invoice_type": "electronic",
        })
        self.assertEqual(result["deduction_code"], "1")
        self.assertEqual(result["invoice_format_code"], "25")


if __name__ == "__main__":
    unittest.main()
