"""Pipeline _step_accounting_excel 雙版本 Fail-Fast 測試

驗收：
1. 成功路徑：2026-04 月結同時產出 boss + staff 兩份，files=[boss, staff]
2. Fail-Fast：staff 失敗 → 整步 status=error → boss 已產出檔被 rollback unlink
3. callsite 確實塞 variant=boss / variant=staff 各一次
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _seed_test_data(tmpdir: str):
    db_path = os.path.join(tmpdir, "test_shanbot.db")
    os.environ["DB_PATH"] = db_path

    import state_manager
    importlib.reload(state_manager)
    state_manager.init_db()

    sid1 = state_manager.add_purchase_staging(
        user_id="U_t", chat_id="U_t",
        purchase_date="2026-04-05", company_id=1,
    )
    state_manager.update_purchase_staging(
        sid1, supplier_name="阿榮蔬果", total_amount=3500, tax_amount=175)
    state_manager.confirm_staging(sid1)

    sid2 = state_manager.add_purchase_staging(
        user_id="U_t", chat_id="U_t",
        purchase_date="2026-04-12", company_id=1,
    )
    state_manager.update_purchase_staging(
        sid2, supplier_name="義美", total_amount=1200, tax_amount=60)

    import services.accounting_service
    importlib.reload(services.accounting_service)
    services.accounting_service.generate_journal_entries(sid1)
    import services.staff_workbook_service
    importlib.reload(services.staff_workbook_service)
    import services.pipeline_service
    importlib.reload(services.pipeline_service)


def _patch_dir(tmpdir):
    import services.accounting_service as acct
    orig = acct.ACCOUNTING_DIR
    acct.ACCOUNTING_DIR = tmpdir
    return orig


def _restore_dir(orig):
    import services.accounting_service as acct
    acct.ACCOUNTING_DIR = orig


class TestPipelineStepAccountingExcelSuccess(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        _seed_test_data(self.tmpdir)
        self._orig_dir = _patch_dir(self.tmpdir)

    def tearDown(self):
        _restore_dir(self._orig_dir)

    def test_success_produces_both_files(self):
        from services.pipeline_service import _step_accounting_excel
        result = _step_accounting_excel("2026-04", company_id=1)
        self.assertEqual(result["status"], "success",
                         f"expected success, got {result}")
        self.assertIn("files", result)
        self.assertEqual(len(result["files"]), 2,
                         f"expected 2 files (boss+staff), got {result['files']}")
        self.assertTrue(all(os.path.exists(p) for p in result["files"]))
        names = [os.path.basename(p) for p in result["files"]]
        self.assertTrue(any("小魚決策帳冊" in n for n in names),
                         f"missing boss file in {names}")
        self.assertTrue(any("員工驗章帳冊" in n for n in names),
                         f"missing staff file in {names}")


class TestPipelineStepAccountingExcelFailFast(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        _seed_test_data(self.tmpdir)
        self._orig_dir = _patch_dir(self.tmpdir)

    def tearDown(self):
        _restore_dir(self._orig_dir)

    def test_staff_failure_triggers_rollback(self):
        from services import accounting_service
        real_gen = accounting_service.generate_accounting_excel

        def fake_gen(year_month, company_id=None, variant="boss"):
            if variant == "staff":
                raise RuntimeError("simulated staff workbook failure")
            return real_gen(
                year_month, company_id=company_id, variant="boss")

        with patch.object(accounting_service, "generate_accounting_excel",
                          side_effect=fake_gen):
            from services.pipeline_service import _step_accounting_excel
            result = _step_accounting_excel("2026-04", company_id=1)

        self.assertEqual(result["status"], "error",
                         f"expected error, got {result}")
        self.assertEqual(result["failed_variant"], "staff")
        self.assertEqual(result["files"], [])
        for p in result.get("rolled_back", []):
            self.assertFalse(os.path.exists(p),
                             f"rolled_back file still exists: {p}")
        out_dir = os.path.join(self.tmpdir, "2026-04")
        if os.path.isdir(out_dir):
            leftover = [n for n in os.listdir(out_dir)
                        if "帳冊" in n and n.endswith(".xlsx")]
            self.assertEqual(leftover, [],
                              f"Atomicity 違反：error 後仍有殘留帳冊 {leftover}")


class TestCallsiteVariantHits(unittest.TestCase):
    def test_pipeline_source_has_both_variant_calls(self):
        import pathlib
        src = pathlib.Path(__file__).resolve().parent.parent / "services" / "pipeline_service.py"
        text = src.read_text(encoding="utf-8")
        self.assertIn("variant=\"boss\"", text,
                     "pipeline_service.py 必須有 variant=boss callsite")
        self.assertIn("variant=\"staff\"", text,
                     "pipeline_service.py 必須有 variant=staff callsite")


if __name__ == "__main__":
    unittest.main(verbosity=2)
