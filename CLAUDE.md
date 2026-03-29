# 小善 BOT (shanbot) — 團膳內帳系統

## 專案概要

五家團膳公司的內帳系統，透過 LINE Bot 收據拍照 → OCR 辨識 → 記帳 → 歸檔 → 報表。

- **架構**：Python 3.10 + FastAPI + SQLite（WAL）+ LINE Messaging API
- **PM2 服務**：`shanbot` port 8025
- **外部 URL**：`https://shanbot.kuangshin.tw`
- **資料庫**：`data/shanbot.db`（22 表，複式簿記）
- **GDrive**：`/mnt/h/我的雲端硬碟/小魚資料/團膳公司資料/{公司}/`

## 五家公司

| ID | 簡稱 | 全名 | 統編 | GDrive 資料夾 |
|----|------|------|------|--------------|
| 1 | 福利社 | 升鼎商行 | 81410187 | 福利社/ |
| 2 | 王凱 | 王凱食品有限公司 | 90438334 | 王凱/ |
| 3 | 台達2廠 | 升鼎商行 | 81410187 | 台達2廠/ |
| 4 | 富燚 | 富燚商行 | 00281384 | 富燚/ |
| 5 | 台達1廠 | 升鼎商行 | 81410187 | 台達1廠/ |

## 核心流程

```
照片上傳 (LINE)
  → photo_handler.handle_photo_received()
  → SHA256 去重
  → OCR 三引擎（PaddleOCR → Gemini VLM → HunyuanOCR）
  → 稅務自動分類（三聯/二聯/電子/免用 → 扣抵代號）
  → purchase_staging 暫存（status=pending）
  → 使用者確認（好/修改/捨棄）
  → confirm → 傳票分錄（借：進貨+進項稅額 / 貸：現金）
  → verify_balance() 借貸平衡檢查
  → GDrive 歸檔（重新命名 YYMMDD_供應商_金額_#ID.jpg）
  → 供應商子資料夾分類 + INDEX.csv 索引更新
```

## CLI 工具

### 批次 OCR 辨識 + 重新命名
```bash
python3 tools/batch_rename_receipts.py --dry-run    # 預覽模式
python3 tools/batch_rename_receipts.py --limit 50    # 批次處理 50 張
python3 tools/batch_rename_receipts.py               # 全部處理
```

### 收據整理（分類到供應商子資料夾）
```bash
bash tools/organize_receipts.sh "/mnt/h/.../團膳公司資料/{公司}/2026/03月/收據憑證"
```

### Rich Menu 部署
```bash
python3 scripts/deploy_richmenu.py
```

### 直接操作資料庫
```bash
# 查看待確認單據
sqlite3 data/shanbot.db "SELECT id, company_id, supplier_name, total_amount, status FROM purchase_staging WHERE status='pending' LIMIT 20"

# 查看借貸平衡
sqlite3 data/shanbot.db "SELECT year_month, SUM(debit) as 借方, SUM(credit) as 貸方, CASE WHEN ABS(SUM(debit)-SUM(credit))<2 THEN '✅' ELSE '❌' END as 平衡 FROM journal_entries GROUP BY year_month"

# 查看各公司單據數量
sqlite3 data/shanbot.db "SELECT company_id, status, COUNT(*) FROM purchase_staging GROUP BY company_id, status"

# 查看會計科目表
sqlite3 data/shanbot.db "SELECT code, name, normal_side FROM chart_of_accounts ORDER BY code"
```

### Python API（在 shanbot 目錄下執行）
```python
import sys; sys.path.insert(0, '.')
import state_manager as sm
sm.init_db()

# 查待確認
pending = sm.get_pending_stagings(company_id=1)

# 確認單據
sm.confirm_staging(staging_id)

# 生成傳票
from services.accounting_service import generate_journal_entries, verify_balance
generate_journal_entries(staging_id)
result = verify_balance(staging_id)  # {'balanced': True, 'debit': 3500, 'credit': 3500}

# 生成報表
from services.financial_report_service import generate_balance_sheet, generate_income_statement
generate_balance_sheet("2026-03", output_dir="/tmp")
generate_income_statement("2026-03", output_dir="/tmp")

# 稅務匯出
from services.tax_export_service import export_mof_txt, export_accounting_excel
export_mof_txt("2026-01-02", output_dir="/tmp")  # 期間: YYYY-MM 雙月
export_accounting_excel("2026-01-02", output_dir="/tmp")

# 月結
from services.report_service import generate_monthly_report
generate_monthly_report("2026-03", output_dir="/tmp")
```

## GDrive 資料夾結構

```
/mnt/h/我的雲端硬碟/小魚資料/團膳公司資料/
├── {公司}/
│   └── 2026/
│       └── 03月/
│           ├── 收據憑證/{供應商}/YYMMDD_供應商_金額_#ID.jpg + INDEX.csv
│           ├── 待確認/（未確認暫存）
│           ├── 採購單據/
│           ├── 月報表/
│           ├── 稅務匯出/
│           ├── 會計資料/
│           ├── 財務報表/
│           ├── 薪資表/
│           ├── 菜單企劃/
│           ├── 租約與合約/
│           └── INDEX_總覽.csv
```

## 會計科目（EAS）

```
1xxx 資產    1100 現金 | 1150 進項稅額 | 1200 應收帳款 | 1300 存貨 | 1500 固定資產
2xxx 負債    2100 應付帳款 | 2150 銷項稅額 | 2200 應付薪資
3xxx 權益    3100 資本額 | 3200 累積盈虧 | 3300 本期損益
4xxx 收入    4100 營業收入
5xxx 成本    5110 進貨（食材）| 5120 直接人工 | 5130 製造費用
6xxx 費用    6110 薪資 | 6120 租金 | 6130 水電 | 6160 折舊
```

## 傳票分錄規則

| 交易類型 | 借方 | 貸方 |
|---------|------|------|
| 進貨（可扣抵）| 進貨 5110 + 進項稅額 1150 | 現金 1100 |
| 進貨（不可扣）| 進貨 5110（含稅）| 現金 1100 |
| 營業收入 | 現金 1100 | 營收 4100 + 銷項稅額 2150 |
| 薪資 | 薪資 6110 + 勞健保 6200 + 勞退 6210 | 現金 1100 + 代扣稅 2310 |
| 折舊 | 折舊費用 6160 | 累計折舊 1500 |

## 稅務分類邏輯

| 條件 | 格式代號 | 扣抵代號 | 說明 |
|------|---------|---------|------|
| 有統編 + 三聯式 | 21 | 1 | 可扣抵 |
| 有統編 + 電子發票 | 25 | 1 | 可扣抵 |
| 有統編 + 二聯式 | 22 | 2 | 不可扣抵 |
| 無統編 / 免用發票 | 22 | 2 | 不可扣抵 |

## 開發注意事項

- 所有 DB 查詢必須帶 `company_id`（多租戶隔離）
- OCR 結果 confidence < 60% 標記為 REJECT，需人工確認
- 借貸不平衡容忍 $1（四捨五入差）
- GDrive 路徑不可寫時 → 自動切換 staging 暫存路徑 `data/gdrive_staging/`
- `verify_signature()` 用簽名比對決定是哪家公司的 webhook
- LINE 免費帳號每月 200 則回覆限制
- 修改後務必 `pm2 restart shanbot`
- 測試：`cd /home/simon/shanbot && python3 -m pytest tests/ -q`
