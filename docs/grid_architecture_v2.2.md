# 小膳 Bot v2.2 — 六宮格架構報告

> 更新日期：2026-02-18
> 版本：v2.2.0（財務資料上傳 + 四大報表生成 + 拍照訣竅 Carousel）

---

## 總覽：六宮格 Rich Menu

```
┌──────────────┬──────────────┬──────────────┐
│  格子 1       │  格子 2       │  格子 3       │
│  📸 拍照記帳  │  📁 財務資料  │  🛒 採購管理   │
│              │  提供和確認   │              │
├──────────────┼──────────────┼──────────────┤
│  格子 4       │  格子 5       │  格子 6       │
│  🍽️ 菜單企劃 │  📊 報表生成  │  ❓ 使用說明   │
└──────────────┴──────────────┴──────────────┘
```

每個格子的 Rich Menu action 皆為 `type: postback`，點擊後觸發 `postback_handler.py` 分發邏輯。

---

## 格子 1：📸 拍照記帳

### Postback 資料
```
data: "menu=camera"
displayText: "📸 拍照記帳"
```

### 觸發流程
```
用戶點擊 Grid #1
  → LINE 發送 postback event（data="menu=camera"）
  → main.py: _handle_postback()
  → postback_handler.py: handle_postback() → _handle_menu("camera")
  → flex_builder.py: build_camera_menu()
  → 回覆 Carousel Flex（3 卡）
```

### Flex 結構：3 卡 Carousel

| 卡片 | 標題 | 內容 |
|------|------|------|
| Card 1 | 📸 拍照訣竅 | 5 個拍照要領：光線充足、平放桌面、對焦清晰、四角入鏡、穩定拍攝 |
| Card 2 | 🤖 辨識流程 | 4 步驟說明：AI 辨識 → 信心度判定（🟢🟡🔴）→ 不清楚追問 → 確認入帳 |
| Card 3 | 📷 開始拍照 | 相機按鈕 + 相簿按鈕 + 拍照前確認清單 |

### 拍照後流程（用戶傳圖片觸發，非 postback）
```
用戶傳圖片
  → main.py: _process_event() → msg_type == "image"
  → _handle_image() → photo_handler.py: handle_photo_received()
  → 下載圖片 → SHA256 → 存 data/files/
  → 上傳 GDrive 收據憑證/
  → 建立 purchase_staging 暫存記錄
  → OCR 辨識（ocr_service.process_image）
  → 根據信心度：
      🟢 AUTO_PASS（高）→ 回覆 Flex 確認卡（build_review_flex）
      🟡 REVIEW（中）→ 回覆 Flex 確認卡 + 標記問題欄位
      🔴 REJECT（低）→ 文字回覆「辨識信心度過低，建議重拍」
  → 用戶按「確認」→ postback action=confirm → 入正式帳
  → 用戶按「修改」→ postback action=edit → 進入修改模式
  → 用戶按「捨棄」→ postback action=discard → 標記 discarded
```

### 子動作

| Postback Data | 功能 | 說明 |
|---------------|------|------|
| `action=confirm&id=N` | 快速確認 | 確認 OCR 結果入帳 |
| `action=edit&id=N` | 修改模式 | 設定 waiting_edit 狀態 |
| `action=discard&id=N` | 捨棄記錄 | 標記為 discarded |

---

## 格子 2：📁 財務資料提供和確認

### Postback 資料
```
data: "menu=finance_upload"
displayText: "📁 財務資料提供和確認"
```

### 觸發流程
```
用戶點擊 Grid #2
  → postback_handler: _handle_menu("finance_upload")
  → flex_builder.py: build_finance_upload_menu()
  → 回覆 Carousel Flex（4 卡）
```

### Flex 結構：4 卡 Carousel

| 卡片 | 標題 | 內容 |
|------|------|------|
| Card 1 | 📁 財務資料提供和確認 | 引導說明：上傳文件 → 自動分類 → 確認歸檔 |
| Card 2 | 📋 上傳文件 | 說明支援格式（Excel/PDF）+ 八大循環分類表 |
| Card 3 | 📂 已上傳文件 | 按鈕：查看本月文件 / 搜尋文件 |
| Card 4 | ✅ 確認與統計 | 按鈕：確認本月資料完整 / 文件統計 |

