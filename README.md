# 台股追蹤引擎 (TW Stock Tracker)

Python 後端 + Web 儀表板的台股追蹤引擎，資料來源全部是證交所 / 櫃買中心的公開 API，不需要金鑰。

## 功能

| 功能 | 說明 |
| --- | --- |
| 多追蹤池 | 任意數量的自訂清單，一檔股票可同時在多個清單；四個自動維護的系統清單（CRM 持有、CRM 觀察、掃描候選、今日警示）；首次加入自動補 6 個月日線與 20 個交易日籌碼 |
| 每日行情 | 收盤後自動抓日 K（開高低收量），計算 MA5/10/20/60/120、RSI、KD、MACD、布林通道 |
| 三大法人 | 外資、投信、自營商買賣超（張） |
| 融資融券 | 融資 / 融券餘額與單日增減（張） |
| 盤中即時報價 | 交易時段每 10 秒輪詢證交所 MIS 即時行情（上市 + 上櫃） |
| 警示引擎 | 價格突破 / 跌破、漲跌幅、均線交叉、站上/跌破均線、RSI、KD 交叉、爆量、法人連續買賣超、融資變動 |
| 通知 | Console、LINE Messaging API、Email (SMTP) |
| 盤面分化 | 全市場上漲/下跌/漲停/跌停家數與走勢、加權指數 vs 個股中位數、前 5 大成交佔比、類股強弱（平均/中位/官方類指數/N 日累計）、漲跌幅分布、領漲領跌與成交金額排行 |
| 選股掃描器 | 全市場 10 個因子（相對強弱、突破、量能、均線排列、外資/投信 5 日、外資連買、融資變化、分化盤逆勢、類股動能）百分位加權評分，4 種權重預設，訊號標籤，結果存檔可回測 |
| 統一介面 | Vite + React + TypeScript 前端，同一導覽列整合引擎與 Stock CRM 兩個後端 |
| REST API | 所有資料都有 JSON API，Stock CRM 的 MCP 也透過它取行情 |

## 帳號、多使用者與對外存取

系統給一家人用：每個人有自己的清單、警示、卡片、部位與通知，市場資料全部共用。

- **登入**：本機帳號 + 密碼（PBKDF2 雜湊），伺服器端 session、HttpOnly cookie（HTTPS 下自動 Secure），登入失敗限速。第一次啟動若沒有任何帳號，會用 `.env` 的 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 建管理員，沒設則建 `admin` 並把隨機密碼寫進日誌。
- **角色**：`admin` 可管理帳號、執行工作、測試通知、同步系統清單；`member` 只能用自己的資料。管理員在「帳號管理」頁建帳號、重設密碼、填每個人的 LINE 使用者 ID 與 Email（警示會推到本人）。
- **API 命名空間**：`/api/market/*` 通用層（登入即可讀）、`/api/me/*` 個人化層（自動依登入者過濾）、`/api/admin/*`、`/api/auth/*`、`/api/crm/*`（代理到 Stock CRM 並帶 `X-User-Id` / `X-User-Name` / `X-Facade-Token`）。舊的 `/api/*` 路徑仍可用。
- **對外**：兩個後端仍只綁 127.0.0.1。公開存取走 Cloudflare Tunnel（不開路由器埠、自帶 HTTPS）：

```powershell
scripts\tunnel_quick.ps1                                   # 測試用：臨時 trycloudflare.com 網址
scripts\tunnel_install.ps1 -Hostname stocks.你的網域.com -Start   # 正式：固定網址 + 開機自動啟動
```

可再加 Cloudflare Access 當外圍第二層；應用層身份仍以本機帳號為準。

```bash
python cli.py users create mom --name 媽媽 --line Uxxxxxxxx     # 建成員（會提示輸入密碼）
python cli.py users create drew --admin
python cli.py users passwd drew
python cli.py users list
```

## 統一介面：引擎 + Stock CRM

引擎與 [Stock CRM](../stockcrm)（供應鏈投資日誌）是兩個獨立後端，由同一個 React 前端整合：

