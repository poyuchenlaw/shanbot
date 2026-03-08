# 小膳 Shanbot — AI 團膳內帳管理系統

> 拍發票、算菜成本、出月結報表、報稅匯出 — 全部在 LINE 上完成。

Shanbot 是一個開源的 LINE Bot，專為團膳公司與小型餐飲業者設計。透過 AI 驅動的發票 OCR、智慧菜單管理、自動財務報表，幫助餐飲業者從每天的紙本作業中解放出來。

## 功能一覽

| 功能 | 說明 |
|------|------|
| **拍照記帳（OCR）** | 拍照即辨識收據/發票 — 三引擎自動切換（PaddleOCR PP-OCRv5 → Gemini VLM → HunyuanOCR） |
| **財務報表** | 月結 / 年結 / 資產負債表 / 損益表，一鍵生成（符合中小企業會計準則） |
| **採購管理** | 供應商資料管理、食材行情自動同步、比價分析 |
| **菜單企劃** | AI 菜單建議 + 成本估算 + 行銷海報圖片生成 |
| **稅務匯出** | MOF 格式 / 會計軟體格式，報稅季資料自動整理，扣抵自動分類 |
| **GDrive 歸檔** | 發票照片自動重命名、分類歸檔到 Google Drive |
| **LINE 六宮格選單** | 拍照記帳 / 財務資料 / 採購管理 / 菜單企劃 / 報表生成 / 使用說明 |

## 系統架構

```
LINE Messaging API
       │
       ▼
  FastAPI (port 8025)  ←── PM2 process manager
       │
       ├── handlers/          → 指令路由 + 拍照 + 菜單對話 + Postback
       ├── services/          → OCR + 財報 + 稅務 + 行情 + AI + GDrive
       ├── state_manager.py   → SQLite 資料管理
       └── task_manager.py    → 排程器 (心跳 + 市場同步 + 月結)

LLM 三層降級：
  Claude Code CLI → llm-router (Gemini/Groq fallback) → Gemini Direct API

OCR 三引擎：
  PaddleOCR PP-OCRv5（本地，最快）
       ↓ 失敗
  Gemini VLM（雲端，最準）
       ↓ 失敗
  HunyuanOCR via HF Inference（備援）

部署：
  PM2 + Cloudflare Tunnel (HTTPS) → LINE Webhook
```

## 專案結構

```
shanbot/
├── main.py                → FastAPI webhook 入口 (port 8025)
├── state_manager.py       → SQLite 資料管理
├── task_manager.py        → 排程器 (心跳 + 市場同步 + 月結)
├── ecosystem.config.js    → PM2 設定檔
├── handlers/
│   ├── command_handler.py → 指令路由
│   ├── photo_handler.py   → 發票/收據拍照 OCR
│   ├── menu_handler.py    → 菜單管理對話
│   ├── file_handler.py    → 檔案上傳處理
│   └── postback_handler.py → LINE Postback 處理
├── services/
│   ├── ocr_service.py     → 三引擎 OCR (PaddleOCR + Gemini + Hunyuan)
│   ├── financial_report_service.py → 四大財務報表
│   ├── tax_export_service.py → 稅務匯出 (MOF + 會計軟體)
│   ├── market_service.py  → 食材行情同步
│   ├── menu_ai_service.py → AI 菜單建議
│   ├── gdrive_service.py  → Google Drive 歸檔
│   ├── flex_builder.py    → LINE Flex Message 模板
│   └── richmenu_service.py → LINE Rich Menu 管理
├── config/
│   ├── .env               → 環境變數（不入版控）
│   └── .env.example       → 環境變數範本
└── tests/                 → 測試
```

## 自行部署指南

### 前置條件

