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
- **API 命名空間**：`/api/market/*` 通用層（登入即可讀）、`/api/me/*` 個人化層（自動依登入者過濾）、`/api/admin/*`、`/api/auth/*`、`/api/crm/*`（代理到 Stock CRM 並帶 `X-User-Id` / `X-User-Name` / `X-Facade-Token`）。舊的 `/api/*` 路徑仍可用。本機服務（例如 CRM 的 MCP）不走瀏覽器登入時，可帶 `X-Service-Token`（＝ `CRM_FACADE_TOKEN`）加 `X-User-Id` 讀 `/api/market/*`；個人與管理路徑一律要真正登入。
- **對外**：兩個後端仍只綁 127.0.0.1。公開存取走 Cloudflare Tunnel（不開路由器埠、自帶 HTTPS）：

```powershell
scripts\tunnel_quick.ps1                                   # 測試用：臨時 trycloudflare.com 網址
scripts\tunnel_install.ps1 -Hostname stocks.你的網域.com -Start   # 正式：固定網址 + 開機自動啟動
```

可再加 Cloudflare Access 當外圍第二層；應用層身份仍以本機帳號為準。

還沒有網域時，可以先把**臨時隧道**服務化：`scripts\tunnel_quick_install.ps1 -Start` 登記同名的 `TWStock Tunnel` 任務，開機自動跑 `*.trycloudflare.com` 網址並在斷線後重連。網址每次重啟都會變，所以引擎把目前的網址寫在 `data\tunnel-url.txt`、顯示在 `/api/health` 的 `public_url` 與「系統」頁，並在網址改變時透過 LINE / Email 推播（`tunnel_watch`）。之後有網域再跑 `tunnel_install.ps1 -Hostname …`，同名任務會被固定隧道取代；固定網址也可直接設 `.env` 的 `PUBLIC_URL`。

```bash
python cli.py users create mom --name 媽媽 --line Uxxxxxxxx     # 建成員（會提示輸入密碼）
python cli.py users create drew --admin
python cli.py users passwd drew
python cli.py users list
```

## 共用資料庫與知識層

引擎與 Stock CRM 從 v0.5 起共用同一個 SQLite 檔 `<workspace>/data/market.db`（WAL），不再各自一個資料庫。分層不是「哪個程式的表」而是「通用知識 vs 個人化」，並用表的擁有權落實：

| 層 | 表 | 誰寫 | 誰讀 |
| --- | --- | --- | --- |
| 通用知識 knowledge | `stocks`、`daily_prices`、法人 / 融資券 / 盤面 / 掃描 / 即時報價，以及 `knowledge_companies`（圖節點 `TW:2330` / `US:NVDA`）、`knowledge_edges`（客戶 → 供應商，`revenue_share`）、`knowledge_edge_weights`（權重歷史）、`knowledge_company_briefs`（簡介 / 近期重點，append-only）、`knowledge_financials_ytd`（季報 YTD）、`knowledge_metrics`（月營收、單季營收、毛利率、費用、EPS、股數的**實際值**） | 引擎 | 兩邊 |
| 個人化 personal | 引擎的 `watchlists` / `alert_rules` / `alert_events`；CRM 的 `personal_*`（卡片、驅動因子、檢查點、互動、提醒、提案、分層規則、模型值、個人筆記） | 各自 | 各自（引擎透過 CRM REST 讀卡片） |
| 帳號 auth | `users`、`sessions` | 引擎 | CRM 只讀身份欄位，不讀 `password_hash` |
| 營運 ops | `job_runs`、`schema_registry`、CRM 的 `crm_maintenance_log` | 各自 | 兩邊 |

- `schema_registry` 記錄每張表的層、擁有者與寫入者，`python cli.py knowledge registry` 可以列出。
- **知識層的寫入通道**：引擎自己抓的官方事實（見下）直接寫；其他人（CRM 核准 knowledge 範圍的提案、agent、維護腳本）透過 `/api/market/knowledge/*` 寫，需要管理員身份（登入的 admin，或 `X-Service-Token` + 管理員的 `X-User-Id`），每筆帶 `source` / `confidence` / `created_by`（`user:drew`、`agent:claude`、`system:mops`）。
- **官方事實由引擎抓**：`mops_monthly`（月營收，週一至五 19:30）、`mops_quarterly`（季報 YTD + 單季差分，20:00）、`mops_shares`（發行股數，週一 20:30）從證交所 / 櫃買開放資料寫入 `knowledge_metrics` / `knowledge_financials_ytd`，對象是 `knowledge_companies` 裡 market=TW 且非 ETF 的公司。季報開放資料是年初至今，單季數字要前一季也在庫才算得出來。
- **第一次啟動**：若 `market.db` 不存在而舊的 `data/twstock.db` 在，引擎會用 SQLite 線上備份把它整個複製過去（舊檔留著當備份，旁邊有 `MOVED_TO_market.db.txt`）。CRM 原本的 `companies` / `edges` / `company_briefs` / `financials_ytd` / `metrics(actual)` 用 `python cli.py knowledge import-crm` 唯讀複製進 `knowledge_*`（id 沿用，可重複執行）。
- 位置可用 `.env` 的 `SHARED_DATA_DIR` 或 `DATABASE_URL` 覆寫；CRM 端把 `STOCKCRM_DB` 指到同一個檔。

