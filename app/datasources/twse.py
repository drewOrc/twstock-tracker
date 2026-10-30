"""Taiwan Stock Exchange (上市) data sources.

Endpoints used (all public, no key required):
  * OpenAPI  https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL   latest OHLCV for all listed
  * OpenAPI  https://openapi.twse.com.tw/v1/opendata/t187ap03_L            listed company master
  * WWW      https://www.twse.com.tw/exchangeReport/STOCK_DAY               monthly history per stock
  * WWW      https://www.twse.com.tw/fund/T86                               三大法人買賣超日報
  * WWW      https://www.twse.com.tw/exchangeReport/MI_MARGN                融資融券彙總
"""
from __future__ import annotations

import logging
from datetime import date

from ..utils import roc_compact_to_date, roc_to_date, to_float, to_int, yyyymmdd
from .base import HttpClient

log = logging.getLogger(__name__)

OPENAPI = "https://openapi.twse.com.tw/v1"
WWW = "https://www.twse.com.tw"


def _sign(cell: str) -> int | None:
    """MI_INDEX encodes direction as HTML: '<p style=color:red>+</p>' / green '-' / 'X' (no reference price)."""
    s = (cell or "").strip()
    if "+" in s:
        return 1
    if "-" in s:
        return -1
    if "X" in s.upper():
        return None
    return 0


def _parse_counts(rows: list[list[str]]) -> dict:
    """漲跌證券數合計 table -> {"advance", "decline", "flat", "limit_up", "limit_down"} for 股票 (column 2)."""
    import re

    out = {"advance": 0, "decline": 0, "flat": 0, "limit_up": 0, "limit_down": 0, "untraded": 0}
    for r in rows:
        if len(r) < 3:
            continue
        label, cell = r[0], r[2]
        m = re.match(r"\s*([\d,]+)(?:\((\d+)\))?", cell)
        if not m:
            continue
        n = int(m.group(1).replace(",", ""))
        extra = int(m.group(2)) if m.group(2) else 0
        if label.startswith("上漲"):
            out["advance"], out["limit_up"] = n, extra
        elif label.startswith("下跌"):
            out["decline"], out["limit_down"] = n, extra
        elif label.startswith("持平"):
            out["flat"] = n
        elif label.startswith("未成交"):
            out["untraded"] = n
    return out


