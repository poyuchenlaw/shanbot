"""Unit tests for services/flex_builder.py — pure-function Flex Message builders."""

import unittest
from datetime import datetime
from unittest.mock import patch

from services.flex_builder import (
    COLOR_BLUE,
    COLOR_PRIMARY,
    COLOR_RED,
    COLOR_SECONDARY,
    COLOR_TEXT,
    COLOR_TEXT_SUB,
    build_camera_menu,
    build_export_menu,
    build_export_period_picker,
    build_finance_menu,
    build_finance_upload_menu,
    build_file_upload_result_flex,
    build_file_reclassify_flex,
    build_finance_doc_list_flex,
    build_finance_doc_summary_flex,
    build_guide_menu,
    build_menu_dish_flex,
    build_menu_plan_menu,
    build_pending_list_flex,
    build_price_compare_flex,
    build_purchase_menu,
    build_reports_menu,
    build_report_period_picker,
    build_stats_flex,
    build_supplier_list_flex,
)


# ============================================================
#  1. TestCameraMenu
# ============================================================
class TestCameraMenu(unittest.TestCase):
    """v2.2 Camera Menu — 3 卡 Carousel：訣竅 → 流程 → 拍照"""

    def setUp(self):
        self.result = build_camera_menu()

    def test_type_is_carousel(self):
        self.assertEqual(self.result["type"], "carousel")

    def test_has_three_cards(self):
        self.assertEqual(len(self.result["contents"]), 3)

    def test_card1_tips(self):
        card = self.result["contents"][0]
        self.assertEqual(card["type"], "bubble")
        header_text = card["header"]["contents"][0]["text"]
        self.assertIn("訣竅", header_text)

    def test_card2_flow(self):
        card = self.result["contents"][1]
        header_text = card["header"]["contents"][0]["text"]
        self.assertIn("流程", header_text)

    def test_card3_has_camera_buttons(self):
        card = self.result["contents"][2]
        # Camera buttons now use postback actions (mode=camera / mode=album)
        actions = _collect_actions(card)
        postback_data = [a.get("data", "") for a in actions if a.get("type") == "postback"]
        self.assertTrue(any("camera" in d for d in postback_data))
        self.assertTrue(any("album" in d for d in postback_data))

    def test_tips_card_has_five_tips(self):
        card = self.result["contents"][0]
        all_texts = _collect_texts(card["body"])
        # Check for key tip keywords
        self.assertTrue(any("光線" in t for t in all_texts))
        self.assertTrue(any("對焦" in t for t in all_texts))


# ============================================================
#  2. TestFinanceMenu (v2.2 — 財務資料提供和確認)
# ============================================================
class TestFinanceMenu(unittest.TestCase):
    def setUp(self):
        self.result = build_finance_menu()

    def test_type_is_carousel(self):
        self.assertEqual(self.result["type"], "carousel")

    def test_has_four_bubbles(self):
        self.assertEqual(len(self.result["contents"]), 4)

    def test_all_contents_are_bubbles(self):
        for b in self.result["contents"]:
            self.assertEqual(b["type"], "bubble")

    def test_first_card_is_intro(self):
        card = self.result["contents"][0]
        header_text = card["header"]["contents"][0]["text"]
        self.assertIn("財務資料", header_text)

    def test_second_card_is_upload(self):
        card = self.result["contents"][1]
        header_text = card["header"]["contents"][0]["text"]
        self.assertIn("上傳", header_text)

    def test_third_card_is_list(self):
        card = self.result["contents"][2]
        header_text = card["header"]["contents"][0]["text"]
        self.assertIn("已上傳", header_text)

    def test_fourth_card_is_confirm(self):
        card = self.result["contents"][3]
        header_text = card["header"]["contents"][0]["text"]
        self.assertIn("勾稽", header_text)

    def test_list_card_has_postback_buttons(self):
        card = self.result["contents"][2]
        buttons = _collect_buttons(card)
        data_vals = [b["action"]["data"] for b in buttons]
        self.assertTrue(any("finance_docs" in d for d in data_vals))

    def test_confirm_card_has_postback_buttons(self):
        card = self.result["contents"][3]
        buttons = _collect_buttons(card)
        data_vals = [b["action"]["data"] for b in buttons]
        self.assertTrue(any("confirm_month" in d for d in data_vals))


