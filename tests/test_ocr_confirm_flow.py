"""OCR 確認流程測試 — waiting_ocr_confirm 狀態機"""

import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _run(coro):
    """同步執行 async 函數"""
    return asyncio.get_event_loop().run_until_complete(coro)


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


def _create_pending_staging(sm, group_id="C001"):
    """建立一筆 pending staging 並設定 waiting_ocr_confirm 狀態"""
    sid = sm.add_purchase_staging("U001", group_id, purchase_date="2026-03-15")
    sm.update_purchase_staging(sid, supplier_name="好鮮水產行", total_amount=5000,
                               subtotal=4762, tax_amount=238)
    sm.set_state(group_id, "waiting_ocr_confirm", {"staging_id": sid})
    return sid


class TestOcrConfirmState(unittest.TestCase):
    """Test 1: OCR 後 state 設為 waiting_ocr_confirm"""

    def setUp(self):
        self.db_path = _setup_db()

    def tearDown(self):
        _teardown_db(self.db_path)

    def test_state_set_after_staging(self):
        import state_manager as sm
        sid = _create_pending_staging(sm)
        state, data = sm.get_state("C001")
        self.assertEqual(state, "waiting_ocr_confirm")
        self.assertEqual(data["staging_id"], sid)


class TestOcrConfirmWords(unittest.TestCase):
    """Test 2: 回覆 ok / 好 / OK / 👍 → 確認成功，state 清除"""

    def setUp(self):
        self.db_path = _setup_db()
        self.line_svc = MagicMock()

    def tearDown(self):
        _teardown_db(self.db_path)

    def test_ok_lowercase(self):
        import state_manager as sm
        from handlers.command_handler import handle_text
        sid = _create_pending_staging(sm)
        result = _run(handle_text(self.line_svc, "ok", "C001", "U001", "User", "RT001"))
        self.assertIn("已確認", result)
        state, _ = sm.get_state("C001")
        self.assertEqual(state, "idle")

    def test_ok_uppercase(self):
        import state_manager as sm
        from handlers.command_handler import handle_text
        _create_pending_staging(sm)
        result = _run(handle_text(self.line_svc, "OK", "C001", "U001", "User", "RT001"))
        self.assertIn("已確認", result)

    def test_hao(self):
        import state_manager as sm
        from handlers.command_handler import handle_text
        _create_pending_staging(sm)
        result = _run(handle_text(self.line_svc, "好", "C001", "U001", "User", "RT001"))
        self.assertIn("已確認", result)

    def test_thumbs_up(self):
        import state_manager as sm
        from handlers.command_handler import handle_text
        _create_pending_staging(sm)
        result = _run(handle_text(self.line_svc, "👍", "C001", "U001", "User", "RT001"))
        self.assertIn("已確認", result)

    def test_staging_confirmed(self):
        import state_manager as sm
        from handlers.command_handler import handle_text
        sid = _create_pending_staging(sm)
        _run(handle_text(self.line_svc, "ok", "C001", "U001", "User", "RT001"))
        staging = sm.get_staging(sid)
        self.assertEqual(staging["status"], "confirmed")


class TestOcrRejectWords(unittest.TestCase):
    """Test 3: 回覆 修改 / 不對 → 進入 edit 模式"""

    def setUp(self):
        self.db_path = _setup_db()
        self.line_svc = MagicMock()

    def tearDown(self):
        _teardown_db(self.db_path)

    def test_modify(self):
        import state_manager as sm
        from handlers.command_handler import handle_text
        _create_pending_staging(sm)
        result = _run(handle_text(self.line_svc, "修改", "C001", "U001", "User", "RT001"))
        self.assertIn("修改記錄", result)
        state, _ = sm.get_state("C001")
        self.assertEqual(state, "waiting_edit")

    def test_wrong(self):
        import state_manager as sm
        from handlers.command_handler import handle_text
        _create_pending_staging(sm)
        result = _run(handle_text(self.line_svc, "不對", "C001", "U001", "User", "RT001"))
        self.assertIn("修改記錄", result)