class TWSEClient:
    market = "TWSE"

    def __init__(self, http: HttpClient):
        self.http = http

    # ------------------------------------------------------------------ master
    def fetch_stock_list(self) -> list[dict]:
        rows = self.http.get_json(f"{OPENAPI}/opendata/t187ap03_L")
        out = []
        for r in rows:
            code = (r.get("公司代號") or "").strip()
            if not code:
                continue
            out.append(
                {
                    "code": code,
                    "name": (r.get("公司簡稱") or r.get("公司名稱") or "").strip(),
                    "market": self.market,
                    "industry": (r.get("產業別") or "").strip() or None,
                }
            )
        return out

    # ------------------------------------------------------------------ daily
    def fetch_daily_all(self) -> list[dict]:
        """Latest trading day OHLCV for every listed security (one request)."""
        rows = self.http.get_json(f"{OPENAPI}/exchangeReport/STOCK_DAY_ALL")
        out = []
        for r in rows:
            d = roc_compact_to_date(r.get("Date", ""))
            code = (r.get("Code") or "").strip()
            if not d or not code:
                continue
            out.append(
                {
                    "code": code,
                    "name": (r.get("Name") or "").strip(),
                    "date": d,
                    "open": to_float(r.get("OpeningPrice")),
                    "high": to_float(r.get("HighestPrice")),
                    "low": to_float(r.get("LowestPrice")),
                    "close": to_float(r.get("ClosingPrice")),
                    "volume": to_int(r.get("TradeVolume")),
                    "turnover": to_float(r.get("TradeValue")),
                    "transactions": to_int(r.get("Transaction")),
                    "change": to_float(r.get("Change")),
                }
            )
        return out

    def fetch_daily_history(self, code: str, year: int, month: int) -> list[dict]:
        """One month of daily OHLCV for a single stock."""
        params = {"response": "json", "date": f"{year}{month:02d}01", "stockNo": code}
        data = self.http.get_json(f"{WWW}/exchangeReport/STOCK_DAY", params=params)
        if data.get("stat") != "OK":
            log.info("STOCK_DAY %s %d-%02d: %s", code, year, month, data.get("stat"))
            return []
        out = []
        for row in data.get("data", []):
            d = roc_to_date(row[0])
            if not d:
                continue
            out.append(
                {
                    "code": code,
                    "date": d,
                    "volume": to_int(row[1]),
                    "turnover": to_float(row[2]),
                    "open": to_float(row[3]),
                    "high": to_float(row[4]),
                    "low": to_float(row[5]),
                    "close": to_float(row[6]),
                    "change": to_float(row[7]),
                    "transactions": to_int(row[8]),
                }
            )
        return out

    # ------------------------------------------------------------------ whole market (MI_INDEX)
    def fetch_market_day(self, d: date) -> dict:
        """每日收盤行情(全部) for one date: all listed securities + official advance/decline
        counts + every TWSE price index (incl. 類股指數). One request.

        Returns {"date", "prices": [daily rows], "counts": {...}|None, "indices": [{name, close, change_pct}]}.
        """
        params = {"response": "json", "date": yyyymmdd(d), "type": "ALLBUT0999"}
        data = self.http.get_json(f"{WWW}/exchangeReport/MI_INDEX", params=params)
        out = {"date": d, "prices": [], "counts": None, "indices": []}
        if data.get("stat") != "OK":
            return out
        for t in data.get("tables", []):
            title = t.get("title") or ""
            fields = t.get("fields") or []
            rows = t.get("data") or []
            if "每日收盤行情" in title:
                for r in rows:
                    if len(r) < 11:
                        continue
                    sign = _sign(r[9])
                    diff = to_float(r[10])
                    close = to_float(r[8])
                    out["prices"].append(
                        {
                            "code": r[0].strip(),
                            "name": r[1].strip(),
                            "date": d,
                            "volume": to_int(r[2]),
                            "transactions": to_int(r[3]),
                            "turnover": to_float(r[4]),
                            "open": to_float(r[5]),
                            "high": to_float(r[6]),
                            "low": to_float(r[7]),
                            "close": close,
                            "change": (sign * diff) if (sign is not None and diff is not None) else None,
                        }
                    )
            elif "漲跌證券數" in title:
                out["counts"] = _parse_counts(rows)
            elif "價格指數" in title and "臺灣證券交易所" in title and fields and fields[0] == "指數":
                for r in rows:
                    if len(r) < 5:
                        continue
                    # 漲跌百分比 is already signed ('-1.45'); the HTML sign column only confirms direction
                    pct = to_float(r[4])
                    sign = _sign(r[2])
                    if pct is not None and sign is not None and sign != 0 and (pct > 0) != (sign > 0):
                        pct = -pct
                    out["indices"].append({"name": r[0].strip(), "close": to_float(r[1]), "change_pct": pct})
        return out

    # ------------------------------------------------------------------ institutional
    def fetch_institutional(self, d: date) -> list[dict]:
        """三大法人買賣超日報 (T86). Units: shares."""
        params = {"response": "json", "date": yyyymmdd(d), "selectType": "ALLBUT0999"}
        data = self.http.get_json(f"{WWW}/fund/T86", params=params)
        if data.get("stat") != "OK":
            return []
        out = []
        for r in data.get("data", []):
            # 0 code, 1 name, 2-4 外陸資(不含自營) 買/賣/超, 5-7 外資自營商 買/賣/超,
            # 8-10 投信 買/賣/超, 11 自營商買賣超, 12-17 自營商細項, 18 三大法人買賣超
            if len(r) < 19:
                continue
            f_buy = (to_int(r[2]) or 0) + (to_int(r[5]) or 0)
            f_sell = (to_int(r[3]) or 0) + (to_int(r[6]) or 0)
            out.append(
                {
                    "code": r[0].strip(),
                    "date": d,
                    "foreign_buy": f_buy,
                    "foreign_sell": f_sell,
                    "foreign_net": f_buy - f_sell,
                    "trust_buy": to_int(r[8]),
                    "trust_sell": to_int(r[9]),
                    "trust_net": to_int(r[10]),
                    "dealer_net": to_int(r[11]),
                    "total_net": to_int(r[18]),
                }
            )
        return out

    # ------------------------------------------------------------------ margin
    def fetch_margin(self, d: date) -> list[dict]:
        """融資融券彙總 (MI_MARGN). Units: lots (張)."""
        params = {"response": "json", "date": yyyymmdd(d), "selectType": "ALL"}
        data = self.http.get_json(f"{WWW}/exchangeReport/MI_MARGN", params=params)
        if data.get("stat") != "OK":
            return []
        table = None
        for t in data.get("tables", []):
            if "融資融券彙總" in (t.get("title") or ""):
                table = t
                break
        if not table:
            return []
        out = []
        for r in table.get("data", []):
            # 0 code,1 name, 2 資買,3 資賣,4 現償,5 前日餘額,6 今日餘額,7 限額,
            # 8 券買,9 券賣,10 券償,11 券前日,12 券今日,13 券限額,14 資券互抵,15 註記
            if len(r) < 15:
                continue
            out.append(
                {
                    "code": r[0].strip(),
                    "date": d,
                    "margin_buy": to_int(r[2]),
                    "margin_sell": to_int(r[3]),
                    "margin_redeem": to_int(r[4]),
                    "margin_prev": to_int(r[5]),
                    "margin_balance": to_int(r[6]),
                    "margin_limit": to_int(r[7]),
                    "short_buy": to_int(r[8]),
                    "short_sell": to_int(r[9]),
                    "short_redeem": to_int(r[10]),
                    "short_prev": to_int(r[11]),
                    "short_balance": to_int(r[12]),
                    "short_limit": to_int(r[13]),
                    "offset": to_int(r[14]),
                }
            )
        return out
