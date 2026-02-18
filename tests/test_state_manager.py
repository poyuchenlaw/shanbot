"""state_manager.py 單元測試 — SQLite 資料層完整驗證"""

import json
import os
import tempfile
import unittest
from datetime import date

# 每個測試使用獨立的 temp DB
_original_db_path = None


def _setup_temp_db():
    """建立暫存 DB 並初始化"""
    import state_manager as sm
    global _original_db_path
    _original_db_path = sm.DB_PATH
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    sm.DB_PATH = path
    sm.init_db()
    return path


def _teardown_temp_db(path):
    """清理暫存 DB"""
    import state_manager as sm
    sm.DB_PATH = _original_db_path
    try:
        os.unlink(path)
    except OSError:
        pass


class TestInitDb(unittest.TestCase):
    """資料庫初始化測試"""

    def setUp(self):
        self.db_path = _setup_temp_db()

    def tearDown(self):
        _teardown_temp_db(self.db_path)

    def test_all_tables_created(self):
        import state_manager as sm
        counts = sm.get_table_counts()
        expected_tables = [
            "ingredients", "suppliers", "purchase_staging", "purchase_items",
            "price_history", "recipes", "recipe_ingredients", "menu_schedule",
            "monthly_cost", "config", "tax_exports", "account_mapping",
            "conversation_state",
        ]
        for t in expected_tables:
            self.assertIn(t, counts, f"Missing table: {t}")
            self.assertNotEqual(counts[t], -1, f"Table {t} error")

    def test_account_mapping_seeded(self):
        import state_manager as sm
        mappings = sm.get_all_account_mappings()
        self.assertEqual(len(mappings), 15)

    def test_account_mapping_categories(self):
        import state_manager as sm
        categories = {m["category"] for m in sm.get_all_account_mappings()}
        self.assertIn("蔬菜", categories)
        self.assertIn("肉類", categories)
        self.assertIn("水電", categories)
        self.assertIn("保險", categories)

    def test_idempotent_init(self):
        """重複初始化不應錯誤"""
        import state_manager as sm
        sm.init_db()
        sm.init_db()
        counts = sm.get_table_counts()
        # INSERT OR IGNORE ensures no duplicates
        self.assertGreaterEqual(counts["account_mapping"], 15)


class TestConversationState(unittest.TestCase):
    """對話狀態機測試"""

    def setUp(self):
        self.db_path = _setup_temp_db()

    def tearDown(self):
        _teardown_temp_db(self.db_path)

    def test_default_idle(self):
        import state_manager as sm
        state, data = sm.get_state("nonexistent_chat")
        self.assertEqual(state, "idle")
        self.assertEqual(data, {})

    def test_set_and_get(self):
        import state_manager as sm
        sm.set_state("C001", "waiting_confirm", {"staging_id": 42})
        state, data = sm.get_state("C001")
        self.assertEqual(state, "waiting_confirm")
        self.assertEqual(data["staging_id"], 42)

    def test_update_existing(self):
        import state_manager as sm
        sm.set_state("C001", "waiting_confirm", {"staging_id": 1})
        sm.set_state("C001", "waiting_edit", {"staging_id": 2})
        state, data = sm.get_state("C001")
        self.assertEqual(state, "waiting_edit")
        self.assertEqual(data["staging_id"], 2)

    def test_clear_state(self):
        import state_manager as sm
        sm.set_state("C001", "waiting_confirm", {"staging_id": 1})
        sm.clear_state("C001")
        state, data = sm.get_state("C001")
        self.assertEqual(state, "idle")
        self.assertEqual(data, {})

    def test_chinese_in_state_data(self):
        import state_manager as sm
        sm.set_state("C001", "waiting_edit", {"field": "供應商", "value": "王記水產"})
        state, data = sm.get_state("C001")
        self.assertEqual(data["field"], "供應商")
        self.assertEqual(data["value"], "王記水產")


