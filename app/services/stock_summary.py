"""One-page stock summary (基本介紹 + 最近狀況) assembled from data the engine already keeps,
plus a light news feed. Numbers only; written analysis lives in Stock CRM's company briefs."""
from __future__ import annotations

import logging
import math
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from urllib.parse import quote

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    AlertEvent,
    AlertRule,
    DailyPrice,
    IndexDaily,
    RealtimeQuote,
    ScreenerResult,
    Stock,
    Watchlist,
    WatchlistItem,
)
from . import industry_chains
from . import knowledge as kn
from . import market_data as md
from .indicators import compute_all
from .industries import MAIN_INDEX, is_common_stock, sector_name

log = logging.getLogger(__name__)

NEWS_TTL = 900  # seconds
NEWS_LIMIT = 10
_news_cache: dict[str, tuple[float, list[dict], str | None]] = {}


def _f(v) -> float | None:
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else round(v, 4)


def _pct(a: float | None, b: float | None) -> float | None:
    """(a / b - 1) * 100"""
    if a is None or b in (None, 0):
        return None
    return round((a / b - 1) * 100, 2)


# ---------------------------------------------------------------------- profile
def profile(stock: Stock) -> dict:
    return {
        "code": stock.code,
        "name": stock.name,
        "full_name": stock.full_name,
        "name_en": stock.name_en,
        "market": stock.market,
        "market_label": "上櫃" if stock.market == "TPEX" else "上市",
        "industry": stock.industry,
        "sector": sector_name(stock.code, stock.industry),
        "is_common_stock": is_common_stock(stock.code),
        "chairman": stock.chairman,
        "general_manager": stock.general_manager,
        "founded": stock.founded,
        "listed_date": stock.listed_date,
        "capital": stock.capital,
        "capital_yi": round(stock.capital / 1e8, 2) if stock.capital else None,
        "shares_issued": stock.shares_issued,
        "website": stock.website,
        "address": stock.address,
    }


# ---------------------------------------------------------------------- price block
def _closes_at(db: Session, codes: list[str], days: list[date]) -> dict[str, dict[date, float]]:
    out: dict[str, dict[date, float]] = {}
    if not codes or not days:
        return out
    for i in range(0, len(codes), 500):
        rows = db.execute(
            select(DailyPrice.code, DailyPrice.date, DailyPrice.close).where(
                DailyPrice.code.in_(codes[i : i + 500]), DailyPrice.date.in_(days), DailyPrice.close.isnot(None)
            )
        )
        for c, d, close in rows:
            out.setdefault(c, {})[d] = close
    return out


