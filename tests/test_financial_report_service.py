"""Unit tests for services/financial_report_service.py — 四大報表生成"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ============================================================
# 1. TestBalanceSheet
# ============================================================

class TestBalanceSheet(unittest.TestCase):
    """資產負債表生成測試"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    @patch("services.financial_report_service._get_monthly_cost_data")
    @patch("services.financial_report_service._get_expense_data")
    @patch("services.financial_report_service._get_income_data")
    def test_generate_empty_data(self, mock_income, mock_expense, mock_cost):
        """空資料應生成報表（全部為 0）"""
        mock_income.return_value = {"rows": [], "total": 0}
        mock_expense.return_value = {"categories": {}, "total": 0}
        mock_cost.return_value = {
            "ingredient_total": 0, "labor_total": 0,
            "overhead_total": 0, "input_tax_total": 0,
        }

        from services.financial_report_service import generate_balance_sheet
        path = generate_balance_sheet("2026-02", self.tmpdir)

        self.assertIsNotNone(path)
        self.assertTrue(os.path.exists(path))
        self.assertIn("資產負債表", path)

    @patch("services.financial_report_service._get_monthly_cost_data")
    @patch("services.financial_report_service._get_expense_data")
    @patch("services.financial_report_service._get_income_data")
    def test_generate_with_data(self, mock_income, mock_expense, mock_cost):
        """有資料應正確生成"""
        mock_income.return_value = {"rows": [{"amount": 100000}], "total": 100000}
        mock_expense.return_value = {"categories": {"蔬菜": 30000}, "total": 30000}
        mock_cost.return_value = {
            "ingredient_total": 30000, "labor_total": 20000,
            "overhead_total": 10000, "input_tax_total": 1500,
        }

        from services.financial_report_service import generate_balance_sheet
        path = generate_balance_sheet("2026-02", self.tmpdir)

        self.assertIsNotNone(path)
        self.assertTrue(os.path.getsize(path) > 0)


# ============================================================
# 2. TestIncomeStatement
# ============================================================

class TestIncomeStatement(unittest.TestCase):
    """損益表生成測試"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    @patch("services.financial_report_service._get_monthly_cost_data")
    @patch("services.financial_report_service._get_expense_data")
    @patch("services.financial_report_service._get_income_data")
    def test_generate_empty_data(self, mock_income, mock_expense, mock_cost):
        mock_income.return_value = {"rows": [], "total": 0}
        mock_expense.return_value = {"categories": {}, "total": 0}
        mock_cost.return_value = {
            "ingredient_total": 0, "labor_total": 0,
            "overhead_total": 0, "input_tax_total": 0,
        }

        from services.financial_report_service import generate_income_statement
        path = generate_income_statement("2026-02", self.tmpdir)

        self.assertIsNotNone(path)
        self.assertTrue(os.path.exists(path))
        self.assertIn("損益表", path)

    @patch("services.financial_report_service._get_monthly_cost_data")
    @patch("services.financial_report_service._get_expense_data")
    @patch("services.financial_report_service._get_income_data")
    def test_generate_with_data(self, mock_income, mock_expense, mock_cost):
        mock_income.return_value = {
            "rows": [{"amount": 80000, "description": "團膳收入"}],
            "total": 80000,
        }
        mock_expense.return_value = {
            "categories": {"蔬菜": 15000, "肉類": 10000, "水電": 5000},
            "total": 30000,
        }
        mock_cost.return_value = {
            "ingredient_total": 25000, "labor_total": 15000,
            "overhead_total": 5000, "input_tax_total": 1250,
        }

        from services.financial_report_service import generate_income_statement
        path = generate_income_statement("2026-02", self.tmpdir)

        self.assertIsNotNone(path)
        self.assertTrue(os.path.getsize(path) > 0)


# ============================================================
# 3. TestCashFlow
# ============================================================

class TestCashFlow(unittest.TestCase):
    """現金流量表生成測試"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    @patch("services.financial_report_service._get_monthly_cost_data")
    @patch("services.financial_report_service._get_expense_data")
    @patch("services.financial_report_service._get_income_data")
    def test_generate_empty_data(self, mock_income, mock_expense, mock_cost):
        mock_income.return_value = {"rows": [], "total": 0}
        mock_expense.return_value = {"categories": {}, "total": 0}
        mock_cost.return_value = {
            "ingredient_total": 0, "labor_total": 0,
            "overhead_total": 0, "input_tax_total": 0,
        }

        from services.financial_report_service import generate_cash_flow
        path = generate_cash_flow("2026-02", self.tmpdir)

        self.assertIsNotNone(path)
        self.assertIn("現金流量表", path)


# ============================================================
# 4. TestEquityChanges
# ============================================================

class TestEquityChanges(unittest.TestCase):
    """權益變動表生成測試"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    @patch("services.financial_report_service._get_monthly_cost_data")
    @patch("services.financial_report_service._get_expense_data")
    @patch("services.financial_report_service._get_income_data")
    def test_generate_empty_data(self, mock_income, mock_expense, mock_cost):
        mock_income.return_value = {"rows": [], "total": 0}
        mock_expense.return_value = {"categories": {}, "total": 0}
        mock_cost.return_value = {
            "ingredient_total": 0, "labor_total": 0,
            "overhead_total": 0, "input_tax_total": 0,
        }

        from services.financial_report_service import generate_equity_changes
        path = generate_equity_changes("2026-02", self.tmpdir)

        self.assertIsNotNone(path)
        self.assertIn("權益變動表", path)

    @patch("services.financial_report_service._get_monthly_cost_data")
    @patch("services.financial_report_service._get_expense_data")
    @patch("services.financial_report_service._get_income_data")
    def test_generate_with_profit(self, mock_income, mock_expense, mock_cost):
        mock_income.return_value = {"rows": [{"amount": 120000}], "total": 120000}
        mock_expense.return_value = {"categories": {}, "total": 0}
        mock_cost.return_value = {
            "ingredient_total": 40000, "labor_total": 20000,
            "overhead_total": 10000, "input_tax_total": 0,
        }

        from services.financial_report_service import generate_equity_changes
        path = generate_equity_changes("2026-02", self.tmpdir)

        self.assertIsNotNone(path)
        self.assertTrue(os.path.getsize(path) > 0)


if __name__ == "__main__":
    unittest.main()
