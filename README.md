# 台股追蹤引擎 (TW Stock Tracker)

Python 後端 + Web 儀表板的台股追蹤引擎，資料來源全部是證交所 / 櫃買中心的公開 API，不需要金鑰。

## 功能

| 功能 | 說明 |
| --- | --- |
| 追蹤池 | 新增 / 移除自選股（上市、上櫃、ETF 皆可），加入時自動補 6 個月日線與 20 個交易日的籌碼資料 |
| 每日行情 | 收盤後自動抓日 K（開高低收量），計算 MA5/10/20/60/120、RSI、KD、MACD、布林通道 |
| 三大法人 | 外資、投信、自營商買賣超（張） |
| 融資融券 | 融資 / 融券餘額與單日增減（張） |
| 盤中即時報價 | 交易時段每 10 秒輪詢證交所 MIS 即時行情（上市 + 上櫃） |
| 警示引擎 | 價格突破 / 跌破、漲跌幅、均線交叉、站上/跌破均線、RSI、KD 交叉、爆量、法人連續買賣超、融資變動 |
| 通知 | Console、LINE Messaging API、Email (SMTP) |
| 盤面分化 | 全市場上漲/下跌/漲停/跌停家數與走勢、加權指數 vs 個股中位數、前 5 大成交佔比、類股強弱（平均/中位/官方類指數/N 日累計）、漲跌幅分布、領漲領跌與成交金額排行 |
| Web 儀表板 | 追蹤池總覽、盤面分化、K 線圖、指標、籌碼表、警示管理、排程狀態 |
| REST API | 所有資料都有 JSON API，方便之後整合自己的前端 |

## 快速開始

```bash
cd twstock-tracker
pip install -r requirements.txt
copy .env.example .env        # 視需要填入 LINE / Email 設定
python cli.py serve           # http://127.0.0.1:8000
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
python cli.py flows --days 40          # 補 40 個交易日的法人 / 融資券
python cli.py alerts                   # 立即評估日線型警示
python cli.py notify-test
```

## 排程（Asia/Taipei，週一至週五）

| 時間 | 工作 |
| --- | --- |
| 09:00–13:35 每 10 秒 | 即時報價 + 盤中警示（價格 / 漲跌幅） |
| 15:05、17:05 | 日線更新 → 評估日線型警示 |
| 16:40、18:40 | 三大法人 → 評估警示 |
| 21:35、22:35 | 融資融券 → 評估警示 |
| 週日 06:00 | 更新上市 / 上櫃公司清單 |

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
GET    /api/health
GET    /api/stocks/search?q=台積
GET    /api/stocks/{code}/daily?limit=250
GET    /api/stocks/{code}/indicators?limit=250     # series + latest
GET    /api/stocks/{code}/institutional?limit=60
GET    /api/stocks/{code}/margin?limit=60
GET    /api/watchlist                               # 總覽（即時價、法人、融資券合併）
POST   /api/watchlist          {"code":"2330","note":"...","backfill":true}
PATCH  /api/watchlist/{code}   {"note":"...","tags":"..."}
DELETE /api/watchlist/{code}
GET    /api/quotes                                  # 最後一次即時快照
POST   /api/quotes/refresh                          # 立刻輪詢 MIS
GET    /api/alerts/rule-types
GET    /api/alerts?code=2330
POST   /api/alerts             {"code":"2330","rule_type":"price_below","params":{"price":2300}}
PATCH  /api/alerts/{id}        {"enabled":false}
DELETE /api/alerts/{id}
GET    /api/alerts/events?limit=100
POST   /api/alerts/evaluate
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
POST   /api/jobs/{name}/run                         # daily_prices | institutional | margin | flows_backfill | market_daily | market_backfill | stock_list | alerts_daily | full_daily | realtime
GET    /api/jobs/runs
POST   /api/notify/test
```

CORS 已開放，之後可以用 React / Vue 等另外做前端直接呼叫這些 API；`static/` 內的儀表板只是純 HTML + JS 的參考實作。

## 通知設定

**LINE**：LINE Notify 已於 2025 年停止服務，這裡使用 LINE Messaging API 的 push message。
到 [LINE Developers](https://developers.line.biz/console/) 建一個 Messaging API channel，取得 channel access token 與自己的 user ID，填入 `.env` 的 `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_USER_ID`。

**Email**：填 `SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`EMAIL_FROM`、`EMAIL_TO`（逗號分隔多個收件人）。Gmail 請用應用程式密碼。

設定好後按儀表板的「測試通知」或 `python cli.py notify-test` 確認。

## 專案結構

```
app/
  config.py            設定（.env）
  db.py / models.py    SQLAlchemy + SQLite（data/twstock.db）
  utils.py             民國日期、數字解析、交易時段判斷
  datasources/
    twse.py            證交所：日線、月歷史、T86 法人、MI_MARGN 融資券、公司清單
    tpex.py            櫃買：同上
    mis.py             證交所 MIS 即時報價
  services/
    market_data.py     抓取 + upsert + 總覽查詢
    indicators.py      技術指標
    alerts.py          警示規則定義與評估
    notifier.py        LINE / Email / console
  scheduler.py         APScheduler 工作與排程
  api/routes.py        REST API
  main.py              FastAPI app
static/                儀表板前端
cli.py                 命令列工具
tests/                 離線單元測試（python -m pytest -q）
```

## 資料來源與注意事項

- 證交所 `www.twse.com.tw` 對短時間大量請求會暫時封鎖，`REQUEST_DELAY_SECONDS`（預設 1.5 秒）控制請求間隔；補歷史時每檔每月一個請求。
- 櫃買中心網站改版頻率較高，若上櫃歷史 / 法人 / 融資券抓不到，優先檢查 `app/datasources/tpex.py` 的欄位索引。
- MIS 即時報價有數秒延遲，非正式交易資料。
- 單位：資料庫內日線成交量為「股」，法人買賣超為「股」，融資券為「張」；API 總覽與前端一律顯示「張」。
- 日線只有未還原權息的原始價格。

## 之後可以擴充的方向

- 加入台股行事曆避開假日排程
- 更多籌碼來源（借券、八大行庫、分點）
- 回測模組：把警示規則套用在歷史資料上統計勝率
- WebSocket 推播即時報價給前端
- 用 React / Vue 重寫前端並加上使用者登入