def price_block(db: Session, stock: Stock) -> dict:
    df = md.load_daily_df(db, stock.code, 260)
    if df.empty:
        return {"available": False}
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    n = len(df)
    last = df.iloc[-1]
    close = float(last["close"])
    dates = list(df["date"])

    def back(k: int):
        return df.iloc[-1 - k] if n > k else None

    windows = {"1d": 1, "5d": 5, "20d": 20, "60d": 60, "120d": 120, "250d": 250}
    ret = {k: _pct(close, float(back(v)["close"])) if back(v) is not None else None for k, v in windows.items()}

    # index over the same dates
    anchor_dates = {k: back(v)["date"] for k, v in windows.items() if back(v) is not None}
    idx_rows = db.execute(
        select(IndexDaily.date, IndexDaily.close).where(IndexDaily.name == MAIN_INDEX, IndexDaily.date.in_([last["date"], *anchor_dates.values()]))
    ).all()
    idx = {d: c for d, c in idx_rows}
    idx_last = idx.get(last["date"])
    index_ret = {k: _pct(idx_last, idx.get(d)) for k, d in anchor_dates.items()}
    rel = {k: round(ret[k] - index_ret[k], 2) if ret.get(k) is not None and index_ret.get(k) is not None else None for k in windows}

    # sector peers (same industry, common stocks): mean 20d return and this stock's rank
    sector_block = {"name": sector_name(stock.code, stock.industry), "peers": 0, "ret_20d": None, "rank_20d": None, "ret_5d": None}
    if stock.industry and is_common_stock(stock.code) and back(20) is not None:
        peers = list(db.execute(select(Stock.code).where(Stock.industry == stock.industry)).scalars())
        peers = [p for p in peers if is_common_stock(p)]
        d0, d20, d5 = last["date"], back(20)["date"], back(5)["date"] if back(5) is not None else None
        closes = _closes_at(db, peers, [d0, d20] + ([d5] if d5 else []))
        rets20 = {c: _pct(v.get(d0), v.get(d20)) for c, v in closes.items() if v.get(d0) and v.get(d20)}
        rets5 = [_pct(v.get(d0), v.get(d5)) for v in closes.values() if d5 and v.get(d0) and v.get(d5)]
        if rets20:
            vals = sorted(rets20.values(), reverse=True)
            sector_block.update(
                {
                    "peers": len(rets20),
                    "ret_20d": round(sum(vals) / len(vals), 2),
                    "rank_20d": (vals.index(rets20[stock.code]) + 1) if stock.code in rets20 else None,
                    "ret_5d": round(sum(rets5) / len(rets5), 2) if rets5 else None,
                }
            )

    hi, lo = float(df["high"].max()), float(df["low"].min())
    ind = compute_all(df) if n >= 3 else None
    il = ind.iloc[-1] if ind is not None else None
    ma = {k: _f(il[k]) if il is not None and k in il else None for k in ("ma5", "ma20", "ma60", "ma120")}
    alignment = None
    if ma["ma5"] and ma["ma20"]:
        bull = close > ma["ma5"] > ma["ma20"] and (ma["ma60"] is None or ma["ma20"] > ma["ma60"])
        bear = close < ma["ma5"] < ma["ma20"] and (ma["ma60"] is None or ma["ma20"] < ma["ma60"])
        alignment = "多頭排列" if bull else "空頭排列" if bear else "盤整"
    vol = float(last["volume"]) if last["volume"] is not None else None
    vol_ma20 = _f(il["vol_ma20"]) if il is not None else None

    q = db.get(RealtimeQuote, stock.code)
    return {
        "available": True,
        "as_of": last["date"].isoformat(),
        "history_days": n,
        "close": close,
        "change": _f(last["change"]),
        "change_pct": ret["1d"],
        "quote": {
            "price": q.price, "change": q.change, "change_pct": q.change_pct, "volume_lots": q.volume,
            "time": f"{q.trade_date} {q.trade_time or ''}".strip() if q and q.trade_date else None,
        } if q and q.price is not None else None,
        "returns": {k: ret[k] for k in windows},
        "index_returns": index_ret,
        "relative": rel,
        "sector": sector_block,
        "range": {
            "high": hi, "low": lo, "from_high_pct": _pct(close, hi), "from_low_pct": _pct(close, lo),
            "days": n, "label": "52 週" if n >= 240 else f"近 {n} 日",
        },
        "ma": ma,
        "alignment": alignment,
        "rsi14": _f(il["rsi14"]) if il is not None else None,
        "k": _f(il["k"]) if il is not None else None,
        "d": _f(il["d"]) if il is not None else None,
        "volume_lots": round(vol / 1000) if vol is not None else None,
        "volume_ratio": round(vol / vol_ma20, 2) if vol is not None and vol_ma20 else None,
        "first_date": dates[0].isoformat(),
    }


# ---------------------------------------------------------------------- chips block
def chips_block(db: Session, code: str) -> dict:
    inst = md.load_institutional(db, code, 20)  # newest first
    margin = md.load_margin(db, code, 21)

    def s(rows, field, k):
        vals = [getattr(r, field) for r in rows[:k] if getattr(r, field) is not None]
        return round(sum(vals) / 1000) if vals else None

    out: dict = {"available": bool(inst or margin)}
    if inst:
        out["as_of"] = inst[0].date.isoformat()
        for who in ("foreign", "trust", "dealer", "total"):
            out[f"{who}_5d"] = s(inst, f"{who}_net", 5)
            out[f"{who}_20d"] = s(inst, f"{who}_net", 20)
        streak = 0
        for r in inst:
            if r.foreign_net is not None and r.foreign_net > 0:
                streak += 1
            else:
                break
        out["foreign_streak"] = streak
    if margin:
        m0, mk = margin[0], margin[min(20, len(margin) - 1)]
        out["margin_balance"] = m0.margin_balance
        out["margin_change_20d"] = (m0.margin_balance - mk.margin_balance) if m0.margin_balance is not None and mk.margin_balance is not None else None
        out["margin_change_20d_pct"] = _pct(m0.margin_balance, mk.margin_balance)
        out["short_balance"] = m0.short_balance
        out["margin_as_of"] = m0.date.isoformat()
    return out