```bash
python cli.py knowledge import-crm                 # 從 ../stockcrm/data/stockcrm.db 匯入（--source 指定）
python cli.py knowledge fetch all                  # monthly | quarterly | shares | all
python cli.py knowledge stats
python cli.py knowledge registry
```

### 知識層怎麼自己長大

知識層不靠人一筆一筆填。三種來源、三種進法：

| 來源 | 例子 | 進法 |
| --- | --- | --- |
| **官方 / 公開事實** | 證交所公司清單、月營收、季報、股數、ETF 成分股與權重 | 引擎排程直接寫入，`created_by=system:*`，帶來源網址 |
| **從事實推導的文字** | 「9 月營收 5,118 億，年增 +54.6%，為近一年新高」 | `knowledge_highlights` 工作直接寫成當月的近期重點（每家每月一則） |
| **需要判斷的內容** | 供應鏈關係、客戶佔比、公司簡介、新聞解讀 | 進 **提案佇列** `knowledge_proposals`，管理員在「知識層」頁核准後才寫入 |

- **節點同步** `knowledge_sync`（每 6 小時）：所有人追蹤的台股、CRM 卡片、掃描候選都會有一個圖節點，名稱與產業來自交易所清單，ETF 自動標 `sector=ETF`。
- **ETF 成分股** `etf_holdings`（每週二 07:00，或 `cli.py knowledge holdings 0050`）：從 MoneyDJ 全部持股頁讀成分股與權重，寫成 `holding` 邊（成分股 → ETF，`revenue_share` = 權重），權重歷史留在 `knowledge_edge_weights`，退出的成分股自動移除。美股 ETF 用 `--file seeds/holdings_voo_2026-09-30.json` 這種檔案載入。
- **提案佇列**：`POST /api/market/knowledge/proposals`（任何登入者、服務金鑰、agent）送 `{kind, payload, rationale, evidence, source, confidence}`；同一件事待審中重複提出只會更新不會重複；管理員 `POST /proposals/decide {ids, approve}` 批次核准，核准即透過 `services/knowledge.py` 套用並記 `applied_ref`，失敗標 `failed` 留原因。`GET /knowledge/todo` 列出還缺簡介、近期重點過期、沒有關係、關係沒來源的公司，給 agent 當工作清單。
- **種子檔**：`seeds/supply_chain_2026-10.json` 是 agent 整理的 0050 / 00981A / VOO 成分股簡介與供應鏈關係，`cli.py knowledge propose-seed <file>` 整包送進佇列，`cli.py knowledge approve [--kind] [--ids]` 從命令列核准。
- **Agent 金鑰**（給 Grok bot、Claude session、腳本）：管理員在「帳號管理 → Agent 金鑰」發放，或 `python cli.py agents create grok --scopes market:read,knowledge:propose --as drew --rate 60`。金鑰 `twa_…` 只顯示一次、資料庫只存 SHA-256；帶法 `Authorization: Bearer twa_…`（或 `X-Agent-Key`）。範圍：`market:read` 讀 `/api/market/*`、`knowledge:propose` 只能 `POST /knowledge/proposals`、`personal:read` 讀代表使用者的 `/api/me/*`；agent 永遠進不了 `/api/admin/*` 與知識層的直接寫入端點，提案一律標 `agent:<名稱>`，每把金鑰有每分鐘上限、可換金鑰、可停用。agent 的工作入口是 `GET /api/market/knowledge/tasks?limit=5`：回傳還缺簡介 / 近期重點 / 關係的公司，每家附上引擎打包好的材料（基本資料、月營收、已知關係、新聞標題），agent 讀完用 `POST /knowledge/proposals/batch` 回答。
- **LLM 抽取器**（選用）：`EXTRACTOR_ENABLED=true` 加 `ANTHROPIC_API_KEY`（或 `ant auth login`），`knowledge_extract` 每晚 20:30 讀待補清單，把引擎自己的材料（基本資料、月營收、新聞標題）交給 Claude 產出簡介、近期重點與供應鏈關係，**全部只進提案佇列**，帶信心度與新聞證據；`cli.py knowledge extract --company TW:2330` 單跑一家。

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
- **context**：最新選股掃描名次與標籤、啟用警示數、最近 5 次觸發、所屬清單；`knowledge` 為共用知識層的簡介 / 近期重點與供應鏈鄰居（客戶、供應商、所屬 ETF）。
- **news**：Google News RSS 以公司名稱查詢的最近 10 則標題（15 分鐘快取，`?news=false` 可略過；`GET /api/stocks/{code}/news` 單獨取）。