### 檔案上傳流程（用戶傳檔案觸發，非 postback）
```
用戶傳 Excel/PDF 檔案
  → main.py: _process_event() → msg_type == "file"
  → _handle_file() → file_handler.py: handle_file_received()
  → 下載檔案 → 存到 data/files/
  → 內容檢視（v2.2 新增）：
      Excel: openpyxl 讀取 sheet 名稱、前 10 行標題、cell 內容
      PDF: PyMuPDF 讀取前 3 頁文字
  → 智能分類（優先級：內容分析 > 檔名關鍵字 > 預設）
  → 智能重命名：YYYYMM_分類短名_原始檔名.xlsx
  → 記錄到 financial_documents 表
  → 上傳 GDrive 對應分類資料夾：
      payroll → 薪資表/
      general → 租約與合約/
      expenditure → 採購單據/
      其他 → 會計資料/
  → 回覆 Flex 歸檔結果（含分類依據、偵測關鍵字）
  → 用戶按「確認」或「修改分類」
```

### 八大循環分類

| doc_category | 中文 | GDrive 子資料夾 |
|--------------|------|----------------|
| revenue | 收入循環 | 會計資料/ |
| expenditure | 支出循環 | 採購單據/ |
| payroll | 人力資源循環 | 薪資表/ |
| production | 生產循環 | 會計資料/ |
| financing | 融資循環 | 會計資料/ |
| investment | 投資循環 | 會計資料/ |
| fixed_asset | 固定資產循環 | 會計資料/ |
| general | 一般循環 | 租約與合約/ |

### 子動作

| Postback Data | 功能 | 說明 |
|---------------|------|------|
| `action=finance_docs&cmd=list` | 查看本月文件 | 列出本月所有已上傳文件 |
| `action=finance_docs&cmd=search` | 搜尋文件 | 設定 waiting_finance_search 狀態 |
| `action=finance_docs&cmd=confirm_month` | 確認本月 | 所有文件標記 confirmed |
| `action=finance_docs&cmd=summary` | 文件統計 | 八大循環各類數量統計 |
| `action=file_confirm&id=N` | 確認分類 | 標記單一文件 confirmed |
| `action=file_reclassify&id=N` | 修改分類 | 顯示八大循環選擇 Flex |
| `action=file_set_category&id=N&cat=X` | 設定分類 | 變更文件分類 |

---

## 格子 3：🛒 採購管理

### Postback 資料
```
data: "menu=purchase"
displayText: "🛒 採購管理"
```

### 觸發流程
```
用戶點擊 Grid #3
  → postback_handler: _handle_menu("purchase")
  → 查詢 pending_count = len(sm.get_pending_stagings())
  → flex_builder.py: build_purchase_menu(pending_count)
  → 回覆 Bubble Flex（1 卡 + 按鈕群）
```

### Flex 結構：1 卡 Bubble

| 區塊 | 內容 |
|------|------|
| Header | 🛒 採購管理 |
| Body 引導 | 3 步驟：拍照上傳 → 確認待處理 → 查看比價 |
| 按鈕 | 📝 查看待處理（含筆數 badge） |
| 按鈕 | 📊 市場行情 / 🏪 供應商（水平排列） |
| 按鈕 | 📦 食材價格對照表 |

### 子動作

| Postback Data | 功能 | 說明 |
|---------------|------|------|
| `action=purchase&cmd=pending` | 待處理清單 | 顯示所有 pending 的 purchase_staging |
| `action=purchase&cmd=market` | 市場行情 | 查詢農產品行情（market_service） |
| `action=purchase&cmd=suppliers` | 供應商列表 | 所有供應商 Flex 清單 |
| `action=purchase&cmd=price_compare` | 價格對照 | 進貨價 vs 市場行情對比 |

---

## 格子 4：🍽️ 菜單企劃

### Postback 資料
```
data: "menu=menu_plan"
displayText: "🍽️ 菜單企劃"
```

### 觸發流程
```
用戶點擊 Grid #4
  → postback_handler: _handle_menu("menu_plan")
  → flex_builder.py: build_menu_plan_menu()
  → 回覆 Carousel Flex（4 卡）
```

### Flex 結構：4 卡 Carousel

| 卡片 | 標題 | 內容 |
|------|------|------|
| Card 1 | 🍽️ 菜單企劃 | 引導說明：查看/編輯菜單、生成圖片、成本試算 |
| Card 2 | 🍽️ 本月菜單確認 | 按鈕：查看菜單 / 編輯菜單 |
| Card 3 | 🎨 菜色文宣圖片 | 按鈕：生成菜色圖片（AI 圖片生成） |
| Card 4 | 🧮 食材成本試算 | 按鈕：開始試算（輸入菜名或食材清單） |