class TestSupplier(unittest.TestCase):
    """供應商 CRUD 測試"""

    def setUp(self):
        self.db_path = _setup_temp_db()

    def tearDown(self):
        _teardown_temp_db(self.db_path)

    def test_upsert_new(self):
        import state_manager as sm
        sid = sm.upsert_supplier("好鮮水產行", tax_id="12345678", has_invoice=True)
        self.assertIsInstance(sid, int)
        self.assertGreater(sid, 0)

    def test_upsert_update(self):
        import state_manager as sm
        sid1 = sm.upsert_supplier("好鮮水產行", tax_id="12345678")
        sid2 = sm.upsert_supplier("好鮮水產行", tax_id="87654321")
        self.assertEqual(sid1, sid2)
        s = sm.get_supplier(name="好鮮水產行")
        self.assertEqual(s["tax_id"], "87654321")

    def test_get_by_name(self):
        import state_manager as sm
        sm.upsert_supplier("菜市場阿嬤", has_invoice=False)
        s = sm.get_supplier(name="菜市場阿嬤")
        self.assertIsNotNone(s)
        self.assertEqual(s["has_uniform_invoice"], 0)

    def test_get_by_id(self):
        import state_manager as sm
        sid = sm.upsert_supplier("好鮮水產行")
        s = sm.get_supplier(supplier_id=sid)
        self.assertEqual(s["name"], "好鮮水產行")

    def test_get_nonexistent(self):
        import state_manager as sm
        s = sm.get_supplier(name="不存在")
        self.assertIsNone(s)

    def test_get_all(self):
        import state_manager as sm
        sm.upsert_supplier("A供應商")
        sm.upsert_supplier("B供應商")
        all_s = sm.get_all_suppliers()
        self.assertEqual(len(all_s), 2)


class TestIngredient(unittest.TestCase):
    """食材主檔測試"""

    def setUp(self):
        self.db_path = _setup_temp_db()

    def tearDown(self):
        _teardown_temp_db(self.db_path)

    def test_upsert_new(self):
        import state_manager as sm
        iid = sm.upsert_ingredient("VEG001", "高麗菜", "蔬菜", "kg")
        self.assertGreater(iid, 0)

    def test_upsert_update(self):
        import state_manager as sm
        sm.upsert_ingredient("VEG001", "高麗菜", "蔬菜", "kg")
        sm.upsert_ingredient("VEG001", "高麗菜（台灣）", "蔬菜", "kg")
        ing = sm.find_ingredient("高麗菜（台灣）")
        self.assertIsNotNone(ing)

    def test_find_exact(self):
        import state_manager as sm
        sm.upsert_ingredient("VEG001", "高麗菜", "蔬菜")
        found = sm.find_ingredient("高麗菜")
        self.assertIsNotNone(found)
        self.assertEqual(found["code"], "VEG001")

    def test_find_like(self):
        import state_manager as sm
        sm.upsert_ingredient("VEG001", "高麗菜", "蔬菜")
        found = sm.find_ingredient("高麗")
        self.assertIsNotNone(found)

    def test_find_none(self):
        import state_manager as sm
        found = sm.find_ingredient("不存在食材")
        self.assertIsNone(found)

    def test_update_price(self):
        import state_manager as sm
        iid = sm.upsert_ingredient("VEG001", "高麗菜", "蔬菜")
        sm.update_ingredient_price(iid, 35.0, market_ref=30.0)
        found = sm.find_ingredient("高麗菜")
        self.assertEqual(found["current_price"], 35.0)
        self.assertEqual(found["market_ref_price"], 30.0)

    def test_update_price_without_market_ref(self):
        import state_manager as sm
        iid = sm.upsert_ingredient("VEG001", "高麗菜", "蔬菜")
        sm.update_ingredient_price(iid, 35.0)
        found = sm.find_ingredient("高麗菜")
        self.assertEqual(found["current_price"], 35.0)


