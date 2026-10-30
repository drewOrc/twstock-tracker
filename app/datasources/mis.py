"""TWSE MIS real-time quote feed (covers both listed tse_ and OTC otc_ securities).

https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_2330.tw|otc_6488.tw&json=1&delay=0
Quotes are delayed a few seconds; the endpoint tolerates roughly one request every few seconds.
"""
from __future__ import annotations

import logging
from datetime import date

from ..utils import to_float, to_int
from .base import HttpClient

log = logging.getLogger(__name__)

MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
MIS_HEADERS = {"Referer": "https://mis.twse.com.tw/stock/index.jsp"}

MARKET_PREFIX = {"TWSE": "tse", "TPEX": "otc"}


def _first_level(s: str | None) -> float | None:
    """Best bid/ask string like 2370.0000_2375.0000_... -> 2370.0"""
    if not s:
        return None
    return to_float(s.split("_")[0])


class MISClient:
    def __init__(self, http: HttpClient):
        self.http = http

    def fetch_quotes(self, items: list[tuple[str, str]]) -> list[dict]:
        """items: [(code, market)] -> list of quote dicts. Requests are batched 50 codes at a time."""
        out: list[dict] = []
        for i in range(0, len(items), 50):
            chunk = items[i : i + 50]
            ex_ch = "|".join(f"{MARKET_PREFIX.get(m, 'tse')}_{c}.tw" for c, m in chunk)
            data = self.http.get_json(
                MIS_URL, params={"ex_ch": ex_ch, "json": "1", "delay": "0"}, headers=MIS_HEADERS
            )
            for msg in data.get("msgArray", []):
                q = self._parse(msg)
                if q:
                    out.append(q)
        return out

    @staticmethod
    def _parse(m: dict) -> dict | None:
        code = (m.get("c") or "").strip()
        if not code:
            return None
        price = to_float(m.get("z"))
        if price is None:
            price = to_float(m.get("pz"))  # last matched price when z is a dash
        bid = _first_level(m.get("b"))
        ask = _first_level(m.get("a"))
        if price is None and bid and ask:
            price = round((bid + ask) / 2, 2)
        prev = to_float(m.get("y"))
        change = round(price - prev, 2) if price is not None and prev else None
        pct = round(change / prev * 100, 2) if change is not None and prev else None
        d = m.get("d") or ""
        trade_date = date(int(d[:4]), int(d[4:6]), int(d[6:8])) if len(d) == 8 and d.isdigit() else None
        t = m.get("t")
        return {
            "code": code,
            "name": m.get("n"),
            "market": "TPEX" if m.get("ex") == "otc" else "TWSE",
            "price": price,
            "open": to_float(m.get("o")),
            "high": to_float(m.get("h")),
            "low": to_float(m.get("l")),
            "prev_close": prev,
            "change": change,
            "change_pct": pct,
            "volume": to_int(m.get("v")),
            "bid": bid,
            "ask": ask,
            "trade_date": trade_date,
            "trade_time": t if t and ":" in t else None,
            "limit_up": to_float(m.get("u")),
            "limit_down": to_float(m.get("w")),
        }