# ---------------------------------------------------------------------- context block
def context_block(db: Session, code: str, user_id: int | None = None) -> dict:
    """Screener placement is shared; alerts and lists are the caller's own when user_id is given."""
    latest_date = db.execute(select(func.max(ScreenerResult.date)).where(ScreenerResult.code == code)).scalar()
    screens = []
    if latest_date:
        for r in db.execute(select(ScreenerResult).where(ScreenerResult.code == code, ScreenerResult.date == latest_date).order_by(ScreenerResult.preset)).scalars():
            screens.append({"preset": r.preset, "date": r.date.isoformat(), "rank": r.rank, "score": r.score, "tags": r.tags})
    ev_stmt = select(AlertEvent).where(AlertEvent.code == code).order_by(AlertEvent.triggered_at.desc()).limit(5)
    rule_stmt = select(func.count()).select_from(AlertRule).where(AlertRule.code == code, AlertRule.enabled.is_(True))
    list_stmt = (
        select(Watchlist.id, Watchlist.name, Watchlist.system_key, Watchlist.color)
        .join(WatchlistItem, WatchlistItem.watchlist_id == Watchlist.id)
        .where(WatchlistItem.code == code)
        .order_by(Watchlist.sort_order)
    )
    if user_id is not None:
        ev_stmt = ev_stmt.where(AlertEvent.user_id == user_id)
        rule_stmt = rule_stmt.where(AlertRule.user_id == user_id)
        list_stmt = list_stmt.where(Watchlist.user_id == user_id)
    events = db.execute(ev_stmt).scalars()
    rules = db.execute(rule_stmt).scalar()
    lists = db.execute(list_stmt).all()
    return {
        "knowledge": kn.for_stock(db, code),
        "chains": industry_chains.for_company(db, kn.company_id_for(code), peers_limit=12),
        "screener": screens,
        "alert_rules": rules,
        "recent_alerts": [{"at": e.triggered_at.isoformat(timespec="seconds"), "message": e.message, "rule_type": e.rule_type} for e in events],
        "lists": [{"id": i, "name": n, "system_key": k, "color": c} for i, n, k, c in lists],
    }


# ---------------------------------------------------------------------- news
def fetch_news(name: str, limit: int = NEWS_LIMIT) -> tuple[list[dict], str | None]:
    """Latest headlines from Google News RSS (zh-TW). Cached per name for NEWS_TTL seconds."""
    now = time.time()
    hit = _news_cache.get(name)
    if hit and now - hit[0] < NEWS_TTL:
        return hit[1][:limit], hit[2]
    url = f"https://news.google.com/rss/search?q={quote(name)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        r = httpx.get(url, timeout=6.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        items = parse_rss(r.text)
        err = None
    except Exception as exc:  # noqa: BLE001
        log.info("news fetch failed for %s: %s", name, exc)
        items, err = (hit[1] if hit else []), f"{type(exc).__name__}"
    _news_cache[name] = (now, items, err)
    return items[:limit], err


def parse_rss(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        src_el = item.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        if title:
            out.append({"title": title, "link": link, "published": pub, "source": source})
    return out


# ---------------------------------------------------------------------- assemble
def stock_summary(db: Session, code: str, with_news: bool = True, user_id: int | None = None) -> dict:
    code = code.strip().upper()
    stock = db.get(Stock, code)
    if stock is None:
        stock = md.ensure_stock(db, code)  # raises ValueError when unknown
    out = {
        "code": code,
        "profile": profile(stock),
        "price": price_block(db, stock),
        "chips": chips_block(db, code),
        "context": context_block(db, code, user_id),
    }
    if with_news:
        items, err = fetch_news(stock.name or code)
        out["news"] = {"items": items, "error": err, "query": stock.name or code}
    return out


def recent_business_days(n: int) -> list[date]:
    return md.business_days_back(md.last_business_day(), n)


__all__ = ["stock_summary", "fetch_news", "parse_rss", "profile", "price_block", "chips_block", "context_block", "timedelta"]