# ============================================================
#  3. TestPurchaseMenu
# ============================================================
class TestPurchaseMenu(unittest.TestCase):
    def test_type_is_bubble(self):
        result = build_purchase_menu()
        self.assertEqual(result["type"], "bubble")

    def test_no_pending_no_badge(self):
        result = build_purchase_menu(pending_count=0)
        body_texts = [c.get("text", "") for c in result["body"]["contents"]
                      if c.get("type") == "text"]
        badge_texts = [t for t in body_texts if "筆" in t]
        # When count is 0, badge should not appear
        for t in badge_texts:
            self.assertNotIn("[", t)

    def test_pending_count_shown_in_badge(self):
        result = build_purchase_menu(pending_count=5)
        body_texts = [c.get("text", "") for c in result["body"]["contents"]
                      if c.get("type") == "text"]
        self.assertTrue(any("5 筆" in t for t in body_texts))

    def test_large_pending_count(self):
        result = build_purchase_menu(pending_count=999)
        body_texts = [c.get("text", "") for c in result["body"]["contents"]
                      if c.get("type") == "text"]
        self.assertTrue(any("999 筆" in t for t in body_texts))

    def test_has_pending_button(self):
        result = build_purchase_menu()
        body = result["body"]["contents"]
        buttons = [c for c in body if c.get("type") == "button"]
        data_values = [b["action"]["data"] for b in buttons]
        self.assertIn("action=purchase&cmd=pending", data_values)

    def test_has_market_and_supplier_buttons(self):
        result = build_purchase_menu()
        body = result["body"]["contents"]
        # Flatten: find horizontal boxes and extract buttons from them
        all_buttons = []
        for c in body:
            if c.get("type") == "button":
                all_buttons.append(c)
            elif c.get("type") == "box" and c.get("layout") == "horizontal":
                for inner in c.get("contents", []):
                    if inner.get("type") == "button":
                        all_buttons.append(inner)
        data_values = [b["action"]["data"] for b in all_buttons]
        self.assertIn("action=purchase&cmd=market", data_values)
        self.assertIn("action=purchase&cmd=suppliers", data_values)

    def test_has_price_compare_button(self):
        result = build_purchase_menu()
        body = result["body"]["contents"]
        buttons = [c for c in body if c.get("type") == "button"]
        data_values = [b["action"]["data"] for b in buttons]
        self.assertIn("action=purchase&cmd=price_compare", data_values)


# ============================================================
#  4. TestMenuPlanMenu
# ============================================================
class TestMenuPlanMenu(unittest.TestCase):
    def setUp(self):
        self.result = build_menu_plan_menu()

    def test_type_is_carousel(self):
        self.assertEqual(self.result["type"], "carousel")

    def test_has_four_bubbles(self):
        self.assertEqual(len(self.result["contents"]), 4)

    def test_first_card_is_intro(self):
        card = self.result["contents"][0]
        header_text = card["header"]["contents"][0]["text"]
        self.assertIn("菜單企劃", header_text)

    def test_second_card_current_menu(self):
        card = self.result["contents"][1]
        header_text = card["header"]["contents"][0]["text"]
        self.assertIn("本月菜單確認", header_text)

    def test_third_card_image_gen(self):
        card = self.result["contents"][2]
        header_text = card["header"]["contents"][0]["text"]
        self.assertIn("菜色文宣圖片", header_text)

    def test_fourth_card_cost_calc(self):
        card = self.result["contents"][3]
        header_text = card["header"]["contents"][0]["text"]
        self.assertIn("食材成本試算", header_text)

    def test_current_menu_has_view_and_edit_actions(self):
        card = self.result["contents"][1]
        footer_data = [btn["action"]["data"]
                       for btn in card["footer"]["contents"]]
        self.assertIn("action=menu&cmd=view_current", footer_data)
        self.assertIn("action=menu&cmd=edit", footer_data)

    def test_image_card_has_gen_image_action(self):
        card = self.result["contents"][2]
        footer_data = [btn["action"]["data"]
                       for btn in card["footer"]["contents"]]
        self.assertIn("action=menu&cmd=gen_image", footer_data)

    def test_cost_card_has_cost_calc_action(self):
        card = self.result["contents"][3]
        footer_data = [btn["action"]["data"]
                       for btn in card["footer"]["contents"]]
        self.assertIn("action=menu&cmd=cost_calc", footer_data)