### 子動作

| Postback Data | 功能 | 說明 |
|---------------|------|------|
| `action=menu&cmd=view_current` | 查看本月菜單 | 顯示當月菜單安排 |
| `action=menu&cmd=edit` | 編輯菜單 | 設定 waiting_menu_edit 狀態 |
| `action=menu&cmd=gen_image` | 生成菜色圖片 | 設定 waiting_dish_name 狀態 |
| `action=menu&cmd=cost_calc` | 成本試算 | 設定 waiting_cost_input 狀態 |

---

## 格子 5：📊 報表生成

### Postback 資料
```
data: "menu=reports"
displayText: "📊 報表生成"
```

### 觸發流程
```
用戶點擊 Grid #5
  → postback_handler: _handle_menu("reports")
  → flex_builder.py: build_reports_menu()
  → 回覆 Carousel Flex（3 卡）
```

### Flex 結構：3 卡 Carousel

| 卡片 | 標題 | 內容 |
|------|------|------|
| Card 1 | 📊 報表生成 | 引導說明：選類型 → 選期間 → 自動生成 + 雲端同步 |
| Card 2 | 📊 四大財務報表 | 按鈕：資產負債表 / 損益表 / 現金流量表 / 權益變動表 |
| Card 3 | 📤 匯出功能 | 按鈕：月報表 / 年報表 / 稅務申報檔 / 會計匯出 / 經手人憑證 |

### 四大報表生成流程
```
用戶按「資產負債表」
  → postback: action=gen_report&type=balance_sheet
  → _handle_gen_report_select() → build_report_period_picker("balance_sheet")
  → 用戶選期間（本月/上月/上上月）
  → postback: action=do_gen_report&type=balance_sheet&period=2026-02
  → _handle_do_gen_report()
  → financial_report_service.generate_balance_sheet("2026-02")
  → 生成 Excel（openpyxl）→ data/exports/2026-02/
  → 上傳 GDrive 財務報表/
  → 回覆路徑
```

### 匯出功能流程
```
用戶按「月報表」
  → postback: action=export&type=monthly
  → _handle_export_select() → build_export_period_picker("monthly")
  → 用戶選期間
  → postback: action=do_export&type=monthly&period=2026-02
  → _handle_do_export()
  → report_service.generate_monthly_report("2026-02")
  → 生成 Excel → 上傳 GDrive 月報表/
```

### 子動作

| Postback Data | 功能 | 說明 |
|---------------|------|------|
| `action=gen_report&type=balance_sheet` | 資產負債表 | 先選期間 |
| `action=gen_report&type=income_statement` | 損益表 | 先選期間 |
| `action=gen_report&type=cash_flow` | 現金流量表 | 先選期間 |
| `action=gen_report&type=equity_changes` | 權益變動表 | 先選期間 |
| `action=do_gen_report&type=X&period=Y` | 實際生成報表 | 生成 + GDrive |
| `action=export&type=monthly` | 月報表匯出 | 先選期間 |
| `action=export&type=annual` | 年報表匯出 | 先選期間 |
| `action=export&type=mof_txt` | 稅務申報 TXT | 先選期間 + 驗證 |
| `action=export&type=accounting` | 會計系統匯出 | 先選期間 |
| `action=export&type=handler_cert` | 經手人憑證 | 先選期間 |
| `action=do_export&type=X&period=Y` | 實際匯出 | 生成 + GDrive |

---

## 格子 6：❓ 使用說明

### Postback 資料
```
data: "menu=guide"
displayText: "❓ 使用說明"
```

### 觸發流程
```
用戶點擊 Grid #6
  → postback_handler: _handle_menu("guide")
  → flex_builder.py: build_guide_menu()
  → 回覆 Carousel Flex（6 卡）
```

### Flex 結構：6 卡 Carousel

| 卡片 | 標題 | 內容 |
|------|------|------|
| Card 1 | ⚡ 快速開始 | 3 步驟：拍照 → 確認 → 報表。按鈕：拍照記帳 |
| Card 2 | 📸 拍照記帳步驟 | 5 步：開啟相機 → 拍照 → 等待辨識 → 確認 → 完成 |
| Card 3 | 👥 財務群組使用指南（v2.2 新增）| 群組 vs 一對一使用時機說明 |
| Card 4 | 📋 各功能操作說明 | 六宮格每個功能的簡述 |
| Card 5 | ❓ 常見問題 | FAQ：如何修改/手寫可以嗎/上傳檔案去哪/支援格式 |
| Card 6 | ℹ️ 關於小膳 | 版本 v2.2.0 + 開發者資訊 |

