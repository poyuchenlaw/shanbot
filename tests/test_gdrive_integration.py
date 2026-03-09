"""GDrive 整合端到端驗證 — 用虛擬資料跑完整流程"""

import asyncio
import json
import os
import shutil
import tempfile

import pytest

# 使用測試用暫存目錄，避免影響實際 GDrive
TEST_GDRIVE = tempfile.mkdtemp(prefix="shanbot_gdrive_test_")


@pytest.fixture(autouse=True)
def mock_gdrive(monkeypatch, tmp_path):
    """將 GDRIVE_LOCAL 指向每個測試獨立的暫存目錄"""
    global TEST_GDRIVE
    import services.gdrive_service as gs
    import services.gdrive_index_service as gis

    test_dir = str(tmp_path / "gdrive")
    os.makedirs(test_dir, exist_ok=True)
    TEST_GDRIVE = test_dir

    monkeypatch.setattr(gs, "GDRIVE_LOCAL", test_dir)
    monkeypatch.setattr(gis, "GDRIVE_LOCAL", test_dir)
    monkeypatch.setattr(gis, "INDEX_FILE", os.path.join(test_dir, "索引.json"))
    # Prevent init_folder_structure from overriding GDRIVE_LOCAL via _resolve_gdrive_path
    monkeypatch.setattr(gs, "_resolve_gdrive_path", lambda: test_dir)
    yield


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestFolderStructure:
    """B2: 資料夾結構建立"""

    def test_init_creates_monthly_folders(self):
        from services.gdrive_service import init_folder_structure
        path = init_folder_structure("2026-02")
        assert os.path.isdir(path)
        for folder in ["收據憑證", "採購單據", "月報表", "稅務匯出", "菜單企劃"]:
            assert os.path.isdir(os.path.join(path, folder)), f"Missing: {folder}"

    def test_init_creates_annual_folders(self):
        from services.gdrive_service import init_folder_structure
        init_folder_structure("2026-03")
        year_path = os.path.join(TEST_GDRIVE, "2026")
        for folder in ["年度報表", "食材價格對照"]:
            assert os.path.isdir(os.path.join(year_path, folder)), f"Missing: {folder}"

    def test_init_idempotent(self):
        from services.gdrive_service import init_folder_structure
        p1 = init_folder_structure("2026-02")
        p2 = init_folder_structure("2026-02")
        assert p1 == p2


class TestReceiptUpload:
    """B3: 收據上傳"""

    def test_upload_receipt_basic(self):
        from services.gdrive_service import init_folder_structure, upload_receipt
        init_folder_structure("2026-02")

        # 建立假收據
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff" + b"\x00" * 100)  # 假 JPEG
            tmp = f.name

        try:
            rel = run(upload_receipt(tmp, "2026-02", "全聯"))
            assert rel is not None
            assert "收據憑證" in rel
            assert "全聯" in rel
            # 檔案實際存在
            full = os.path.join(TEST_GDRIVE, rel)
            assert os.path.isfile(full)
        finally:
            os.unlink(tmp)

    def test_upload_receipt_default_month(self):
        from services.gdrive_service import init_folder_structure, upload_receipt
        init_folder_structure()  # 當月

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff" + b"\x00" * 50)
            tmp = f.name

        try:
            rel = run(upload_receipt(tmp))
            assert rel is not None
            assert "收據憑證" in rel
        finally:
            os.unlink(tmp)


class TestExportUpload:
    """B3: 匯出檔案上傳"""

    def test_upload_monthly_export(self):
        from services.gdrive_service import init_folder_structure, upload_export
        init_folder_structure("2026-02")

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(b"PK" + b"\x00" * 100)
            tmp = f.name

        try:
            rel = run(upload_export(tmp, "monthly", "2026-02"))
            assert rel is not None
            assert "月報表" in rel
        finally:
            os.unlink(tmp)

    def test_upload_tax_export(self):
        from services.gdrive_service import init_folder_structure, upload_export
        init_folder_structure("2026-01")

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"TAX DATA")
            tmp = f.name

        try:
            rel = run(upload_export(tmp, "mof_txt", "2026-01-02"))
            assert rel is not None
            assert "稅務匯出" in rel
        finally:
            os.unlink(tmp)

    def test_upload_annual_export(self):
        from services.gdrive_service import init_folder_structure, upload_export
        init_folder_structure("2026-12")

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(b"ANNUAL")
            tmp = f.name

        try:
            rel = run(upload_export(tmp, "annual", "2026"))
            assert rel is not None
            assert "年度報表" in rel
        finally:
            os.unlink(tmp)