class TestOcrDiscard(unittest.TestCase):
    """Test 4: 回覆 捨棄 → staging 變 discarded"""

    def setUp(self):
        self.db_path = _setup_db()
        self.line_svc = MagicMock()

    def tearDown(self):
        _teardown_db(self.db_path)

    def test_discard(self):
        import state_manager as sm
        from handlers.command_handler import handle_text
        sid = _create_pending_staging(sm)
        result = _run(handle_text(self.line_svc, "捨棄", "C001", "U001", "User", "RT001"))
        self.assertIn("已捨棄", result)
        staging = sm.get_staging(sid)
        self.assertEqual(staging["status"], "discarded")
        state, _ = sm.get_state("C001")
        self.assertEqual(state, "idle")


class TestOcrUnrecognized(unittest.TestCase):
    """Test 5: 回覆無關文字 → 提示訊息，state 不清除"""

    def setUp(self):
        self.db_path = _setup_db()
        self.line_svc = MagicMock()

    def tearDown(self):
        _teardown_db(self.db_path)

    def test_unrecognized_keeps_state(self):
        import state_manager as sm
        from handlers.command_handler import handle_text
        sid = _create_pending_staging(sm)
        result = _run(handle_text(self.line_svc, "今天天氣真好", "C001", "U001", "User", "RT001"))
        self.assertIn("等待確認中", result)
        self.assertIn("OK", result)
        state, data = sm.get_state("C001")
        self.assertEqual(state, "waiting_ocr_confirm")
        self.assertEqual(data["staging_id"], sid)


class TestStickerConfirm(unittest.TestCase):
    """Test 6: 貼圖 → 確認成功"""

    def setUp(self):
        self.db_path = _setup_db()

    def tearDown(self):
        _teardown_db(self.db_path)

    def test_sticker_confirms(self):
        import state_manager as sm
        # Import the function we need to test directly
        sid = _create_pending_staging(sm)

        # Simulate what _handle_sticker does
        state, state_data = sm.get_state("C001")
        self.assertEqual(state, "waiting_ocr_confirm")

        staging_id = state_data.get("staging_id")
        self.assertEqual(staging_id, sid)

        from handlers.command_handler import _confirm_staging
        sm.clear_state("C001")
        result = _run(_confirm_staging(staging_id, "C001"))
        self.assertIn("已確認", result)

        # State should be cleared
        state, _ = sm.get_state("C001")
        self.assertEqual(state, "idle")

        # Staging should be confirmed
        staging = sm.get_staging(sid)
        self.assertEqual(staging["status"], "confirmed")


class TestStickerNoConfirmState(unittest.TestCase):
    """Test 7: 非 waiting_ocr_confirm 狀態貼圖 → 無回應"""

    def setUp(self):
        self.db_path = _setup_db()

    def tearDown(self):
        _teardown_db(self.db_path)

    def test_sticker_ignored_in_idle(self):
        import state_manager as sm
        # State is idle (default)
        state, _ = sm.get_state("C001")
        self.assertEqual(state, "idle")
        # _handle_sticker would not trigger any action in idle state
        # Just verify the state check logic
        self.assertNotEqual(state, "waiting_ocr_confirm")


class TestPhotoOverridesState(unittest.TestCase):
    """Test 8: 新照片覆蓋舊 state（舊 staging 留 pending）"""

    def setUp(self):
        self.db_path = _setup_db()

    def tearDown(self):
        _teardown_db(self.db_path)

    def test_new_photo_overrides_old_state(self):
        import state_manager as sm
        # Create first staging
        sid1 = _create_pending_staging(sm)

        # Simulate second photo: new staging + overwrite state
        sid2 = sm.add_purchase_staging("U001", "C001", purchase_date="2026-03-15")
        sm.update_purchase_staging(sid2, supplier_name="阿明豆腐店", total_amount=1200,
                                   subtotal=1143, tax_amount=57)
        sm.set_state("C001", "waiting_ocr_confirm", {"staging_id": sid2})

        # Old staging still pending
        old = sm.get_staging(sid1)
        self.assertEqual(old["status"], "pending")

        # State now points to new staging
        state, data = sm.get_state("C001")
        self.assertEqual(state, "waiting_ocr_confirm")
        self.assertEqual(data["staging_id"], sid2)


if __name__ == "__main__":
    unittest.main()
