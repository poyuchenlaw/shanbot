"""richmenu_service.py 單元測試 — Rich Menu CRUD + 部署流程"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock, mock_open

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.richmenu_service import RICHMENU_JSON, RichMenuService


# ---------------------------------------------------------------------------
# TestRichMenuJson — 靜態 JSON 結構驗證
# ---------------------------------------------------------------------------
class TestRichMenuJson(unittest.TestCase):
    """RICHMENU_JSON 結構正確性"""

    def test_size_width(self):
        self.assertEqual(RICHMENU_JSON["size"]["width"], 2500)

    def test_size_height(self):
        self.assertEqual(RICHMENU_JSON["size"]["height"], 1686)

    def test_areas_count(self):
        self.assertEqual(len(RICHMENU_JSON["areas"]), 6)

    def test_top_row_bounds_y(self):
        """上排三格 y=0"""
        for area in RICHMENU_JSON["areas"][:3]:
            self.assertEqual(area["bounds"]["y"], 0)

    def test_bottom_row_bounds_y(self):
        """下排三格 y=843"""
        for area in RICHMENU_JSON["areas"][3:]:
            self.assertEqual(area["bounds"]["y"], 843)

    def test_all_areas_have_postback(self):
        for area in RICHMENU_JSON["areas"]:
            self.assertEqual(area["action"]["type"], "postback")

    def test_postback_data_values(self):
        expected = ["menu=camera", "menu=finance_upload", "menu=purchase",
                    "menu=menu_plan", "menu=reports", "menu=guide"]
        actual = [a["action"]["data"] for a in RICHMENU_JSON["areas"]]
        self.assertEqual(actual, expected)

    def test_selected_true(self):
        self.assertTrue(RICHMENU_JSON["selected"])

    def test_chat_bar_text(self):
        self.assertEqual(RICHMENU_JSON["chatBarText"], "小膳功能選單")

    def test_bounds_width_sum_per_row(self):
        """每列 bounds width 總和 = 2500"""
        top = sum(a["bounds"]["width"] for a in RICHMENU_JSON["areas"][:3])
        bottom = sum(a["bounds"]["width"] for a in RICHMENU_JSON["areas"][3:])
        self.assertEqual(top, 2500)
        self.assertEqual(bottom, 2500)


# ---------------------------------------------------------------------------
# TestCreateRichMenu
# ---------------------------------------------------------------------------
class TestCreateRichMenu(unittest.TestCase):

    def setUp(self):
        self.svc = RichMenuService(token="test-token")

    @patch("services.richmenu_service.requests.post")
    def test_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"richMenuId": "rm-abc123"}
        mock_post.return_value = mock_resp

        result = self.svc.create_rich_menu()
        self.assertEqual(result, "rm-abc123")
        mock_post.assert_called_once()

    @patch("services.richmenu_service.requests.post")
    def test_failure_400(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad request"
        mock_post.return_value = mock_resp

        result = self.svc.create_rich_menu()
        self.assertIsNone(result)

    @patch("services.richmenu_service.requests.post", side_effect=Exception("timeout"))
    def test_network_error(self, mock_post):
        result = self.svc.create_rich_menu()
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# TestUploadImage
# ---------------------------------------------------------------------------
class TestUploadImage(unittest.TestCase):

    def setUp(self):
        self.svc = RichMenuService(token="test-token")

    @patch("services.richmenu_service.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"\x89PNG"))
    @patch("services.richmenu_service.requests.post")
    def test_upload_png_success(self, mock_post, mock_exists):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        result = self.svc.upload_image("rm-123", "/tmp/menu.png")
        self.assertTrue(result)
        # verify content-type is png
        call_kwargs = mock_post.call_args
        self.assertEqual(call_kwargs.kwargs["headers"]["Content-Type"], "image/png")

    @patch("services.richmenu_service.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"\xff\xd8\xff"))
    @patch("services.richmenu_service.requests.post")
    def test_upload_jpeg_content_type(self, mock_post, mock_exists):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        result = self.svc.upload_image("rm-123", "/tmp/menu.jpg")
        self.assertTrue(result)
        call_kwargs = mock_post.call_args
        self.assertEqual(call_kwargs.kwargs["headers"]["Content-Type"], "image/jpeg")

    @patch("services.richmenu_service.os.path.exists", return_value=False)
    def test_missing_file(self, mock_exists):
        result = self.svc.upload_image("rm-123", "/tmp/no_such_file.png")
        self.assertFalse(result)

    @patch("services.richmenu_service.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"\x89PNG"))
    @patch("services.richmenu_service.requests.post")
    def test_upload_failure_500(self, mock_post, mock_exists):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal error"
        mock_post.return_value = mock_resp

        result = self.svc.upload_image("rm-123", "/tmp/menu.png")
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# TestSetDefault
# ---------------------------------------------------------------------------
class TestSetDefault(unittest.TestCase):

    def setUp(self):
        self.svc = RichMenuService(token="test-token")

    @patch("services.richmenu_service.requests.post")
    def test_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        result = self.svc.set_default("rm-abc")
        self.assertTrue(result)

    @patch("services.richmenu_service.requests.post")
    def test_failure(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_post.return_value = mock_resp

        result = self.svc.set_default("rm-abc")
        self.assertFalse(result)

    @patch("services.richmenu_service.requests.post", side_effect=Exception("conn err"))
    def test_network_error(self, mock_post):
        result = self.svc.set_default("rm-abc")
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# TestDeploy — 整合流程
# ---------------------------------------------------------------------------
class TestDeploy(unittest.TestCase):

    def setUp(self):
        self.svc = RichMenuService(token="test-token")

    @patch.object(RichMenuService, "set_default", return_value=True)
    @patch.object(RichMenuService, "upload_image", return_value=True)
    @patch.object(RichMenuService, "create_rich_menu", return_value="rm-new-001")
    def test_full_deploy_with_image(self, mock_create, mock_upload, mock_default):
        result = self.svc.deploy(image_path="/tmp/menu.png")
        self.assertEqual(result, "rm-new-001")
        mock_create.assert_called_once()
        mock_upload.assert_called_once_with("rm-new-001", "/tmp/menu.png")
        mock_default.assert_called_once_with("rm-new-001")

    @patch.object(RichMenuService, "set_default", return_value=True)
    @patch.object(RichMenuService, "create_rich_menu", return_value="rm-new-002")
    def test_deploy_without_image(self, mock_create, mock_default):
        result = self.svc.deploy()
        self.assertEqual(result, "rm-new-002")
        mock_default.assert_called_once()

    @patch.object(RichMenuService, "create_rich_menu", return_value=None)
    def test_deploy_create_fails(self, mock_create):
        result = self.svc.deploy(image_path="/tmp/menu.png")
        self.assertIsNone(result)

    @patch.object(RichMenuService, "set_default", return_value=False)
    @patch.object(RichMenuService, "upload_image", return_value=False)
    @patch.object(RichMenuService, "create_rich_menu", return_value="rm-partial")
    def test_deploy_upload_fails_still_returns_id(self, mock_create, mock_upload, mock_default):
        """upload fails => warning logged but still continues to set_default"""
        result = self.svc.deploy(image_path="/tmp/bad.png")
        # Even if set_default fails, menu_id is still returned
        self.assertEqual(result, "rm-partial")


# ---------------------------------------------------------------------------
# TestListMenus
# ---------------------------------------------------------------------------
class TestListMenus(unittest.TestCase):

    def setUp(self):
        self.svc = RichMenuService(token="test-token")

    @patch("services.richmenu_service.requests.get")
    def test_list_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "richmenus": [
                {"richMenuId": "rm-1", "name": "menu1"},
                {"richMenuId": "rm-2", "name": "menu2"},
            ]
        }
        mock_get.return_value = mock_resp

        result = self.svc.list_menus()
        self.assertEqual(len(result), 2)

    @patch("services.richmenu_service.requests.get")
    def test_list_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"richmenus": []}
        mock_get.return_value = mock_resp

        result = self.svc.list_menus()
        self.assertEqual(result, [])

    @patch("services.richmenu_service.requests.get")
    def test_list_error(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_get.return_value = mock_resp

        result = self.svc.list_menus()
        self.assertEqual(result, [])

    @patch("services.richmenu_service.requests.get", side_effect=Exception("err"))
    def test_list_network_error(self, mock_get):
        result = self.svc.list_menus()
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# TestDeleteMenu
# ---------------------------------------------------------------------------
class TestDeleteMenu(unittest.TestCase):

    def setUp(self):
        self.svc = RichMenuService(token="test-token")

    @patch("services.richmenu_service.requests.delete")
    def test_delete_success(self, mock_del):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_del.return_value = mock_resp

        result = self.svc.delete_menu("rm-abc")
        self.assertTrue(result)

    @patch("services.richmenu_service.requests.delete")
    def test_delete_not_found(self, mock_del):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_del.return_value = mock_resp

        result = self.svc.delete_menu("rm-nonexist")
        self.assertFalse(result)

    @patch("services.richmenu_service.requests.delete", side_effect=Exception("err"))
    def test_delete_network_error(self, mock_del):
        result = self.svc.delete_menu("rm-abc")
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# TestGetDefaultId
# ---------------------------------------------------------------------------
class TestGetDefaultId(unittest.TestCase):

    def setUp(self):
        self.svc = RichMenuService(token="test-token")

    @patch("services.richmenu_service.requests.get")
    def test_get_default_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"richMenuId": "rm-default-1"}
        mock_get.return_value = mock_resp

        result = self.svc.get_default_id()
        self.assertEqual(result, "rm-default-1")

    @patch("services.richmenu_service.requests.get")
    def test_get_default_none(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        result = self.svc.get_default_id()
        self.assertIsNone(result)

    @patch("services.richmenu_service.requests.get", side_effect=Exception("err"))
    def test_get_default_error(self, mock_get):
        result = self.svc.get_default_id()
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# TestTokenInit
# ---------------------------------------------------------------------------
class TestTokenInit(unittest.TestCase):

    def test_explicit_token(self):
        svc = RichMenuService(token="my-tok")
        self.assertEqual(svc.token, "my-tok")

    @patch.dict(os.environ, {"LINE_CHANNEL_ACCESS_TOKEN": "env-tok"})
    def test_env_token(self):
        svc = RichMenuService()
        self.assertEqual(svc.token, "env-tok")

    @patch.dict(os.environ, {}, clear=True)
    def test_no_token(self):
        svc = RichMenuService()
        self.assertEqual(svc.token, "")


if __name__ == "__main__":
    unittest.main()