class TestPurchaseStaging(unittest.TestCase):
    """採購暫存表測試"""

    def setUp(self):
        self.db_path = _setup_temp_db()

    def tearDown(self):
        _teardown_temp_db(self.db_path)

    def test_add_staging(self):
        import state_manager as sm
        sid = sm.add_purchase_staging("U001", "C001", purchase_date="2026-03-15")
        self.assertGreater(sid, 0)

    def test_auto_year_month(self):
        import state_manager as sm
        sid = sm.add_purchase_staging("U001", "C001", purchase_date="2026-03-15")
        staging = sm.get_staging(sid)
        self.assertEqual(staging["year_month"], "2026-03")

    def test_auto_tax_period(self):
        import state_manager as sm
        sid = sm.add_purchase_staging("U001", "C001", purchase_date="2026-03-15")
        staging = sm.get_staging(sid)
        self.assertEqual(staging["tax_period"], "2026-03-04")

    def test_default_status_pending(self):
        import state_manager as sm
        sid = sm.add_purchase_staging("U001", "C001")
        staging = sm.get_staging(sid)
        self.assertEqual(staging["status"], "pending")

    def test_update_fields(self):
        import state_manager as sm
        sid = sm.add_purchase_staging("U001", "C001")
        sm.update_purchase_staging(sid, supplier_name="好鮮水產行", total_amount=5000)
        staging = sm.get_staging(sid)
        self.assertEqual(staging["supplier_name"], "好鮮水產行")
        self.assertEqual(staging["total_amount"], 5000)

    def test_confirm(self):
        import state_manager as sm
        sid = sm.add_purchase_staging("U001", "C001")
        sm.confirm_staging(sid)
        staging = sm.get_staging(sid)
        self.assertEqual(staging["status"], "confirmed")
        self.assertIsNotNone(staging["confirmed_at"])

    def test_get_nonexistent(self):
        import state_manager as sm
        staging = sm.get_staging(9999)
        self.assertIsNone(staging)

    def test_get_pending(self):
        import state_manager as sm
        sm.add_purchase_staging("U001", "C001")
        sm.add_purchase_staging("U001", "C001")
        sid3 = sm.add_purchase_staging("U001", "C001")
        sm.confirm_staging(sid3)
        pending = sm.get_pending_stagings()
        self.assertEqual(len(pending), 2)

    def test_get_pending_by_chat(self):
        import state_manager as sm
        sm.add_purchase_staging("U001", "C001")
        sm.add_purchase_staging("U001", "C002")
        pending = sm.get_pending_stagings(chat_id="C001")
        self.assertEqual(len(pending), 1)

    def test_get_confirmed_by_tax_period(self):
        import state_manager as sm
        sid1 = sm.add_purchase_staging("U001", "C001", purchase_date="2026-01-10")
        sid2 = sm.add_purchase_staging("U001", "C001", purchase_date="2026-01-20")
        sid3 = sm.add_purchase_staging("U001", "C001", purchase_date="2026-03-10")
        sm.confirm_staging(sid1)
        sm.confirm_staging(sid2)
        sm.confirm_staging(sid3)
        confirmed = sm.get_confirmed_stagings("2026-01-02")
        self.assertEqual(len(confirmed), 2)

    def test_get_stagings_by_month(self):
        import state_manager as sm
        sid1 = sm.add_purchase_staging("U001", "C001", purchase_date="2026-03-10")
        sid2 = sm.add_purchase_staging("U001", "C001", purchase_date="2026-03-20")
        sm.confirm_staging(sid1)
        sm.confirm_staging(sid2)
        stagings = sm.get_stagings_by_month("2026-03")
        self.assertEqual(len(stagings), 2)


class TestPurchaseItems(unittest.TestCase):
    """採購明細表測試"""

    def setUp(self):
        self.db_path = _setup_temp_db()

    def tearDown(self):
        _teardown_temp_db(self.db_path)

    def test_add_item(self):
        import state_manager as sm
        sid = sm.add_purchase_staging("U001", "C001")
        item_id = sm.add_purchase_item(sid, "高麗菜", quantity=10, unit="kg",
                                       unit_price=35, amount=350)
        self.assertGreater(item_id, 0)

    def test_auto_tax_amount(self):
        import state_manager as sm
        sid = sm.add_purchase_staging("U001", "C001")
        sm.add_purchase_item(sid, "高麗菜", amount=1000)
        items = sm.get_purchase_items(sid)
        self.assertEqual(items[0]["tax_amount"], 50)  # 1000 * 0.05

    def test_get_items(self):
        import state_manager as sm
        sid = sm.add_purchase_staging("U001", "C001")
        sm.add_purchase_item(sid, "高麗菜", amount=350)
        sm.add_purchase_item(sid, "紅蘿蔔", amount=200)
        sm.add_purchase_item(sid, "豬肉", amount=500)
        items = sm.get_purchase_items(sid)
        self.assertEqual(len(items), 3)
        names = [i["item_name"] for i in items]
        self.assertIn("高麗菜", names)
        self.assertIn("豬肉", names)