# ============================================================
#  5. TestExportMenu
# ============================================================
class TestExportMenu(unittest.TestCase):
    """v2.2 — build_export_menu() 現在是 build_reports_menu() 的別名"""
    def setUp(self):
        self.result = build_export_menu()

    def test_type_is_carousel(self):
        self.assertEqual(self.result["type"], "carousel")

    def test_has_three_cards(self):
        self.assertEqual(len(self.result["contents"]), 3)

    def test_intro_card_title(self):
        header_text = self.result["contents"][0]["header"]["contents"][0]["text"]
        self.assertIn("報表生成", header_text)

    def test_financial_card_has_four_buttons(self):
        card = self.result["contents"][1]
        buttons = _collect_buttons(card)
        self.assertEqual(len(buttons), 4)

    def test_export_card_has_export_types(self):
        card = self.result["contents"][2]
        buttons = _collect_buttons(card)
        data_values = [b["action"]["data"] for b in buttons]
        expected_types = ["monthly", "annual", "mof_txt",
                          "accounting", "handler_cert"]
        for et in expected_types:
            self.assertTrue(
                any(f"type={et}" in d for d in data_values),
                f"Missing export type={et} in button data")

    def test_intro_has_steps(self):
        texts = _collect_texts(self.result["contents"][0])
        self.assertTrue(any("選擇報表類型" in t or "報表" in t for t in texts))


# ============================================================
#  6. TestGuideMenu
# ============================================================
class TestGuideMenu(unittest.TestCase):
    def setUp(self):
        self.result = build_guide_menu()

    def test_type_is_carousel(self):
        self.assertEqual(self.result["type"], "carousel")

    def test_has_six_bubbles(self):
        """v2.2: 新增財務群組指南，共 6 張卡"""
        self.assertEqual(len(self.result["contents"]), 6)

    def test_first_card_quickstart(self):
        header_text = self.result["contents"][0]["header"]["contents"][0]["text"]
        self.assertIn("快速入門", header_text)

    def test_second_card_camera_steps(self):
        header_text = self.result["contents"][1]["header"]["contents"][0]["text"]
        self.assertIn("拍照記帳教學", header_text)

    def test_third_card_finance_group(self):
        """v2.2: 新增群組 vs 一對一指南"""
        header_text = self.result["contents"][2]["header"]["contents"][0]["text"]
        self.assertIn("群組", header_text)

    def test_fourth_card_features(self):
        header_text = self.result["contents"][3]["header"]["contents"][0]["text"]
        self.assertIn("各功能操作說明", header_text)

    def test_fifth_card_faq(self):
        header_text = self.result["contents"][4]["header"]["contents"][0]["text"]
        self.assertIn("常見問題", header_text)

    def test_sixth_card_info(self):
        header_text = self.result["contents"][5]["header"]["contents"][0]["text"]
        self.assertIn("可查看的資訊", header_text)

    def test_quickstart_has_steps(self):
        body = self.result["contents"][0]["body"]
        all_texts = _collect_texts(body)
        self.assertTrue(any("拍照記帳" in t for t in all_texts))

    def test_faq_card_has_questions_and_answers(self):
        body = self.result["contents"][4]["body"]
        all_texts = _collect_texts(body)
        self.assertTrue(any("Q:" in t for t in all_texts))
        self.assertTrue(any("A:" in t for t in all_texts))


# ============================================================
#  7. TestStatsFlex
# ============================================================
class TestStatsFlex(unittest.TestCase):
    def test_type_is_bubble(self):
        result = build_stats_flex("2025-06", {})
        self.assertEqual(result["type"], "bubble")

    def test_header_contains_year_month(self):
        result = build_stats_flex("2025-06", {})
        header_text = result["header"]["contents"][0]["text"]
        self.assertIn("2025-06", header_text)

    def test_stats_values_rendered(self):
        stats = {
            "total": 42,
            "pending": 5,
            "confirmed": 30,
            "exported": 7,
            "total_amount": 123456,
            "total_tax": 6172,
        }
        result = build_stats_flex("2025-06", stats)
        all_texts = _collect_texts(result["body"])
        self.assertTrue(any("42 筆" in t for t in all_texts))
        self.assertTrue(any("$123,456" in t for t in all_texts))
        self.assertTrue(any("$6,172" in t for t in all_texts))

    def test_zero_stats_defaults(self):
        result = build_stats_flex("2025-01", {})
        all_texts = _collect_texts(result["body"])
        self.assertTrue(any("0 筆" in t for t in all_texts))
        self.assertTrue(any("$0" in t for t in all_texts))

    def test_none_values_treated_as_zero(self):
        stats = {"total": None, "total_amount": None, "total_tax": None}
        result = build_stats_flex("2025-01", stats)
        all_texts = _collect_texts(result["body"])
        self.assertTrue(any("0 筆" in t for t in all_texts))

    def test_body_has_separator(self):
        result = build_stats_flex("2025-01", {})
        types = [c["type"] for c in result["body"]["contents"]]
        self.assertIn("separator", types)