寫成文字的「公司簡介」與「近期重點」存在共用知識層的 `knowledge_company_briefs`（agent 讀本端點與月營收後產生、在 CRM 走提案核准、核准時寫入 `POST /api/market/knowledge/briefs`），個股概況的「供應鏈與簡介」區塊直接顯示。

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
| 19:30、20:00 | 知識層官方事實：月營收（`mops_monthly`）、季報 YTD 與單季差分（`mops_quarterly`） |
| 週一 20:30 | 發行股數（`mops_shares`） |

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
POST   /api/jobs/{name}/run                         # daily_prices | institutional | margin | flows_backfill | market_daily | market_backfill | screener | sync_lists | stock_list | alerts_daily | full_daily | realtime | mops_monthly | mops_quarterly | mops_shares
GET    /api/jobs/runs
POST   /api/notify/test
ANY    /api/crm/*                                   # 反向代理到 Stock CRM 的 /api/*（CRM 離線回 502）

# 共用知識層（/api/market/knowledge；讀：登入即可，寫：管理員或服務金鑰 + 管理員 X-User-Id）
GET    /api/market/knowledge/stats                  # 各表列數、官方資料最新期間
GET    /api/market/knowledge/companies?q=台積&market=TW
GET    /api/market/knowledge/companies/{id}         # 含邊、最新簡介 / 近期重點、metrics、financials
PUT    /api/market/knowledge/companies/{id}         {"name":"台積電","sector":"晶圓代工","source":"...","confidence":"high"}
GET    /api/market/knowledge/edges?company=TW:2330&relation=customer
POST   /api/market/knowledge/edges                  {"customer_id":"US:NVDA","supplier_id":"TW:2330","revenue_share":0.12,"date":"2026-06-30","source":"10-K"}
DELETE /api/market/knowledge/edges/{id}             # 仍被引用回 409
GET    /api/market/knowledge/edges/{id}/weights
POST   /api/market/knowledge/edges/{id}/weights     {"date":"2026-09-30","revenue_share":0.15}   # 同步更新邊上的最新值
GET    /api/market/knowledge/briefs/{company_id}?kind=profile
POST   /api/market/knowledge/briefs                 {"company_id":"TW:2330","kind":"highlights","date":"2026-10-20","content":"...","sources":[...],"created_by":"agent:claude"}
GET    /api/market/knowledge/financials/{company_id}
POST   /api/market/knowledge/financials             {"company_id":"TW:2330","year":2026,"quarter":2,"revenue":...}   # /financials/batch 吃陣列
GET    /api/market/knowledge/metrics/{company_id}?metric=revenue_m
POST   /api/market/knowledge/metrics                {"company_id":"TW:2330","metric":"revenue_m","period":"2026-09","value":511857399,"source":"..."}   # /metrics/batch 吃陣列
```

除 `/api/health` 與登入外都需要 session（或服務金鑰），只綁 127.0.0.1、回 JSON（NaN 已轉 null）。CORS 只開給 Vite 開發伺服器。

## 通知設定

**LINE**：LINE Notify 已於 2025 年停止服務，這裡使用 LINE Messaging API 的 push message。
到 [LINE Developers](https://developers.line.biz/console/) 建一個 Messaging API channel，取得 channel access token 與自己的 user ID，填入 `.env` 的 `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_USER_ID`。

**Email**：填 `SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`EMAIL_FROM`、`EMAIL_TO`（逗號分隔多個收件人）。Gmail 請用應用程式密碼。

設定好後按儀表板的「測試通知」或 `python cli.py notify-test` 確認。

## 專案結構

```
app/
  config.py            設定（.env，含 SHARED_DATA_DIR、CRM_BASE_URL、CRM_FACADE_TOKEN）
  db.py / models.py    SQLAlchemy + 共用 SQLite（<workspace>/data/market.db）、遷移、schema_registry
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
    knowledge.py       共用知識層：公司、供應鏈邊與權重歷史、簡介、季報、實際值；從 CRM 匯入
    mops.py            證交所 / 櫃買開放資料：月營收、季報 YTD 差分、股數 → knowledge_*
    indicators.py      技術指標
    alerts.py          警示規則定義與評估
    notifier.py        LINE / Email / console
    breadth.py         盤面分化：家數、類股、分布、歷史
    screener.py        選股掃描：因子、評分、標籤、預設
    industries.py      產業別代碼對照
  scheduler.py         APScheduler 工作與排程
  api/
    routes.py          REST API（market / me / admin）
    knowledge_routes.py  /api/market/knowledge/*
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

- 與 Stock CRM 的分工：引擎 repo 負責通用知識層（市場資料、供應鏈圖、簡介、官方財務事實）、警示、掃描、排程、通知、帳號、統一前端與代理；stockcrm repo 負責個人化層（卡片、論點、驅動因子、提案）、MCP server 與其維護腳本。同一個資料庫、各寫各的表（`schema_registry`），表結構與 API 變更先互相告知。

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