1. **Linux / WSL2 環境**（PaddleOCR 需要 Linux）
2. **Python 3.10+**
3. **Node.js 18+**（用於 PM2 進程管理）
4. **Claude Code CLI**（`npm install -g @anthropic-ai/claude-code`，需 Anthropic API Key 或 Claude Pro/Max 訂閱）
5. **LINE Messaging API 帳號**（至 [LINE Developers Console](https://developers.line.biz/console/) 建立 Channel）
6. **Cloudflare Tunnel**（或其他 HTTPS 反向代理，如 ngrok）

### 安裝

```bash
git clone https://github.com/poyuchenlaw/shanbot.git
cd shanbot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 設定環境變數

```bash
cp config/.env.example config/.env
```

用文字編輯器打開 `config/.env`，填入你的金鑰（詳見下方[環境變數說明](#環境變數說明)）。

### 啟動

```bash
# 直接啟動
python main.py

# 或用 PM2 管理（推薦，自動重啟 + 日誌管理）
npm install -g pm2
pm2 start ecosystem.config.js
pm2 save
```

Bot 會在 `http://localhost:8025` 啟動。

### 設定 Webhook

1. 用 Cloudflare Tunnel 或 ngrok 將 HTTPS 流量轉發到 `localhost:8025`
2. 在 [LINE Developers Console](https://developers.line.biz/console/) 設定 Webhook URL 為你的公開 HTTPS URL + `/webhook`
3. 驗證健康狀態：`curl http://localhost:8025/health` 應回傳 200

### 一鍵部署提示詞

安裝好 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 後，在專案目錄執行 `claude` 並貼上以下提示詞，即可自動完成部署：

```
請幫我部署小膳 Shanbot 內帳系統：
1. 建立 Python venv 並安裝 requirements.txt
2. 複製 config/.env.example 為 config/.env，提示我填入：
   - LINE_CHANNEL_SECRET 和 LINE_CHANNEL_ACCESS_TOKEN（從 LINE Developers Console 取得）
   - GEMINI_API_KEY（從 Google AI Studio https://aistudio.google.com/apikey 免費取得）
   （ADMIN_USER_ID 無需手動設定，第一位與 Bot 互動的使用者會自動成為管理員）
3. 初始化 SQLite 資料庫
4. 用 PM2 啟動服務：pm2 start ecosystem.config.js && pm2 save
5. 設定 Cloudflare Tunnel 或 ngrok 將 HTTPS 流量轉發到 localhost:8025
6. 在 LINE Developers Console 設定 Webhook URL 為你的公開 HTTPS URL + /webhook
7. 建立 Rich Menu（6 格：拍照記帳/財務資料/採購管理/菜單企劃/報表生成/使用說明）
8. 驗證：curl http://localhost:8025/health 應回傳 200
```

## 環境變數說明

| 變數 | 必填 | 說明 | 取得方式 |
|------|------|------|----------|
| `LINE_CHANNEL_ID` | 選填 | LINE Channel ID | [LINE Developers Console](https://developers.line.biz/console/) → Channel 基本設定 |
| `LINE_CHANNEL_SECRET` | **必填** | LINE Channel Secret | 同上 → Channel Secret |
| `LINE_CHANNEL_ACCESS_TOKEN` | **必填** | LINE Channel Access Token | 同上 → Messaging API → 發行 Long-lived Token |
| `GEMINI_API_KEY` | **必填** | Google Gemini API Key（OCR + AI 功能） | [Google AI Studio](https://aistudio.google.com/apikey)（免費額度） |
| `GEMINI_MODEL` | 選填 | Gemini 模型名稱 | 預設 `gemini-2.5-flash` |
| `LLM_ROUTER_URL` | 選填 | LLM Router 服務位址 | 自建 LLM Router，預設 `http://127.0.0.1:8010/chat` |
| `HUNYUAN_OCR_API_KEY` | 選填 | HunyuanOCR 備援引擎 Token | [Hugging Face Tokens](https://huggingface.co/settings/tokens) |
| `HUNYUAN_OCR_API_URL` | 選填 | HunyuanOCR API 端點 | 預設 `https://router.huggingface.co/hf-inference/models/tencent/HunyuanOCR` |
| `EINVOICE_APP_ID` | 選填 | 電子發票 API App ID | [財政部電子發票平台](https://www.einvoice.nat.gov.tw) 申請 |
| `EINVOICE_API_KEY` | 選填 | 電子發票 API Key | 同上 |
| `GDRIVE_LOCAL` | 選填 | Google Drive 本地同步路徑 | 安裝 Google Drive 桌面版後的本地掛載路徑 |
| `COMPANY_TAX_ID` | 選填 | 公司統一編號 | 用於稅務匯出 |
| `COMPANY_TAX_REG_NO` | 選填 | 公司稅籍編號 | 用於稅務匯出 |
| `COMPANY_NAME` | 選填 | 公司名稱 | 用於報表標題 |
| `PUBLIC_BASE_URL` | 選填 | 公開 HTTPS URL | 你的 Cloudflare Tunnel / ngrok 網址 |
| `PORT` | 選填 | 服務埠號 | 預設 `8025` |
| `DB_PATH` | 選填 | SQLite 資料庫路徑 | 預設 `./data/shanbot.db` |
| `LOG_LEVEL` | 選填 | 日誌等級 | `DEBUG` / `INFO` / `WARNING`，預設 `INFO` |

## 排程自動化

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

## 技術棧

Python / FastAPI / SQLite / PaddleOCR / LINE Messaging API / Claude Code / Gemini API / PM2

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

MIT License — 免費使用、修改、商用。詳見 [LICENSE](LICENSE)。

## 關於

由[廣信法律會計事務所](https://kuangshin.tw)開發維護。我們相信好的工具應該免費給大家用。

如果你是餐飲業者，除了帳務問題，遇到勞資糾紛、食安法規、租賃合約等法律問題，也歡迎聯繫我們。

---

*Built with FastAPI + PaddleOCR + LINE Messaging API + Claude AI + Gemini*