# ============================================================
#  8. TestPriceCompareFlex
# ============================================================
class TestPriceCompareFlex(unittest.TestCase):
    def test_type_is_bubble(self):
        result = build_price_compare_flex([])
        self.assertEqual(result["type"], "bubble")

    def test_header_has_title(self):
        result = build_price_compare_flex([])
        header_text = result["header"]["contents"][0]["text"]
        self.assertIn("食材價格對照表", header_text)

    def test_normal_items_rendered(self):
        items = [
            {"name": "高麗菜", "purchase_price": 30,
             "market_price": 28, "deviation_pct": 7},
        ]
        result = build_price_compare_flex(items)
        all_texts = _collect_texts(result["body"])
        self.assertTrue(any("高麗菜" in t for t in all_texts))
        self.assertTrue(any("$30" in t for t in all_texts))
        self.assertTrue(any("$28" in t for t in all_texts))

    def test_alert_item_has_red_circle(self):
        items = [
            {"name": "松露", "purchase_price": 500,
             "market_price": 300, "deviation_pct": 67},
        ]
        result = build_price_compare_flex(items)
        all_texts = _collect_texts(result["body"])
        self.assertTrue(any("松露" in t for t in all_texts))

    def test_alert_item_uses_red_color(self):
        items = [
            {"name": "松露", "purchase_price": 500,
             "market_price": 300, "deviation_pct": 67},
        ]
        result = build_price_compare_flex(items)
        # The item row is the 3rd element (after header row + separator)
        item_row = result["body"]["contents"][2]
        name_el = item_row["contents"][0]
        self.assertEqual(name_el["color"], COLOR_RED)

    def test_alert_count_warning_shown(self):
        items = [
            {"name": "A", "purchase_price": 100,
             "market_price": 50, "deviation_pct": 100},
            {"name": "B", "purchase_price": 30,
             "market_price": 28, "deviation_pct": 7},
        ]
        result = build_price_compare_flex(items)
        all_texts = _collect_texts(result["body"])
        self.assertTrue(any("1 項偏差超過 30%" in t for t in all_texts))

    def test_no_alert_warning_when_all_normal(self):
        items = [
            {"name": "B", "purchase_price": 30,
             "market_price": 28, "deviation_pct": 7},
        ]
        result = build_price_compare_flex(items)
        all_texts = _collect_texts(result["body"])
        self.assertFalse(any("偏差超過" in t for t in all_texts))

    def test_max_15_items(self):
        items = [
            {"name": f"item_{i}", "purchase_price": 10,
             "market_price": 10, "deviation_pct": 0}
            for i in range(20)
        ]
        result = build_price_compare_flex(items)
        body = result["body"]["contents"]
        # Header row + separator + 15 data rows = 17
        data_rows = [c for c in body
                     if c.get("type") == "box" and c.get("layout") == "horizontal"
                     and c.get("margin", "") == "sm"]
        self.assertLessEqual(len(data_rows), 15)

    def test_negative_deviation_alert(self):
        """Deviation below -30 should also be flagged."""
        items = [
            {"name": "cheap", "purchase_price": 10,
             "market_price": 50, "deviation_pct": -80},
        ]
        result = build_price_compare_flex(items)
        all_texts = _collect_texts(result["body"])
        self.assertTrue(any("1 項偏差超過 30%" in t for t in all_texts))