class TestPriceHistory(unittest.TestCase):
    """價格歷史測試"""

    def setUp(self):
        self.db_path = _setup_temp_db()

    def tearDown(self):
        _teardown_temp_db(self.db_path)

    def test_add_price(self):
        import state_manager as sm
        iid = sm.upsert_ingredient("VEG001", "高麗菜", "蔬菜")
        sm.add_price_history(iid, "2026-03-15", "farm_api", avg_price=25.0)
        history = sm.get_price_history(iid)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["avg_price"], 25.0)

    def test_upsert_replaces(self):
        import state_manager as sm
        iid = sm.upsert_ingredient("VEG001", "高麗菜", "蔬菜")
        sm.add_price_history(iid, "2026-03-15", "farm_api", avg_price=25.0)
        sm.add_price_history(iid, "2026-03-15", "farm_api", avg_price=30.0)
        history = sm.get_price_history(iid)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["avg_price"], 30.0)

    def test_limit(self):
        import state_manager as sm
        iid = sm.upsert_ingredient("VEG001", "高麗菜", "蔬菜")
        for i in range(10):
            sm.add_price_history(iid, f"2026-03-{i+1:02d}", "farm_api", avg_price=25.0 + i)
        history = sm.get_price_history(iid, days=5)
        self.assertEqual(len(history), 5)


class TestRecipe(unittest.TestCase):
    """配方表測試"""

    def setUp(self):
        self.db_path = _setup_temp_db()

    def tearDown(self):
        _teardown_temp_db(self.db_path)

    def test_add_recipe(self):
        import state_manager as sm
        rid = sm.add_recipe("紅燒肉", "主菜", 100)
        self.assertGreater(rid, 0)

    def test_add_recipe_ingredient(self):
        import state_manager as sm
        rid = sm.add_recipe("紅燒肉", "主菜")
        iid = sm.upsert_ingredient("MEAT001", "五花肉", "肉類", "kg")
        ri_id = sm.add_recipe_ingredient(rid, iid, 5.0, "kg", "MAIN")
        self.assertGreater(ri_id, 0)

    def test_get_bom(self):
        import state_manager as sm
        rid = sm.add_recipe("紅燒肉")
        iid1 = sm.upsert_ingredient("MEAT001", "五花肉", "肉類", "kg")
        iid2 = sm.upsert_ingredient("SAUCE001", "醬油", "調味料", "ml")
        sm.add_recipe_ingredient(rid, iid1, 5.0, "kg")
        sm.add_recipe_ingredient(rid, iid2, 500, "ml")
        bom = sm.get_recipe_bom(rid)
        self.assertEqual(len(bom), 2)
        self.assertIn("ingredient_name", bom[0])


class TestMonthlyCost(unittest.TestCase):
    """月度成本測試"""

    def setUp(self):
        self.db_path = _setup_temp_db()

    def tearDown(self):
        _teardown_temp_db(self.db_path)

    def test_insert(self):
        import state_manager as sm
        mid = sm.upsert_monthly_cost("2026-03", ingredient_total=50000)
        self.assertGreater(mid, 0)

    def test_update(self):
        import state_manager as sm
        sm.upsert_monthly_cost("2026-03", ingredient_total=50000)
        sm.upsert_monthly_cost("2026-03", ingredient_total=60000)
        mc = sm.get_monthly_cost("2026-03")
        self.assertEqual(mc["ingredient_total"], 60000)

    def test_get_nonexistent(self):
        import state_manager as sm
        mc = sm.get_monthly_cost("9999-01")
        self.assertIsNone(mc)


class TestTaxExport(unittest.TestCase):
    """稅務匯出記錄測試"""

    def setUp(self):
        self.db_path = _setup_temp_db()

    def tearDown(self):
        _teardown_temp_db(self.db_path)

    def test_add(self):
        import state_manager as sm
        eid = sm.add_tax_export("2026-01-02", "mof_txt", "/tmp/test.txt",
                                record_count=10, total_amount=50000, total_tax=2500)
        self.assertGreater(eid, 0)

    def test_get_by_period(self):
        import state_manager as sm
        sm.add_tax_export("2026-01-02", "mof_txt", "/tmp/a.txt")
        sm.add_tax_export("2026-01-02", "winton_excel", "/tmp/b.xlsx")
        sm.add_tax_export("2026-03-04", "mof_txt", "/tmp/c.txt")
        exports = sm.get_tax_exports("2026-01-02")
        self.assertEqual(len(exports), 2)

    def test_get_all(self):
        import state_manager as sm
        sm.add_tax_export("2026-01-02", "mof_txt", "/tmp/a.txt")
        sm.add_tax_export("2026-03-04", "mof_txt", "/tmp/b.txt")
        exports = sm.get_tax_exports()
        self.assertEqual(len(exports), 2)