class TestFolderIndex:
    """B2/B5: 索引功能"""

    def test_get_folder_index_empty(self):
        from services.gdrive_service import init_folder_structure, get_folder_index
        init_folder_structure("2026-02")
        idx = get_folder_index("2026-02")
        assert idx["year_month"] == "2026-02"
        assert idx["total_files"] == 0
        assert "收據憑證" in idx["folders"]

    def test_get_folder_index_with_files(self):
        from services.gdrive_service import init_folder_structure, upload_receipt, get_folder_index
        init_folder_structure("2026-02")

        # 上傳兩張收據
        for i in range(2):
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                f.write(b"\xff" * (100 + i))
                tmp = f.name
            run(upload_receipt(tmp, "2026-02", f"供應商{i}"))
            os.unlink(tmp)

        idx = get_folder_index("2026-02")
        assert idx["total_files"] == 2
        assert len(idx["folders"]["收據憑證"]) == 2

    def test_get_annual_index(self):
        from services.gdrive_service import init_folder_structure, get_annual_index
        init_folder_structure("2026-01")
        init_folder_structure("2026-02")
        idx = get_annual_index("2026")
        assert "01月" in idx["months"]
        assert "02月" in idx["months"]
        assert "年度報表" in idx["annual_folders"]


class TestIndexService:
    """B5: 索引服務"""

    def test_update_index_creates_file(self):
        from services.gdrive_service import init_folder_structure
        from services.gdrive_index_service import update_index

        init_folder_structure("2026-02")
        idx = update_index("2026-02")
        assert "last_updated" in idx
        assert "2026-02" in idx["months"]

        # 索引檔案實際存在
        assert os.path.isfile(os.path.join(TEST_GDRIVE, "索引.json"))

    def test_search_index(self):
        from services.gdrive_service import init_folder_structure, upload_receipt
        from services.gdrive_index_service import search_index

        init_folder_structure("2026-02")

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False, prefix="market_") as f:
            f.write(b"\xff" * 50)
            tmp = f.name

        run(upload_receipt(tmp, "2026-02", "永輝市場"))
        os.unlink(tmp)

        results = search_index("永輝")
        assert len(results) >= 1
        assert "永輝" in results[0]["name"]

    def test_search_no_match(self):
        from services.gdrive_service import init_folder_structure
        from services.gdrive_index_service import search_index

        init_folder_structure("2026-02")
        results = search_index("不存在的東西")
        assert results == []

    def test_get_summary(self):
        from services.gdrive_service import init_folder_structure, upload_receipt
        from services.gdrive_index_service import get_summary

        init_folder_structure("2026-02")

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff" * 500)
            tmp = f.name
        run(upload_receipt(tmp, "2026-02", "Test"))
        os.unlink(tmp)

        summary = get_summary("2026-02")
        assert summary["total_files"] == 1
        assert summary["total_size"] > 0
        assert summary["folders"]["收據憑證"]["count"] == 1


class TestEndToEnd:
    """完整端到端流程驗證"""

    def test_full_receipt_lifecycle(self):
        """模擬：上傳收據 → 歸檔到採購單據 → 更新索引 → 搜尋"""
        from services.gdrive_service import (
            init_folder_structure, upload_receipt,
            get_folder_index, _year_month_path, GDRIVE_LOCAL,
        )
        from services.gdrive_index_service import update_index, search_index, get_summary

        ym = "2026-02"
        init_folder_structure(ym)

        # 1. 上傳收據（模擬 photo_handler）
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff" + b"\x00" * 200)
            receipt_path = f.name

        gdrive_rel = run(upload_receipt(receipt_path, ym, "萬客隆超市"))
        assert gdrive_rel is not None

        # 2. 確認後歸檔到採購單據（模擬 command_handler）
        _, month_path = _year_month_path(ym)
        dest_dir = os.path.join(month_path, "採購單據")
        os.makedirs(dest_dir, exist_ok=True)
        basename = os.path.basename(receipt_path)
        dest = os.path.join(dest_dir, f"萬客隆超市_{basename}")
        shutil.copy2(receipt_path, dest)
        os.unlink(receipt_path)

        # 3. 更新索引
        idx = update_index(ym)
        assert idx["months"][ym]["total_files"] == 2  # 收據+採購

        # 4. 搜尋
        results = search_index("萬客隆")
        assert len(results) == 2  # 收據和採購各一份

        # 5. 統計
        summary = get_summary(ym)
        assert summary["total_files"] == 2
        assert summary["folders"]["收據憑證"]["count"] == 1
        assert summary["folders"]["採購單據"]["count"] == 1

    def test_multi_export_types(self):
        """模擬多種匯出類型"""
        from services.gdrive_service import init_folder_structure, upload_export
        from services.gdrive_index_service import update_index

        ym = "2026-01"
        init_folder_structure(ym)

        exports = [
            ("monthly", "2026-01", ".xlsx", b"MONTHLY"),
            ("mof_txt", "2026-01-02", ".txt", b"MOF_DATA"),
            ("accounting", "2026-01-02", ".xlsx", b"ACCT"),
        ]

        for etype, period, ext, data in exports:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                f.write(data)
                tmp = f.name
            rel = run(upload_export(tmp, etype, period))
            assert rel is not None, f"Failed for {etype}"
            os.unlink(tmp)

        idx = update_index(ym)
        assert idx["months"][ym]["total_files"] == 3
