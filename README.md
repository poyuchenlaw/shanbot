# Shanbot (小膳) — 餐飲業 AI 內帳助手

> 拍發票、算菜成本、出月結報表、報稅匯出 — 全部在 LINE 上完成。

Shanbot 是一個開源的 LINE Bot，專為團膳公司與小型餐飲業者設計。透過 AI 驅動的發票 OCR、智慧菜單管理、自動財務報表，幫助餐飲業者從每天的紙本作業中解放出來。

## 功能一覽

| 功能 | 說明 |
|------|------|
| **發票/收據 OCR** | 拍照即辨識 — 三引擎自動切換（PaddleOCR → Gemini VLM → HunyuanOCR） |
| **菜單管理** | AI 菜單建議 + 食材成本自動計算 |
| **財務報表** | 月結 / 年結報表一鍵生成（符合中小企業會計準則） |
| **稅務匯出** | 報稅季資料自動整理匯出，省下數十小時人工 |
| **市場行情** | 食材價格自動同步，即時掌握成本波動 |
| **GDrive 歸檔** | 發票照片自動重命名、分類歸檔到 Google Drive |
| **LINE 六宮格選單** | 直覺操作介面，不需要學任何指令 |

## 快速開始

### 前置需求

- Python 3.10+
- LINE Messaging API Channel（[申請教學](https://developers.line.biz/en/docs/messaging-api/getting-started/)）
- Google Gemini API Key（OCR 備援 + AI 功能）

### 安裝

```bash
git clone https://github.com/poyuchenlaw/shanbot.git
cd shanbot
pip install -r requirements.txt
```

### 設定

複製環境變數範本並填入你的金鑰：

```bash
cp config/.env.example config/.env
```

必填欄位：

```env
# LINE Bot
LINE_CHANNEL_SECRET=your_channel_secret
LINE_CHANNEL_ACCESS_TOKEN=your_access_token

# AI (OCR + 智慧功能)
GEMINI_API_KEY=your_gemini_key

# Google Drive (選填，用於自動歸檔)
GDRIVE_FOLDER_ID=your_folder_id
```

### 啟動

```bash
# 直接啟動
python main.py

# 或用 PM2 管理（推薦）
pm2 start ecosystem.config.js
```

Bot 會在 `http://localhost:8025` 啟動，將此 URL 設定為 LINE Webhook 即可使用。

## 架構

```
shanbot/
├── main.py                → FastAPI webhook 入口 (port 8025)
├── state_manager.py       → SQLite 資料管理
├── task_manager.py        → 排程器 (心跳 + 市場同步 + 月結)
├── handlers/
│   ├── command_handler.py → 指令路由
│   ├── photo_handler.py   → 發票/收據拍照 OCR
│   ├── menu_handler.py    → 菜單管理對話
│   ├── file_handler.py    → 檔案上傳處理
│   └── postback_handler.py → LINE Postback 處理
├── services/
│   ├── ocr_service.py     → 三引擎 OCR (PaddleOCR + Gemini + Hunyuan)
│   ├── financial_report_service.py → 四大財務報表
│   ├── tax_export_service.py → 稅務匯出
│   ├── market_service.py  → 食材行情同步
│   ├── menu_ai_service.py → AI 菜單建議
│   ├── gdrive_service.py  → Google Drive 歸檔
│   ├── flex_builder.py    → LINE Flex Message 模板
│   └── richmenu_service.py → LINE Rich Menu 管理
└── tests/                 → 測試
```

## 技術特色

### 三引擎 OCR 自動降級

```
拍照 → PaddleOCR PP-OCRv5（本地，最快）
       ↓ 失敗
       Gemini VLM（雲端，最準）
       ↓ 失敗
       HunyuanOCR via HF Inference（備援）
```

每張發票自動選擇最佳引擎，確保辨識成功率。

### AI 驅動的智慧功能

- **Claude CLI Bridge** — 接入 Claude 做自然語言理解
- **3-Tier LLM Fallback** — Claude CLI → LLM Router → Gemini
- **食材成本計算** — 根據菜單自動計算每道菜的食材成本
- **稅務分類** — 發票自動分類為可扣抵/不可扣抵

### 排程自動化

| 排程 | 頻率 | 功能 |
|------|------|------|
| HeartbeatScheduler | 每小時 | 系統健康檢查 |
| MarketSyncScheduler | 每日 | 食材行情同步 |
| MonthlySummaryScheduler | 每月 | 月結報表自動生成 |

## 誰適合用？

- 團膳公司（每天大量採購單、發票）
- 小型餐廳（老闆兼會計，沒時間整理帳）
- 早餐店 / 便當店（簡單記帳 + 成本控制）
- 任何需要在 LINE 上管理餐飲財務的人

## 報稅省時效果

| 傳統方式 | 使用小膳 |
|---------|---------|
| 每天手動輸入發票 30 分鐘 | 拍照 3 秒自動辨識歸檔 |
| 月底整理帳目 2-3 小時 | 一鍵生成月結報表 |
| 報稅季整理 2-3 天 | 稅務匯出 1 分鐘完成 |
| **每月耗時 ~20 小時** | **每月耗時 ~1 小時** |

## Roadmap

- [x] v1.0 — 基礎 OCR + 菜單 + 財務報表
- [x] v2.0 — LINE 六宮格介面 + 市場行情 + 稅務匯出
- [x] v2.3 — 稅務扣抵自動分類 + 菜單行銷海報
- [x] v2.4 — 拍照記帳五項修復 + GDrive 歸檔強化
- [ ] v3.0 — 食材主表建立 + 價格比對警報
- [ ] v3.1 — Docker 一鍵部署
- [ ] v3.2 — 多店管理（一個 Bot 管多家店）
- [ ] v4.0 — 電子發票 API 串接（免拍照）

## 授權

MIT License — 免費使用、修改、商用。

## 關於

由[廣信法律會計事務所](https://kuangshin.tw)開發維護。我們相信好的工具應該免費給大家用。

如果你是餐飲業者，除了帳務問題，遇到勞資糾紛、食安法規、租賃合約等法律問題，也歡迎聯繫我們。

---

*Built with FastAPI + PaddleOCR + LINE Messaging API + Claude AI*