class TestConfig(unittest.TestCase):
    """系統配置測試"""

    def setUp(self):
        self.db_path = _setup_temp_db()

    def tearDown(self):
        _teardown_temp_db(self.db_path)

    def test_set_and_get(self):
        import state_manager as sm
        sm.set_config("admin_user_id", "U12345")
        val = sm.get_config("admin_user_id")
        self.assertEqual(val, "U12345")

    def test_get_default(self):
        import state_manager as sm
        val = sm.get_config("nonexistent", "default_value")
        self.assertEqual(val, "default_value")

    def test_upsert(self):
        import state_manager as sm
        sm.set_config("key1", "v1")
        sm.set_config("key1", "v2")
        self.assertEqual(sm.get_config("key1"), "v2")


class TestCalcTaxPeriod(unittest.TestCase):
    """稅期計算測試"""

    def setUp(self):
        self.db_path = _setup_temp_db()

    def tearDown(self):
        _teardown_temp_db(self.db_path)

    def test_jan(self):
        import state_manager as sm
        self.assertEqual(sm._calc_tax_period("2026-01-15"), "2026-01-02")

    def test_feb(self):
        import state_manager as sm
        self.assertEqual(sm._calc_tax_period("2026-02-28"), "2026-01-02")

    def test_mar(self):
        import state_manager as sm
        self.assertEqual(sm._calc_tax_period("2026-03-01"), "2026-03-04")

    def test_apr(self):
        import state_manager as sm
        self.assertEqual(sm._calc_tax_period("2026-04-30"), "2026-03-04")

    def test_nov(self):
        import state_manager as sm
        self.assertEqual(sm._calc_tax_period("2026-11-01"), "2026-11-12")

    def test_dec(self):
        import state_manager as sm
        self.assertEqual(sm._calc_tax_period("2026-12-31"), "2026-11-12")


class TestStagingStats(unittest.TestCase):
    """統計功能測試"""

    def setUp(self):
        self.db_path = _setup_temp_db()

    def tearDown(self):
        _teardown_temp_db(self.db_path)

    def test_empty(self):
        import state_manager as sm
        stats = sm.get_staging_stats()
        self.assertEqual(stats["total"], 0)

    def test_with_data(self):
        import state_manager as sm
        sid1 = sm.add_purchase_staging("U001", "C001", purchase_date="2026-03-10")
        sm.update_purchase_staging(sid1, total_amount=1000, tax_amount=50)
        sm.confirm_staging(sid1)
        sid2 = sm.add_purchase_staging("U001", "C001", purchase_date="2026-03-15")
        sm.update_purchase_staging(sid2, total_amount=2000, tax_amount=100)
        stats = sm.get_staging_stats("2026-03")
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["confirmed"], 1)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["total_amount"], 1000)  # Only confirmed

    def test_ocr_stats(self):
        import state_manager as sm
        sid = sm.add_purchase_staging("U001", "C001")
        sm.update_purchase_staging(sid, ocr_confidence=0.85)
        stats = sm.get_ocr_stats()
        self.assertEqual(stats["total"], 1)
        self.assertAlmostEqual(stats["avg_confidence"], 0.85, places=2)


class TestAccountMapping(unittest.TestCase):
    """會計科目對照測試"""

    def setUp(self):
        self.db_path = _setup_temp_db()

    def tearDown(self):
        _teardown_temp_db(self.db_path)

    def test_get_vegetable(self):
        import state_manager as sm
        m = sm.get_account_mapping("蔬菜")
        self.assertIsNotNone(m)
        self.assertEqual(m["account_code"], "5110")

    def test_get_utility(self):
        import state_manager as sm
        m = sm.get_account_mapping("水電")
        self.assertEqual(m["account_code"], "6180")

    def test_get_nonexistent(self):
        import state_manager as sm
        m = sm.get_account_mapping("不存在類別")
        self.assertIsNone(m)


if __name__ == "__main__":
    unittest.main()