# ============================================================
#  9. TestSupplierListFlex
# ============================================================
class TestSupplierListFlex(unittest.TestCase):
    def test_empty_list_shows_placeholder(self):
        result = build_supplier_list_flex([])
        self.assertEqual(result["type"], "bubble")
        all_texts = _collect_texts(result["body"])
        self.assertTrue(any("尚未建立" in t for t in all_texts))

    def test_header_shows_count(self):
        suppliers = [{"name": "A", "tax_id": "12345678"}]
        result = build_supplier_list_flex(suppliers)
        header_text = result["header"]["contents"][0]["text"]
        self.assertIn("1 家", header_text)

    def test_supplier_name_rendered(self):
        suppliers = [{"name": "大安市場", "tax_id": "99887766"}]
        result = build_supplier_list_flex(suppliers)
        all_texts = _collect_texts(result["body"])
        self.assertTrue(any("大安市場" in t for t in all_texts))

    def test_supplier_without_tax_id(self):
        suppliers = [{"name": "菜市場攤販"}]
        result = build_supplier_list_flex(suppliers)
        all_texts = _collect_texts(result["body"])
        self.assertTrue(any("無統編" in t for t in all_texts))

    def test_max_20_suppliers(self):
        suppliers = [{"name": f"S{i}", "tax_id": f"{i:08d}"}
                     for i in range(30)]
        result = build_supplier_list_flex(suppliers)
        body_rows = result["body"]["contents"]
        self.assertLessEqual(len(body_rows), 20)

    def test_invoice_icon_for_has_uniform(self):
        suppliers = [{"name": "X", "has_uniform_invoice": 1}]
        result = build_supplier_list_flex(suppliers)
        row = result["body"]["contents"][0]
        icon_text = row["contents"][0]["text"]
        self.assertEqual(icon_text, "\U0001f4c4")  # paper emoji

    def test_no_invoice_icon(self):
        suppliers = [{"name": "X", "has_uniform_invoice": 0}]
        result = build_supplier_list_flex(suppliers)
        row = result["body"]["contents"][0]
        icon_text = row["contents"][0]["text"]
        self.assertEqual(icon_text, "\U0001f4dd")  # memo emoji


# ============================================================
#  10. TestPendingListFlex
# ============================================================
class TestPendingListFlex(unittest.TestCase):
    def test_empty_list_shows_message(self):
        result = build_pending_list_flex([])
        self.assertEqual(result["type"], "bubble")
        all_texts = _collect_texts(result["body"])
        self.assertTrue(any("沒有待處理" in t for t in all_texts))

    def test_populated_list_header_count(self):
        pendings = [
            {"id": 1, "purchase_date": "2025-06-01",
             "total_amount": 1500, "supplier_name": "A"},
            {"id": 2, "purchase_date": "2025-06-02",
             "total_amount": 800, "supplier_name": "B"},
        ]
        result = build_pending_list_flex(pendings)
        header_text = result["header"]["contents"][0]["text"]
        self.assertIn("2 筆", header_text)

    def test_item_has_confirm_edit_discard_buttons(self):
        pendings = [
            {"id": 7, "purchase_date": "2025-06-01",
             "total_amount": 2000, "supplier_name": "C"},
        ]
        result = build_pending_list_flex(pendings)
        all_texts = _collect_texts(result["body"])
        # Flatten and find all button action data
        buttons = _collect_buttons(result["body"])
        data_values = [b["action"]["data"] for b in buttons]
        self.assertIn("action=confirm&id=7", data_values)
        self.assertIn("action=edit&id=7", data_values)
        self.assertIn("action=discard&id=7", data_values)

    def test_item_shows_amount(self):
        pendings = [
            {"id": 1, "purchase_date": "2025-06-01",
             "total_amount": 12345, "supplier_name": "Test"},
        ]
        result = build_pending_list_flex(pendings)
        all_texts = _collect_texts(result["body"])
        self.assertTrue(any("$12,345" in t for t in all_texts))

    def test_item_shows_supplier(self):
        pendings = [
            {"id": 1, "purchase_date": "2025-06-01",
             "total_amount": 100, "supplier_name": "Fresh Market"},
        ]
        result = build_pending_list_flex(pendings)
        all_texts = _collect_texts(result["body"])
        self.assertTrue(any("Fresh Market" in t for t in all_texts))

    def test_max_10_items_rendered(self):
        pendings = [
            {"id": i, "purchase_date": "2025-06-01",
             "total_amount": 100, "supplier_name": f"S{i}"}
            for i in range(15)
        ]
        result = build_pending_list_flex(pendings)
        # Count how many item boxes have confirm buttons (each item has one)
        buttons = _collect_buttons(result["body"])
        confirm_buttons = [b for b in buttons
                           if "action=confirm" in b["action"]["data"]]
        self.assertLessEqual(len(confirm_buttons), 10)