```
瀏覽器 ──► 引擎 :8000 ──┬── /api/*        市場資料、警示、掃描、排程
                        ├── /api/crm/*    反向代理 ──► Stock CRM :8765 /api/*
                        └── /             web/dist（Vite + React + TypeScript）
```

- 前端只面對一個網址，沒有 CORS 問題；stockcrm 不需要任何修改，各自保有 repo、資料庫、CI 與 PR 流程。
- 分頁：引擎（追蹤池、盤面分化、選股掃描、警示、系統）與 CRM（看板、關係圖、早晨、提案），卡片抽屜可從任何頁面打開；抽屜分「概況」（基本介紹、AI 簡介與近期重點、最近狀況、新聞）與「我的論點與證據」兩個檢視，台股節點沒有卡片也能預覽並一鍵建卡。
- 身份橋接在前端：CRM 的 `TW:2330` ↔ 引擎的 `2330`（`web/src/lib/format.ts`）。
- 舊版純 HTML 儀表板仍在 <http://127.0.0.1:8000/legacy/>。
- CRM 位址可用 `.env` 的 `CRM_BASE_URL` 改（預設 `http://127.0.0.1:8765`）；CRM 離線時 `/api/crm/*` 回 502，`/api/health` 的 `crm.reachable` 會是 false。

```bash
# 前端開發（熱更新，/api 代理到 :8000）
cd web && npm install && npm run dev        # http://127.0.0.1:5173
# 正式建置，之後由引擎直接伺服
cd web && npm run build
```

## 快速開始

```bash
cd twstock-tracker
pip install -r requirements.txt
copy .env.example .env        # 視需要填入 LINE / Email 設定
cd web && npm install && npm run build && cd ..   # 統一前端（可略過，略過時 / 顯示舊版儀表板）
python cli.py serve           # http://127.0.0.1:8000
# 另開終端機啟動 Stock CRM（CRM 分頁才有資料）
cd ../stockcrm && python -m stockcrm.api          # http://127.0.0.1:8765
```

或直接：

```bash
uvicorn app.main:app --reload --port 8000
```

開啟 <http://127.0.0.1:8000>，在追蹤池輸入代號（例如 `2330`、`6488`、`0050`）加入。
API 文件（Swagger）在 <http://127.0.0.1:8000/docs>。

### CLI

```bash
python cli.py add 2330 --note 台積電   # 加入並補歷史
python cli.py list                     # 總覽
python cli.py update                   # 日線 + 法人 + 融資券 + 警示評估
python cli.py quote                    # 立即抓一次即時報價
python cli.py backfill 2330 --months 12
python cli.py flows --days 40          # 補 40 個交易日的全市場法人 / 融資券
python cli.py market --days 60         # 補 60 個交易日的全市場日線（盤面分化 / 掃描需要）
python cli.py screen --preset chips    # 執行選股掃描（balanced | momentum | chips | contrarian）
python cli.py alerts                   # 立即評估日線型警示
python cli.py notify-test
```

### 讓它無人值守（Windows 服務化）

