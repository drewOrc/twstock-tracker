"""Taipei Exchange (上櫃) data sources.

Endpoints used:
  * OpenAPI  https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes        latest OHLCV for all OTC
  * OpenAPI  https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O           OTC company master
  * WWW      https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock     monthly history per stock
  * WWW      https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade              三大法人買賣明細
  * WWW      https://www.tpex.org.tw/www/zh-tw/margin/balance                融資融券餘額
"""
from __future__ import annotations

import logging
from datetime import date

from ..utils import roc_compact_to_date, roc_to_date, slash_date, to_float, to_int
from .base import HttpClient

log = logging.getLogger(__name__)

OPENAPI = "https://www.tpex.org.tw/openapi/v1"
WWW = "https://www.tpex.org.tw/www/zh-tw"


def _first_table(data: dict) -> dict | None:
    tables = data.get("tables") or []
    for t in tables:
        if t.get("data"):
            return t
    return tables[0] if tables else None


class TPEXClient:
    market = "TPEX"

    def __init__(self, http: HttpClient):
        self.http = http

    # ------------------------------------------------------------------ master
    def fetch_stock_list(self) -> list[dict]:
        rows = self.http.get_json(f"{OPENAPI}/mopsfin_t187ap03_O")
        out = []
        for r in rows:
            code = (r.get("SecuritiesCompanyCode") or "").strip()
            if not code:
                continue
            out.append(
                {
                    "code": code,
                    "name": (r.get("CompanyAbbreviation") or r.get("CompanyName") or "").strip(),
                    "market": self.market,
                    "industry": (r.get("SecuritiesIndustryCode") or "").strip() or None,
                }
            )
        return out

    # ------------------------------------------------------------------ daily
    def fetch_daily_all(self) -> list[dict]:
        rows = self.http.get_json(f"{OPENAPI}/tpex_mainboard_quotes")
        out = []
        for r in rows:
            d = roc_compact_to_date(r.get("Date", ""))
            code = (r.get("SecuritiesCompanyCode") or "").strip()
            if not d or not code:
                continue
            out.append(
                {
                    "code": code,
                    "name": (r.get("CompanyName") or "").strip(),
                    "date": d,
                    "open": to_float(r.get("Open")),
                    "high": to_float(r.get("High")),
                    "low": to_float(r.get("Low")),
                    "close": to_float(r.get("Close")),
                    "volume": to_int(r.get("TradingShares")),
                    "turnover": to_float(r.get("TransactionAmount")),
                    "transactions": to_int(r.get("TransactionNumber")),
                    "change": to_float(r.get("Change")),
                }
            )
        return out

    def fetch_daily_history(self, code: str, year: int, month: int) -> list[dict]:
        params = {"code": code, "date": f"{year}/{month:02d}/01", "response": "json"}
        data = self.http.get_json(f"{WWW}/afterTrading/tradingStock", params=params)
        table = _first_table(data)
        if not table:
            return []
        out = []
        for row in table.get("data", []):
            d = roc_to_date(row[0])
            if not d:
                continue
            # TPEx reports volume in lots (千股) and turnover in thousands of NTD; normalise to shares / NTD
            vol = to_int(row[1])
            turnover = to_float(row[2])
            out.append(
                {
                    "code": code,
                    "date": d,
                    "volume": vol * 1000 if vol is not None else None,
                    "turnover": turnover * 1000 if turnover is not None else None,
                    "open": to_float(row[3]),
                    "high": to_float(row[4]),
                    "low": to_float(row[5]),
                    "close": to_float(row[6]),
                    "change": to_float(row[7]),
                    "transactions": to_int(row[8]),
                }
            )
        return out

    # ------------------------------------------------------------------ whole market
    def fetch_market_day(self, d: date) -> dict:
        """上櫃股票每日收盤行情 for one date (type=EW: all securities, no warrants). One request.
        Same shape as TWSEClient.fetch_market_day; TPEx publishes no official breadth counts here."""
        params = {"date": slash_date(d), "type": "EW", "response": "json"}
        data = self.http.get_json(f"{WWW}/afterTrading/otc", params=params)
        table = _first_table(data)
        out = {"date": d, "prices": [], "counts": None, "indices": []}
        if not table:
            return out
        for r in table.get("data", []):
            if len(r) < 10:
                continue
            # 0 代號,1 名稱,2 收盤,3 漲跌,4 開盤,5 最高,6 最低,7 成交股數,8 成交金額,9 成交筆數
            out["prices"].append(
                {
                    "code": r[0].strip(),
                    "name": r[1].strip(),
                    "date": d,
                    "close": to_float(r[2]),
                    "change": to_float(r[3]),
                    "open": to_float(r[4]),
                    "high": to_float(r[5]),
                    "low": to_float(r[6]),
                    "volume": to_int(r[7]),
                    "turnover": to_float(r[8]),
                    "transactions": to_int(r[9]),
                }
            )
        return out

    # ------------------------------------------------------------------ institutional
    def fetch_institutional(self, d: date) -> list[dict]:
        params = {"type": "Daily", "sect": "EW", "date": slash_date(d), "response": "json"}
        data = self.http.get_json(f"{WWW}/insti/dailyTrade", params=params)
        table = _first_table(data)
        if not table:
            return []
        out = []
        for r in table.get("data", []):
            if len(r) < 24:
                continue
            # 0 code, 1 name, 2-4 外資不含自營, 5-7 外資自營, 8-10 外資合計 買/賣/超,
            # 11-13 投信 買/賣/超, 14-16 自營(自行), 17-19 自營(避險), 20-22 自營合計, 23 三大法人合計
            out.append(
                {
                    "code": r[0].strip(),
                    "date": d,
                    "foreign_buy": to_int(r[8]),
                    "foreign_sell": to_int(r[9]),
                    "foreign_net": to_int(r[10]),
                    "trust_buy": to_int(r[11]),
                    "trust_sell": to_int(r[12]),
                    "trust_net": to_int(r[13]),
                    "dealer_net": to_int(r[22]),
                    "total_net": to_int(r[23]),
                }
            )
        return out

    # ------------------------------------------------------------------ margin
    def fetch_margin(self, d: date) -> list[dict]:
        params = {"date": slash_date(d), "response": "json"}
        data = self.http.get_json(f"{WWW}/margin/balance", params=params)
        table = _first_table(data)
        if not table:
            return []
        out = []
        for r in table.get("data", []):
            if len(r) < 19:
                continue
            # 0 code,1 name,2 前資餘額,3 資買,4 資賣,5 現償,6 資餘額,7 資屬證金,8 資使用率,9 資限額,
            # 10 前券餘額,11 券賣,12 券買,13 券償,14 券餘額,15 券屬證金,16 券使用率,17 券限額,18 資券相抵
            out.append(
                {
                    "code": r[0].strip(),
                    "date": d,
                    "margin_prev": to_int(r[2]),
                    "margin_buy": to_int(r[3]),
                    "margin_sell": to_int(r[4]),
                    "margin_redeem": to_int(r[5]),
                    "margin_balance": to_int(r[6]),
                    "margin_limit": to_int(r[9]),
                    "short_prev": to_int(r[10]),
                    "short_sell": to_int(r[11]),
                    "short_buy": to_int(r[12]),
                    "short_redeem": to_int(r[13]),
                    "short_balance": to_int(r[14]),
                    "short_limit": to_int(r[17]),
                    "offset": to_int(r[18]),
                }
            )
        return out