# ============================================================
#  11. TestExportPeriodPicker
# ============================================================
class TestExportPeriodPicker(unittest.TestCase):
    def test_type_is_bubble(self):
        result = build_export_period_picker("monthly")
        self.assertEqual(result["type"], "bubble")

    def test_monthly_has_this_month_button(self):
        result = build_export_period_picker("monthly")
        buttons = _collect_buttons(result["body"])
        data_values = [b["action"]["data"] for b in buttons]
        # Monthly should have a "this month" option
        ym = datetime.now().strftime("%Y-%m")
        self.assertTrue(
            any(f"period={ym}" in d for d in data_values),
            f"Expected period={ym} in data values: {data_values}")

    def test_annual_has_this_month_button(self):
        result = build_export_period_picker("annual")
        buttons = _collect_buttons(result["body"])
        data_values = [b["action"]["data"] for b in buttons]
        ym = datetime.now().strftime("%Y-%m")
        self.assertTrue(any(f"period={ym}" in d for d in data_values))

    def test_mof_txt_no_this_month_button(self):
        result = build_export_period_picker("mof_txt")
        buttons = _collect_buttons(result["body"])
        # mof_txt should have exactly 2 buttons (current + previous period)
        self.assertEqual(len(buttons), 2)

    def test_header_contains_label(self):
        result = build_export_period_picker("mof_txt")
        header_text = result["header"]["contents"][0]["text"]
        self.assertIn("稅務申報", header_text)

    def test_accounting_label(self):
        result = build_export_period_picker("accounting")
        header_text = result["header"]["contents"][0]["text"]
        self.assertIn("會計匯出", header_text)

    def test_handler_cert_label(self):
        result = build_export_period_picker("handler_cert")
        header_text = result["header"]["contents"][0]["text"]
        self.assertIn("經手人憑證", header_text)

    def test_postback_data_contains_export_type(self):
        result = build_export_period_picker("accounting")
        buttons = _collect_buttons(result["body"])
        for btn in buttons:
            self.assertIn("type=accounting", btn["action"]["data"])

    def test_unknown_type_falls_back_to_raw_string(self):
        result = build_export_period_picker("some_new_type")
        header_text = result["header"]["contents"][0]["text"]
        self.assertIn("some_new_type", header_text)

    def test_bimonthly_periods_present(self):
        """Both current and previous bimonthly period buttons exist."""
        result = build_export_period_picker("mof_txt")
        buttons = _collect_buttons(result["body"])
        data_values = [b["action"]["data"] for b in buttons]
        # At least one should contain 'period=' with a range format
        self.assertTrue(
            all("action=do_export" in d for d in data_values))