排程器跑在伺服器程序裡，程序活著才會自動執行。`scripts/` 提供不需要管理員權限、不需要第三方工具的做法：用 Windows 工作排程器在登入時啟動一個監控迴圈，程序掛掉 5 秒內重啟，視窗隱藏。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\service_install.ps1 -WithCrm -Start   # 引擎 + Stock CRM，立刻啟動
powershell -ExecutionPolicy Bypass -File scripts\service_restart.ps1 [-Engine|-Crm]    # 更新程式碼後重啟
powershell -ExecutionPolicy Bypass -File scripts\service_stop.ps1 [-Engine|-Crm]       # 停止（任務 + 伺服器程序）
powershell -ExecutionPolicy Bypass -File scripts\service_uninstall.ps1                  # 移除兩個任務並停掉程序
```

- 任務名稱 `TWStock Engine`（8000）與 `TWStock CRM`（8765，可省略 `-WithCrm`）。CRM 只被啟動，程式碼不動。
- 請用 `service_stop.ps1` / `service_restart.ps1` 而不是直接 `Stop-ScheduledTask`：後者只會結束監控迴圈，伺服器程序會留下來佔住 port。監控迴圈每次啟動前也會回收佔用該 port 的舊程序，所以即使只重啟任務也會在幾秒內自我修復。
- 日誌：`data/logs/engine.log`（應用程式，5 MB × 5 輪替）、`supervisor.log`、`crm-supervisor.log`。
- 限制：任務在你登入的互動工作階段執行，電腦必須在排程時間保持開機且未休眠（電源選項把「睡眠」設為永不，或改用 VPS）。
- 通知只會送到 `.env` 裡設定好的管道，沒填 LINE / Email 時只有 console 與日誌。

### 資料健康

儀表板「系統」頁的「資料健康」區塊（`GET /api/health/data`）依發布時程檢查每張表：日線 / 盤面 15:00 後、三大法人 17:00 後、融資券 22:00 後、選股掃描 17:00 後應有最新交易日的資料；落後一個交易日顯示「落後 1 日」（國定假日也會這樣顯示，屬正常），落後兩日以上為「過期」。同時列出 24 小時內失敗的工作、每張表最近一次成功餵資料的工作、資料庫大小。

## 個股概況：基本介紹 + 最近狀況

`GET /api/stocks/{code}/summary` 把分散的資料整理成一頁，給卡片抽屜、追蹤池「概況」分頁與關係圖節點預覽用：

- **profile**：證交所 / 櫃買公司基本資料（全名、英文簡稱、董事長、總經理、成立 / 上市日、實收資本額、發行股數、網址、地址、產業名稱），每週隨公司清單更新；ETF 沒有。
- **price**：收盤與即時價、1 / 5 / 20 / 60 / 120 / 250 日漲幅並對比加權指數（`relative`）、所屬類股均值與 20 日排名、距區間高低點（資料滿 240 日才標 52 週）、MA5 / 20 / 60 / 120 與多空排列、RSI、KD、量能比。
- **chips**：外資 / 投信 / 自營 5 日與 20 日淨買超（張）、外資連買天數、融資餘額 20 日變化。
- **context**：最新選股掃描名次與標籤、啟用警示數、最近 5 次觸發、所屬清單。
- **news**：Google News RSS 以公司名稱查詢的最近 10 則標題（15 分鐘快取，`?news=false` 可略過；`GET /api/stocks/{code}/news` 單獨取）。

寫成文字的「公司簡介」與「近期重點」屬於 Stock CRM 的 `company_briefs`（由 agent 讀本端點與月營收後產生、走提案核准），前端在卡片的「概況」檢視同時顯示兩邊。

## 與 Stock CRM 的互嵌（建卡 → 目標價 → 警示 → 證據鏈）

| 方向 | 機制 |
| --- | --- |
| CRM 卡片 → 引擎追蹤 | 系統清單「CRM 持有 / 觀察」每 15 分鐘同步卡片代號並自動回補 |
| CRM 目標價 / 停損價 → 引擎警示 | 同一個同步工作把每張台股卡片的 `target_price` 鏡射成 `price_above`、`stop_price` 鏡射成 `price_below` 規則（`source=crm_target / crm_stop`，冷卻 7 天）；改價即更新，清掉或卡片出場即刪除。前端儲存卡片後也會立刻呼叫 `POST /api/alerts/sync-crm` |
| 引擎警示觸發 → CRM 證據 | `alerts.fire()` 透過 `POST /api/proposals` 送 kind=interaction（互動種類 `alert`，舊版 CRM 自動退回 `news`）、附觸發價與規則說明的**提案**，你在「提案」頁核准後才進卡片時間軸。沒有卡片的股票不送；CRM 離線只記在事件的 `delivery.crm` |
| 部位與損益 | CRM 卡片的 `shares` / `avg_cost` + 引擎現價 → 卡片概況顯示市值、未實現損益、距目標 / 距停損 %；看板持有欄顯示合計市值與今日損益 |

`.env` 開關：`CRM_SYNC_ALERTS`、`CRM_PROPOSALS`、`CRM_ALERT_KIND`。

## 多追蹤池

`watchlists`（清單）與 `watchlist_items`（清單 × 代號）多對多。資料訂閱（回補、即時報價、法人、警示評估）以所有清單的代號聯集計算，同一檔在幾個清單都只抓一次。舊版的單一追蹤池會在啟動時自動遷入預設清單「我的追蹤」。

| 系統清單 | 內容 | 更新 |
| --- | --- | --- |
| CRM 持有 / CRM 觀察 | Stock CRM 中 stage=hold / watch 的台股卡片（透過其 REST 讀取，`US:` 節點略過） | 每 15 分鐘與法人工作後 |
| 掃描候選 | 最新一次均衡預設選股掃描的前 20 名 | 每次掃描後 |
| 今日警示 | 過去 24 小時觸發過警示的股票 | 每 15 分鐘 |

系統清單不能手動增減或刪除；新進入 CRM 清單的代號會自動回補日線（每次最多 10 檔）。警示規則綁代號不綁清單，只有當一檔股票從所有清單消失時才會連同規則刪除（事件保留）。

```bash
python cli.py lists                          # 所有清單與檔數
python cli.py add 2330 --list "AI 供應鏈"     # 清單不存在會自動建立
python cli.py remove 2330 --list "AI 供應鏈"  # 省略 --list 則從所有自訂清單移除
python cli.py list --list "CRM 持有"
python cli.py sync-lists
```

## 排程（Asia/Taipei，週一至週五）

| 時間 | 工作 |
| --- | --- |
| 09:00–13:35 每 10 秒 | 即時報價 + 盤中警示（價格 / 漲跌幅） |
| 15:05、17:05 | 追蹤池日線 + 全市場日線（盤面分化）→ 補最新一根 → 評估日線型警示 |
| 16:40、18:40 | 全市場三大法人 → 評估警示 → 四個預設的選股掃描 → 推播均衡前 10 名 |
| 21:35、22:35 | 全市場融資融券 → 評估警示 |
| 週日 06:00 | 更新上市 / 上櫃公司清單 |
| 每 15 分鐘 | 同步系統清單（CRM 持有 / 觀察、掃描候選、今日警示） |

每個工作跑兩次是為了容忍交易所延遲發布；寫入都是 upsert，重複執行不會產生重複資料。
國定假日不做特別判斷：交易所當天沒有資料，工作就只是沒有新增而已。

## 警示規則

| rule_type | 範圍 | 參數 |
| --- | --- | --- |
| `price_above` / `price_below` | 盤中 | `price` |
| `pct_change_above` / `pct_change_below` | 盤中 | `pct` |
| `ma_cross` | 日線 | `fast`, `slow`, `direction` (golden/death) |
| `price_vs_ma` | 日線 | `period`, `direction` (above/below) |
| `rsi_above` / `rsi_below` | 日線 | `period`, `value` |
| `kd_cross` | 日線 | `direction` |
| `volume_spike` | 日線 | `multiplier`, `window` |
| `institutional_streak` | 日線 | `investor` (foreign/trust/dealer/total), `direction` (buy/sell), `days` |
| `margin_change` | 日線 | `direction` (increase/decrease), `lots` |

每條規則有 `cooldown_minutes`（預設盤中 60 分、日線 23 小時）避免重複通知，`one_shot=true` 則觸發一次後自動停用。
盤中型規則在收盤後的每日工作裡也會用收盤價再檢查一次，因此即使沒開即時輪詢也能運作。

## 盤面分化

每個交易日只要 2 個請求（證交所 `MI_INDEX` 全部個股 + 櫃買 `afterTrading/otc`），就能拿到全市場每檔收盤、漲跌、成交金額，以及證交所官方的漲跌家數與所有類股指數。資料存在 `daily_prices`（全市場）、`market_stats`（每日家數）、`index_daily`（加權與類股指數）。

```bash
python cli.py market            # 抓最新交易日
python cli.py market --days 20  # 回補 20 個交易日（約 1–2 分鐘）
```

儀表板「盤面分化」面板：
- 指標卡：上漲/下跌/平盤、上漲比例、漲停/跌停、加權指數 vs 個股中位數、「指數 − 中位數」（正值代表權值股撐盤、個股普遍較弱）、前 5 大成交佔比。
- 漲跌家數走勢（近 30 日）與上漲比例線。
- 類股強弱表：家數、漲/跌、平均 %、中位 %、官方類指數 %（上市）、近 N 日累計 %、成交佔比、領漲/領跌股；點類股展開全部成分股。
- 漲跌幅分布、漲幅/跌幅前 15（成交額 ≥ 2 千萬）、成交金額前 10。

類股依公司「產業別」代碼對照（上市上櫃共用），ETF 與非 4 碼商品歸入「ETF / 其他商品」且不計入家數統計。日線工作每天 15:05 / 17:05 會順便更新全市場。

## 選股掃描器

每天收盤後對全市場流動性合格的一般股票（預設成交額 ≥ 5 千萬）計算因子，轉成全市場百分位排名（0–100）後依預設權重加總成分數，產出候選清單並存入 `screener_results`，方便之後回測每個標籤的實際勝率。

```bash
python cli.py screen                       # 均衡預設，前 20 名
python cli.py screen --preset chips --top 30 --notify
```

| 因子 | 說明 |
| --- | --- |
| `rs20` / `rs5` | 20 / 5 日漲幅減去加權指數同期漲幅 |
| `breakout` / `breakout60` | 收盤 ÷ 前 20 / 60 日最高價（≥ 1 代表創新高） |
| `vol_ratio` / `vol_trend` | 今日量 ÷ 20 日均量、5 日均量 ÷ 20 日均量 |
| `trend` | 均線排列分：收盤 > MA5、MA5 > MA20、MA20 > MA60、MA20 上升，各 1 分 |
| `foreign5` / `trust5` | 外資 / 投信 5 日淨買超 ÷ 5 日成交量 |
| `foreign_streak` | 外資連續買超天數 |
| `margin` | 融資餘額 5 日變化（減少計高分） |
| `contrarian` | 近 20 日「上漲家數 < 40%」的弱勢盤中逆勢收紅次數 |
| `sector` | 所屬類股近 5 日累計平均漲跌 |

預設權重：`balanced`（均衡）、`momentum`（動能突破）、`chips`（法人籌碼）、`contrarian`（分化盤逆勢強勢）；`POST /api/screener/run` 也接受自訂 `weights`。
訊號標籤（創 60 日新高、量能 Nx、多頭排列、外資連買 N 日、外資 5 日大買、投信買超、融資減價漲、逆勢收紅 N 次、強勢類股）會一併儲存。

排程：三大法人更新後（16:40 / 18:40）自動跑四個預設，均衡預設的前 10 名會推播。掃描需要全市場日線與籌碼歷史，首次使用請先：

```bash
python cli.py market --days 60
python cli.py flows --days 60
```

**分數是相對排名，不是機率。** 要知道「分數 80 以上的股票 20 日後有多少比例上漲」，需要下一步的回測模組把 `screener_results` 與後續價格對照。

## REST API 摘要

```
GET    /api/health                                  # 引擎、排程器、通知管道、CRM 連線
GET    /api/health/data                             # 各表新鮮度、失敗工作、儲存空間
GET    /api/stocks/search?q=台積
GET    /api/stocks/{code}/summary?news=true         # 基本介紹 + 最近狀況（見上節）
GET    /api/stocks/{code}/news?limit=10
GET    /api/stocks/{code}/daily?limit=250
GET    /api/stocks/{code}/indicators?limit=250     # series + latest
GET    /api/stocks/{code}/institutional?days=5      # 全市場都有，單位股，最新在前（limit= 亦可）
GET    /api/stocks/{code}/margin?days=5             # 單位張
GET    /api/watchlists                              # 清單（含檔數、system_key）
POST   /api/watchlists         {"name":"AI 供應鏈","color":"#4f8cff"}
PATCH  /api/watchlists/{id}    {"name":"...","color":"...","sort_order":1}
DELETE /api/watchlists/{id}                         # 僅自訂清單；回傳因此停止追蹤的代號
POST   /api/watchlists/sync                         # 背景重建系統清單
GET    /api/watchlist?list={id}                     # 總覽（即時價、法人、融資券、所屬清單）；不帶 list 為聯集
POST   /api/watchlist          {"code":"2330","lists":[1,3],"note":"...","backfill":true}   # lists 省略 = 預設清單；重複加入只更新備註
PATCH  /api/watchlist/{code}   {"lists":[1],"note":"..."}                                 # 設定自訂清單的精確成員關係
DELETE /api/watchlist/{code}?list={id}              # 從一個清單移除；省略 list 則從所有自訂清單移除
GET    /api/quotes?codes=2330,2382                  # 最新即時快照；不在追蹤池的代號會即時抓
POST   /api/quotes/refresh                          # 立刻輪詢 MIS
GET    /api/alerts/rule-types
GET    /api/alerts?code=2330
POST   /api/alerts             {"code":"2330","rule_type":"price_below","params":{"price":2300}}
PATCH  /api/alerts/{id}        {"enabled":false}
DELETE /api/alerts/{id}
GET    /api/alerts/events?limit=100
POST   /api/alerts/evaluate
POST   /api/alerts/sync-crm                         # 鏡射 CRM 目標價 / 停損價為警示規則
GET    /api/market/dates                            # 有全市場資料的日期
GET    /api/market/breadth?date=2026-10-30          # 家數、類股、分布、排行
GET    /api/market/breadth/history?days=30
GET    /api/market/sectors/history?days=10          # 類股每日平均漲跌矩陣與累計
GET    /api/market/sectors/{類股名}/stocks?date=
GET    /api/screener/presets                        # 預設權重與因子說明
GET    /api/screener/dates?preset=balanced
GET    /api/screener?preset=balanced&date=&limit=30
POST   /api/screener/run       {"preset":"chips","min_turnover":50000000,"top":30,"notify":false}
GET    /api/jobs                                    # 排程與即時輪詢狀態
POST   /api/jobs/{name}/run                         # daily_prices | institutional | margin | flows_backfill | market_daily | market_backfill | screener | sync_lists | stock_list | alerts_daily | full_daily | realtime
GET    /api/jobs/runs
POST   /api/notify/test
ANY    /api/crm/*                                   # 反向代理到 Stock CRM 的 /api/*（CRM 離線回 502）
```

全部無認證、只綁 127.0.0.1、回 JSON（NaN 已轉 null）。CORS 已開放，Vite 開發伺服器與其他前端可直接呼叫。

## 通知設定

**LINE**：LINE Notify 已於 2025 年停止服務，這裡使用 LINE Messaging API 的 push message。
到 [LINE Developers](https://developers.line.biz/console/) 建一個 Messaging API channel，取得 channel access token 與自己的 user ID，填入 `.env` 的 `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_USER_ID`。

**Email**：填 `SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`EMAIL_FROM`、`EMAIL_TO`（逗號分隔多個收件人）。Gmail 請用應用程式密碼。

設定好後按儀表板的「測試通知」或 `python cli.py notify-test` 確認。

## 專案結構

```
app/
  config.py            設定（.env，含 CRM_BASE_URL）
  db.py / models.py    SQLAlchemy + SQLite（data/twstock.db）
  utils.py             民國日期、數字解析、交易時段判斷
  datasources/
    twse.py            證交所：日線、月歷史、MI_INDEX 全市場、T86 法人、MI_MARGN 融資券、公司清單
    tpex.py            櫃買：同上（afterTrading/otc 全市場）
    mis.py             證交所 MIS 即時報價
  services/
    market_data.py     抓取 + upsert + 追蹤池總覽
    watchlists.py      多追蹤池：清單 CRUD、成員關係、系統清單同步
    health.py          資料健康：各表新鮮度、失敗工作、儲存空間
    stock_summary.py   個股概況：基本介紹、相對強弱、籌碼、脈絡、新聞 RSS
    crm_link.py        與 CRM 互嵌：目標價鏡射警示、警示回寫提案
    indicators.py      技術指標
    alerts.py          警示規則定義與評估
    notifier.py        LINE / Email / console
    breadth.py         盤面分化：家數、類股、分布、歷史
    screener.py        選股掃描：因子、評分、標籤、預設
    industries.py      產業別代碼對照
  scheduler.py         APScheduler 工作與排程
  api/
    routes.py          REST API
    crm_proxy.py       /api/crm/* 反向代理到 Stock CRM
  main.py              FastAPI app：API + 代理 + 伺服 web/dist（/legacy 為舊版）
web/                   統一前端（Vite + React + TypeScript）
  src/pages/           追蹤池、盤面分化、選股掃描、警示、排程、crm/{看板、關係圖、早晨、提案}
  src/components/      Layout、CardDrawer（CRM 卡片抽屜）、Chart、Toast
  src/lib/format.ts    格式化與 TW:2330 ↔ 2330 橋接
  api/
    auth_routes.py     登入 / 登出 / me / 改密碼；/api/admin/users 帳號管理
    deps.py            current_user / require_admin
  services/auth.py     密碼雜湊、session、登入限速、首次管理員
scripts/               Windows 服務化：service_install / stop / restart / uninstall、run_engine / run_crm；Cloudflare Tunnel：tunnel_quick / tunnel_install / run_tunnel
static/                舊版純 HTML 儀表板（/legacy/）
cli.py                 命令列工具
tests/                 離線單元測試與 API 測試（python -m pytest -q）
.github/workflows/     CI：ruff、pytest、API 煙霧測試、前端建置
```

## 開發流程

- 所有變更走分支 → PR → CI 綠 → 審查合併；`main` 不直接推。`.github/CODEOWNERS` 讓每個 PR 自動指定倉庫擁有者審查（GitHub 會略過 PR 作者本人）。
- CI（`.github/workflows/ci.yml`）在每個 PR 跑：`ruff check`、`compileall`、`pytest`、FastAPI TestClient 煙霧測試（Python 3.11 / 3.12），以及 `npm ci && npm run build`（型別檢查 + Vite 建置）。
- 本機同樣四步：

```bash
python -m ruff check app cli.py tests
python -m pytest -q
cd web && npm run build
```

- 與 Stock CRM 的分工：引擎 repo 負責市場資料、警示、掃描、排程、通知、統一前端與代理；stockcrm repo 負責卡片、論點、供應鏈、提案、MCP server 與其資料腳本。各寫各的資料庫，API 變更先互相告知。

## 資料來源與注意事項

- 證交所 `www.twse.com.tw` 對短時間大量請求會暫時封鎖，`REQUEST_DELAY_SECONDS`（預設 1.5 秒）控制請求間隔；補歷史時每檔每月一個請求。
- 櫃買中心網站改版頻率較高，若上櫃歷史 / 法人 / 融資券抓不到，優先檢查 `app/datasources/tpex.py` 的欄位索引。
- MIS 即時報價有數秒延遲，非正式交易資料。
- 單位：資料庫內日線成交量為「股」，法人買賣超為「股」，融資券為「張」；API 總覽與前端一律顯示「張」。
- 日線只有未還原權息的原始價格。
- 歷史深度：追蹤池內的股票回補 6 個月；全市場其他股票只有 `market --days N` 回補的天數（預設建議 60），MA120 等長週期指標在這些股票會是 null。
- 證交所 OpenAPI 的全市場日線有時比個股月歷史晚一天，日線工作會自動用月歷史補最新一根。

## 之後的計畫

1. **統一介面 PR 2（互嵌）**：建 TW 卡片同步加入追蹤池並回補；卡片與看板顯示即時價、法人 5 日、類股強弱；目標價 / 停損價自動生成價格警示；警示觸發透過 `POST /api/crm/proposals` 寫成 CRM 提案。
2. **統一介面 PR 3（早晨頁合併）**：CRM 的注意事項與對手方 + 昨日盤面分化 + 選股前 10 + 觸發警示，一頁看完並推播。
3. **回測模組**：用 `screener_results` 與 `alert_events` 對照後續 5 / 10 / 20 日報酬，統計每個標籤、分數區間與警示規則的勝率與報酬分布，把「分數」變成「機率」。
4. 台股行事曆避開假日排程；更多籌碼來源（借券、八大行庫、分點）；WebSocket 推播即時報價；伺服器服務化（Windows 服務或 VPS）。