---

## GDrive 資料夾結構

```
團膳公司資料/
├── 2026/
│   ├── 01月/
│   │   ├── 收據憑證/        ← 拍照記帳的收據照片
│   │   ├── 採購單據/        ← expenditure 類文件
│   │   ├── 月報表/          ← 月報表匯出
│   │   ├── 稅務匯出/        ← MOF TXT + 會計匯出
│   │   ├── 菜單企劃/        ← 菜單相關
│   │   ├── 薪資表/          ← payroll 類文件（v2.2）
│   │   ├── 租約與合約/      ← general 類文件（v2.2）
│   │   ├── 會計資料/        ← revenue/financing/investment/fixed_asset/production（v2.2）
│   │   └── 財務報表/        ← 四大報表輸出（v2.2）
│   ├── 02月/
│   │   └── ...（同上）
│   └── 年度報表/
│       └── 食材價格對照/
```

---

## DB 表一覽（15 張）

| 表名 | 用途 | 關鍵格子 |
|------|------|---------|
| config | 系統設定 | 全域 |
| suppliers | 供應商主檔 | #3 |
| ingredients | 食材主檔 | #3、#4 |
| purchase_staging | 採購暫存（OCR） | #1、#3 |
| purchase_items | 採購明細 | #1、#3 |
| income | 收入記錄 | #5 |
| monthly_cost | 月度固定成本 | #5 |
| recipes | 食譜 | #4 |
| recipe_ingredients | 食譜食材 | #4 |
| menu_schedule | 菜單排程 | #4 |
| market_prices | 市場行情 | #3 |
| price_alerts | 價格警報 | #3 |
| conversation_state | 對話狀態 | 全域 |
| image_generation_log | 圖片生成紀錄 | #4 |
| financial_documents | 財務文件索引（v2.2）| #2 |

---

## 檔案對照表

| 檔案 | 職責 |
|------|------|
| `main.py` | FastAPI 入口、webhook 處理、事件分發 |
| `handlers/postback_handler.py` | 所有 postback 路由分發（29 個路由） |
| `handlers/photo_handler.py` | 照片 OCR 辨識流程 |
| `handlers/file_handler.py` | 檔案上傳內容檢視分類歸檔（v2.2 強化） |
| `handlers/command_handler.py` | 文字指令處理 |
| `services/flex_builder.py` | 所有 Flex Message 模板工廠（1300+ 行） |
| `services/line_service.py` | LINE API 封裝（reply、push、get_content） |
| `services/richmenu_service.py` | Rich Menu CRUD + 部署 |
| `services/gdrive_service.py` | GDrive 本地同步資料夾操作 |
| `services/ocr_service.py` | OCR 辨識引擎 |
| `services/report_service.py` | 月報/年報生成 |
| `services/financial_report_service.py` | 四大財務報表生成（v2.2） |
| `services/tax_export_service.py` | 稅務匯出（MOF TXT、會計 Excel、經手人 PDF） |
| `services/market_service.py` | 農產品行情查詢 |
| `state_manager.py` | SQLite ORM（15 張表、60+ CRUD 函數） |
| `task_manager.py` | 排程器（心跳、行情同步、月結） |

---

## v2.2 改動摘要

| 項目 | 改動 |
|------|------|
| Grid #1 拍照 | 從 1 卡 Bubble → 3 卡 Carousel（訣竅 + 流程 + 拍照） |
| Grid #2 財務 | 從「財務總覽」→「財務資料提供和確認」（4 卡 Carousel） |
| Grid #5 報表 | 從「匯出中心」→「報表生成」（3 卡 Carousel + 四大報表） |
| Grid #6 使用說明 | 新增「財務群組使用指南」卡片（5→6 卡） |
| 檔案上傳 | 內容檢視（Excel headers + PDF 文字）→ 智能分類 + 重命名 |
| DB | 新增 financial_documents 表（第 15 張） |
| GDrive | 新增 4 個月度子資料夾（薪資表/租約與合約/會計資料/財務報表） |
| 測試 | 610 個測試全數通過 |