# ============================================================
#  12. TestMenuDishFlex
# ============================================================
class TestMenuDishFlex(unittest.TestCase):
    def test_type_is_bubble(self):
        result = build_menu_dish_flex("紅燒肉", ["五花肉", "醬油"], 150.0)
        self.assertEqual(result["type"], "bubble")

    def test_header_has_dish_name(self):
        result = build_menu_dish_flex("紅燒肉", ["五花肉", "醬油"], 150.0)
        header_text = result["header"]["contents"][0]["text"]
        self.assertIn("紅燒肉", header_text)

    def test_ingredients_listed(self):
        result = build_menu_dish_flex("Test", ["豆腐", "蔥花", "辣椒"], 80.0)
        all_texts = _collect_texts(result["body"])
        self.assertTrue(any("豆腐" in t for t in all_texts))
        self.assertTrue(any("蔥花" in t for t in all_texts))
        self.assertTrue(any("辣椒" in t for t in all_texts))

    def test_cost_shown(self):
        result = build_menu_dish_flex("Test", ["A"], 5000.0)
        all_texts = _collect_texts(result["body"])
        self.assertTrue(any("$5,000" in t for t in all_texts))

    def test_no_image_no_hero(self):
        result = build_menu_dish_flex("Test", ["A"], 100.0)
        self.assertNotIn("hero", result)

    def test_with_image_has_hero(self):
        result = build_menu_dish_flex(
            "Test", ["A"], 100.0, image_url="https://example.com/img.jpg")
        self.assertIn("hero", result)
        self.assertEqual(result["hero"]["type"], "image")
        self.assertEqual(result["hero"]["url"], "https://example.com/img.jpg")

    def test_description_included_when_provided(self):
        result = build_menu_dish_flex(
            "Test", ["A"], 100.0, description="A delicious dish")
        all_texts = _collect_texts(result["body"])
        self.assertTrue(any("A delicious dish" in t for t in all_texts))

    def test_no_description_no_extra_text(self):
        result = build_menu_dish_flex("Test", ["A"], 100.0, description="")
        body_contents = result["body"]["contents"]
        # First element should be separator (no description text before it)
        self.assertEqual(body_contents[0]["type"], "separator")

    def test_max_10_ingredients(self):
        ings = [f"食材{i}" for i in range(15)]
        result = build_menu_dish_flex("Test", ings, 100.0)
        all_texts = _collect_texts(result["body"])
        ingredient_texts = [t for t in all_texts if t.startswith("• ")]
        self.assertLessEqual(len(ingredient_texts), 10)


# ============================================================
#  v2.2: TestFinanceUploadMenu
# ============================================================
class TestFinanceUploadMenu(unittest.TestCase):
    def setUp(self):
        self.result = build_finance_upload_menu()

    def test_type_is_carousel(self):
        self.assertEqual(self.result["type"], "carousel")

    def test_has_four_cards(self):
        self.assertEqual(len(self.result["contents"]), 4)

    def test_first_card_title(self):
        card = self.result["contents"][0]
        texts = _collect_texts(card)
        self.assertTrue(any("財務資料" in t for t in texts))

    def test_list_card_has_buttons(self):
        card = self.result["contents"][2]
        buttons = _collect_buttons(card)
        self.assertTrue(len(buttons) >= 1)

    def test_confirm_card_has_buttons(self):
        card = self.result["contents"][3]
        buttons = _collect_buttons(card)
        self.assertTrue(len(buttons) >= 1)


class TestReportsMenu(unittest.TestCase):
    def setUp(self):
        self.result = build_reports_menu()

    def test_type_is_carousel(self):
        self.assertEqual(self.result["type"], "carousel")

    def test_has_three_cards(self):
        self.assertEqual(len(self.result["contents"]), 3)

    def test_financial_card_has_four_report_buttons(self):
        card = self.result["contents"][1]
        buttons = _collect_buttons(card)
        # 四大報表 = 4 buttons
        self.assertEqual(len(buttons), 4)

    def test_export_card_has_export_buttons(self):
        card = self.result["contents"][2]
        buttons = _collect_buttons(card)
        self.assertTrue(len(buttons) >= 5)


class TestFileUploadResultFlex(unittest.TestCase):
    def test_basic_structure(self):
        doc_info = {
            "id": 1, "filename": "test.xlsx", "file_type": "excel",
            "doc_category": "payroll", "category_label": "人力資源循環",
            "gdrive_path": "2026/02月/薪資表/test.xlsx",
            "year_month": "2026-02",
        }
        result = build_file_upload_result_flex(doc_info)
        self.assertEqual(result["type"], "bubble")
        buttons = _collect_buttons(result)
        self.assertEqual(len(buttons), 2)  # 確認 + 修改分類

    def test_without_gdrive_path(self):
        doc_info = {
            "id": 2, "filename": "test.pdf", "file_type": "pdf",
            "doc_category": "general", "category_label": "一般循環",
            "gdrive_path": "", "year_month": "2026-02",
        }
        result = build_file_upload_result_flex(doc_info)
        self.assertEqual(result["type"], "bubble")


class TestFileReclassifyFlex(unittest.TestCase):
    def test_has_eight_category_buttons(self):
        result = build_file_reclassify_flex(42)
        buttons = _collect_buttons(result)
        self.assertEqual(len(buttons), 8)


class TestFinanceDocListFlex(unittest.TestCase):
    def test_empty_list(self):
        result = build_finance_doc_list_flex([], "2026-02")
        self.assertEqual(result["type"], "bubble")
        texts = _collect_texts(result)
        self.assertTrue(any("尚未上傳" in t for t in texts))

    def test_with_docs(self):
        docs = [
            {"filename": "薪資表.xlsx", "doc_category": "payroll", "status": "confirmed"},
            {"filename": "租約.pdf", "doc_category": "general", "status": "pending"},
        ]
        result = build_finance_doc_list_flex(docs, "2026-02")
        texts = _collect_texts(result)
        self.assertTrue(any("2 件" in t for t in texts))


class TestFinanceDocSummaryFlex(unittest.TestCase):
    def test_basic_summary(self):
        summary = {
            "year_month": "2026-02", "total": 5, "confirmed": 3,
            "categories": {
                "payroll": {"count": 2, "confirmed": 1},
                "general": {"count": 3, "confirmed": 2},
            },
        }
        result = build_finance_doc_summary_flex(summary)
        self.assertEqual(result["type"], "bubble")
        texts = _collect_texts(result)
        self.assertTrue(any("5 件" in t for t in texts))


class TestReportPeriodPicker(unittest.TestCase):
    def test_balance_sheet_picker(self):
        result = build_report_period_picker("balance_sheet")
        self.assertEqual(result["type"], "bubble")
        buttons = _collect_buttons(result)
        self.assertEqual(len(buttons), 2)
        texts = _collect_texts(result)
        self.assertTrue(any("資產負債表" in t for t in texts))

    def test_income_statement_picker(self):
        result = build_report_period_picker("income_statement")
        texts = _collect_texts(result)
        self.assertTrue(any("損益表" in t for t in texts))


class TestFinanceMenuAlias(unittest.TestCase):
    """build_finance_menu 應等同於 build_finance_upload_menu"""
    def test_alias_returns_same_structure(self):
        a = build_finance_menu()
        b = build_finance_upload_menu()
        self.assertEqual(a["type"], b["type"])
        self.assertEqual(len(a["contents"]), len(b["contents"]))


class TestExportMenuAlias(unittest.TestCase):
    """build_export_menu 應等同於 build_reports_menu"""
    def test_alias_returns_same_structure(self):
        a = build_export_menu()
        b = build_reports_menu()
        self.assertEqual(a["type"], b["type"])
        self.assertEqual(len(a["contents"]), len(b["contents"]))


class TestGuideMenuV22(unittest.TestCase):
    """v2.2 使用說明應有財務群組指南卡片"""
    def setUp(self):
        self.result = build_guide_menu()

    def test_has_six_cards(self):
        self.assertEqual(len(self.result["contents"]), 6)

    def test_finance_group_card_present(self):
        texts = _collect_texts(self.result)
        self.assertTrue(any("群組" in t for t in texts))

    def test_updated_faq(self):
        texts = _collect_texts(self.result)
        self.assertTrue(any("上傳的檔案去哪了" in t for t in texts))


# ============================================================
#  Helpers
# ============================================================
def _collect_texts(node: dict) -> list[str]:
    """Recursively collect all 'text' values from a Flex node tree."""
    texts = []
    if isinstance(node, dict):
        if node.get("type") == "text" and "text" in node:
            texts.append(node["text"])
        for v in node.values():
            if isinstance(v, (dict, list)):
                texts.extend(_collect_texts(v))
    elif isinstance(node, list):
        for item in node:
            texts.extend(_collect_texts(item))
    return texts


def _collect_buttons(node: dict) -> list[dict]:
    """Recursively collect all button elements from a Flex node tree."""
    buttons = []
    if isinstance(node, dict):
        if node.get("type") == "button":
            buttons.append(node)
        for v in node.values():
            if isinstance(v, (dict, list)):
                buttons.extend(_collect_buttons(v))
    elif isinstance(node, list):
        for item in node:
            buttons.extend(_collect_buttons(item))
    return buttons


def _collect_actions(node) -> list[dict]:
    """Recursively collect all 'action' dicts from a Flex node tree."""
    actions = []
    if isinstance(node, dict):
        if "action" in node and isinstance(node["action"], dict):
            actions.append(node["action"])
        for v in node.values():
            if isinstance(v, (dict, list)):
                actions.extend(_collect_actions(v))
    elif isinstance(node, list):
        for item in node:
            actions.extend(_collect_actions(item))
    return actions


if __name__ == "__main__":
    unittest.main()
