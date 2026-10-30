"""Fetch + persist daily prices, institutional flows, margin balances and realtime quotes."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..config import settings
from ..datasources import CLIENTS, mis, tpex, twse
from ..db import engine
from ..models import (
    DailyPrice,
    InstitutionalFlow,
    MarginBalance,
    RealtimeQuote,
    Stock,
    WatchlistItem,
)
from ..utils import today_tw

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------- helpers
def upsert(db: Session, model, rows: list[dict], conflict_cols: list[str], chunk: int = 300) -> int:
    """Insert-or-update rows keyed by conflict_cols (SQLite ON CONFLICT; generic merge fallback).

    Only keys present in each row are written, so columns a source does not provide keep
    their existing / default values.
    """
    if not rows:
        return 0
    table = model.__table__
    cols = {c.name for c in table.columns if c.name != "id"}
    clean = [{k: v for k, v in r.items() if k in cols} for r in rows]

    if engine.dialect.name == "sqlite":
        groups: dict[frozenset, list[dict]] = defaultdict(list)
        for r in clean:
            groups[frozenset(r.keys())].append(r)
        for keys, group in groups.items():
            for i in range(0, len(group), chunk):
                part = group[i : i + chunk]
                stmt = sqlite_insert(table).values(part)
                update_cols = {c: getattr(stmt.excluded, c) for c in keys if c not in conflict_cols}
                stmt = stmt.on_conflict_do_update(index_elements=conflict_cols, set_=update_cols)
                db.execute(stmt)
    else:  # pragma: no cover - generic path for other databases
        for r in clean:
            cond = [getattr(model, c) == r[c] for c in conflict_cols]
            obj = db.execute(select(model).where(*cond)).scalar_one_or_none()
            if obj is None:
                db.add(model(**r))
            else:
                for k, v in r.items():
                    setattr(obj, k, v)
    return len(clean)


def business_days_back(start: date, n: int) -> list[date]:
    """n most recent weekdays ending at start (inclusive), newest first. Holidays are not filtered."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def last_business_day(d: date | None = None) -> date:
    d = d or today_tw()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


# ---------------------------------------------------------------------- master list
def refresh_stock_list(db: Session) -> int:
    rows: list[dict] = []
    now = datetime.now()
    for client in (twse, tpex):
        try:
            for r in client.fetch_stock_list():
                r["updated_at"] = now
                rows.append(r)
        except Exception as exc:  # noqa: BLE001
            log.warning("stock list fetch failed for %s: %s", client.market, exc)
    n = upsert(db, Stock, rows, ["code"])
    db.commit()
    log.info("stock list refreshed: %d rows", n)
    return n


def stock_list_is_stale(db: Session) -> bool:
    newest = db.execute(select(func.max(Stock.updated_at))).scalar()
    return newest is None or (datetime.now() - newest) > timedelta(days=1)


def ensure_stock(db: Session, code: str) -> Stock:
    """Return the Stock row for code, discovering market/name if needed."""
    code = code.strip().upper()
    stock = db.get(Stock, code)
    if stock:
        return stock
    if stock_list_is_stale(db):
        refresh_stock_list(db)
        stock = db.get(Stock, code)
        if stock:
            return stock
    # ETFs and some securities are not in the company master; probe the realtime feed instead
    for market in ("TWSE", "TPEX"):
        try:
            quotes = mis.fetch_quotes([(code, market)])
        except Exception:  # noqa: BLE001
            quotes = []
        if quotes and quotes[0].get("name"):
            stock = Stock(code=code, name=quotes[0]["name"], market=market, updated_at=datetime.now())
            db.add(stock)
            db.commit()
            return stock
    raise ValueError(f"unknown security code: {code}")


def search_stocks(db: Session, q: str, limit: int = 20) -> list[Stock]:
    if not db.execute(select(func.count()).select_from(Stock)).scalar():
        refresh_stock_list(db)
    like = f"%{q.strip()}%"
    stmt = select(Stock).where((Stock.code.like(like)) | (Stock.name.like(like))).order_by(Stock.code).limit(limit)
    return list(db.execute(stmt).scalars())


# ---------------------------------------------------------------------- watchlist helpers
def watchlist_items(db: Session) -> list[WatchlistItem]:
    return list(db.execute(select(WatchlistItem).order_by(WatchlistItem.added_at)).scalars())


def watch_codes(db: Session) -> set[str]:
    return {w.code for w in watchlist_items(db)}


# ---------------------------------------------------------------------- daily prices
def update_daily_prices(db: Session, codes: set[str] | None = None) -> dict:
    codes = codes if codes is not None else watch_codes(db)
    if not codes:
        return {"rows": 0, "date": None}
    rows: list[dict] = []
    for client in (twse, tpex):
        try:
            rows.extend(r for r in client.fetch_daily_all() if r["code"] in codes)
        except Exception as exc:  # noqa: BLE001
            log.warning("daily fetch failed for %s: %s", client.market, exc)
    n = upsert(db, DailyPrice, rows, ["code", "date"])
    db.commit()
    latest = max((r["date"] for r in rows), default=None)
    log.info("daily prices updated: %d rows (%s)", n, latest)
    return {"rows": n, "date": latest.isoformat() if latest else None}


def fill_missing_latest(db: Session, codes: set[str] | None = None) -> dict:
    """The TWSE OpenAPI "all stocks" feed can lag the per-stock monthly history by a day.
    For every watched code whose newest bar is older than the last business day, fetch the
    current month (1 request per code) so the latest close is present."""
    codes = codes if codes is not None else watch_codes(db)
    target = last_business_day()
    if not codes:
        return {"checked": 0, "filled": 0}
    latest = _latest_per_code(db, DailyPrice, codes)
    filled = 0
    for code in sorted(codes):
        row = latest.get(code)
        if row and row.date >= target:
            continue
        stock = db.get(Stock, code)
        if not stock:
            continue
        try:
            rows = CLIENTS[stock.market].fetch_daily_history(code, target.year, target.month)
        except Exception as exc:  # noqa: BLE001
            log.warning("latest fill failed %s: %s", code, exc)
            continue
        n = upsert(db, DailyPrice, rows, ["code", "date"])
        db.commit()
        filled += 1 if n else 0
    return {"checked": len(codes), "filled": filled, "target": target.isoformat()}


def backfill_daily(db: Session, code: str, months: int | None = None) -> int:
    stock = ensure_stock(db, code)
    client = CLIENTS[stock.market]
    months = months or settings.backfill_months
    today = today_tw()
    total = 0
    y, m = today.year, today.month
    for _ in range(months):
        try:
            rows = client.fetch_daily_history(stock.code, y, m)
        except Exception as exc:  # noqa: BLE001
            log.warning("history fetch failed %s %d-%02d: %s", stock.code, y, m, exc)
            rows = []
        total += upsert(db, DailyPrice, rows, ["code", "date"])
        db.commit()
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    log.info("backfilled %s: %d rows", stock.code, total)
    return total


def load_daily_df(db: Session, code: str, limit: int = 300) -> pd.DataFrame:
    stmt = select(DailyPrice).where(DailyPrice.code == code).order_by(DailyPrice.date.desc()).limit(limit)
    rows = db.execute(stmt).scalars().all()
    if not rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "turnover", "change"])
    df = pd.DataFrame(
        [
            {
                "date": r.date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
                "turnover": r.turnover,
                "change": r.change,
            }
            for r in rows
        ]
    )
    return df.sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------------- institutional / margin
# Institutional flows and margin balances are stored for the WHOLE market (the exchange returns
# every security in one response anyway), so the screener can rank all stocks on chips.
FULL_DAY_MIN_ROWS = 300  # a date with fewer rows than this was only partially stored


def _fetch_flows_for_date(d: date) -> tuple[list[dict], list[dict]]:
    inst: list[dict] = []
    margin: list[dict] = []
    for client in (twse, tpex):
        try:
            inst.extend(client.fetch_institutional(d))
        except Exception as exc:  # noqa: BLE001
            log.warning("institutional fetch failed %s %s: %s", client.market, d, exc)
        try:
            margin.extend(client.fetch_margin(d))
        except Exception as exc:  # noqa: BLE001
            log.warning("margin fetch failed %s %s: %s", client.market, d, exc)
    return inst, margin


def update_institutional(db: Session, d: date | None = None) -> dict:
    d = last_business_day(d)
    rows: list[dict] = []
    for client in (twse, tpex):
        try:
            rows.extend(client.fetch_institutional(d))
        except Exception as exc:  # noqa: BLE001
            log.warning("institutional fetch failed %s: %s", client.market, exc)
    n = upsert(db, InstitutionalFlow, rows, ["code", "date"])
    db.commit()
    log.info("institutional updated %s: %d rows", d, n)
    return {"rows": n, "date": d.isoformat()}


def update_margin(db: Session, d: date | None = None) -> dict:
    d = last_business_day(d)
    rows: list[dict] = []
    for client in (twse, tpex):
        try:
            rows.extend(client.fetch_margin(d))
        except Exception as exc:  # noqa: BLE001
            log.warning("margin fetch failed %s: %s", client.market, exc)
    n = upsert(db, MarginBalance, rows, ["code", "date"])
    db.commit()
    log.info("margin updated %s: %d rows", d, n)
    return {"rows": n, "date": d.isoformat()}


def _full_dates(db: Session, model, since: date) -> set[date]:
    stmt = select(model.date).where(model.date >= since).group_by(model.date).having(func.count() >= FULL_DAY_MIN_ROWS)
    return set(db.execute(stmt).scalars())


def backfill_flows(db: Session, days: int = 20, check_codes: set[str] | None = None) -> dict:
    """Fill whole-market institutional + margin history for the last N business days.
    A date is fetched (2 requests) only if it is not already stored in full."""
    dates = business_days_back(last_business_day(), days)
    have_inst = _full_dates(db, InstitutionalFlow, dates[-1])
    have_margin = _full_dates(db, MarginBalance, dates[-1])
    fetched, inst_total, margin_total = 0, 0, 0
    for d in dates:
        if d in have_inst and d in have_margin:
            continue
        inst, margin = _fetch_flows_for_date(d)
        inst_total += upsert(db, InstitutionalFlow, inst, ["code", "date"])
        margin_total += upsert(db, MarginBalance, margin, ["code", "date"])
        db.commit()
        fetched += 1
    log.info("flows backfill: %d dates, %d inst rows, %d margin rows", fetched, inst_total, margin_total)
    return {"dates": fetched, "inst_rows": inst_total, "margin_rows": margin_total}


def load_institutional(db: Session, code: str, limit: int = 60) -> list[InstitutionalFlow]:
    stmt = (
        select(InstitutionalFlow)
        .where(InstitutionalFlow.code == code)
        .order_by(InstitutionalFlow.date.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def load_margin(db: Session, code: str, limit: int = 60) -> list[MarginBalance]:
    stmt = select(MarginBalance).where(MarginBalance.code == code).order_by(MarginBalance.date.desc()).limit(limit)
    return list(db.execute(stmt).scalars())


# ---------------------------------------------------------------------- realtime
def update_realtime(db: Session, codes: set[str] | None = None) -> list[dict]:
    items = watchlist_items(db)
    pairs = [(w.code, w.stock.market if w.stock else "TWSE") for w in items if codes is None or w.code in codes]
    if not pairs:
        return []
    quotes = mis.fetch_quotes(pairs)
    rows = []
    for q in quotes:
        r = {k: v for k, v in q.items() if k not in ("limit_up", "limit_down")}
        r["updated_at"] = datetime.now()
        rows.append(r)
    upsert(db, RealtimeQuote, rows, ["code"])
    db.commit()
    return quotes


def load_realtime(db: Session, codes: set[str] | None = None) -> list[RealtimeQuote]:
    stmt = select(RealtimeQuote)
    if codes:
        stmt = stmt.where(RealtimeQuote.code.in_(codes))
    return list(db.execute(stmt).scalars())


# ---------------------------------------------------------------------- overview
def _latest_per_code(db: Session, model, codes: set[str]) -> dict:
    """Return {code: latest row} for a model that has code + date columns."""
    if not codes:
        return {}
    sub = (
        select(model.code, func.max(model.date).label("d"))
        .where(model.code.in_(codes))
        .group_by(model.code)
        .subquery()
    )
    stmt = select(model).join(sub, (model.code == sub.c.code) & (model.date == sub.c.d))
    return {r.code: r for r in db.execute(stmt).scalars()}


def _prev_daily(db: Session, latest: dict) -> dict:
    """The daily bar before the latest one, per code."""
    out = {}
    for code, row in latest.items():
        stmt = (
            select(DailyPrice)
            .where(DailyPrice.code == code, DailyPrice.date < row.date)
            .order_by(DailyPrice.date.desc())
            .limit(1)
        )
        prev = db.execute(stmt).scalar_one_or_none()
        if prev:
            out[code] = prev
    return out


def _lots(shares: int | None) -> int | None:
    return round(shares / 1000) if shares is not None else None


def watchlist_overview(db: Session) -> list[dict]:
    items = watchlist_items(db)
    codes = {w.code for w in items}
    rt = {q.code: q for q in load_realtime(db, codes)}
    daily = _latest_per_code(db, DailyPrice, codes)
    prev = _prev_daily(db, daily)
    inst = _latest_per_code(db, InstitutionalFlow, codes)
    margin = _latest_per_code(db, MarginBalance, codes)
    out = []
    for w in items:
        q = rt.get(w.code)
        d = daily.get(w.code)
        p = prev.get(w.code)
        i = inst.get(w.code)
        m = margin.get(w.code)
        use_rt = bool(q and q.price is not None)
        price = q.price if use_rt else (d.close if d else None)
        prev_close = q.prev_close if use_rt and q.prev_close else (p.close if p else None)
        change = round(price - prev_close, 2) if price is not None and prev_close else None
        pct = round(change / prev_close * 100, 2) if change is not None and prev_close else None
        out.append(
            {
                "code": w.code,
                "name": w.stock.name if w.stock else None,
                "market": w.stock.market if w.stock else None,
                "note": w.note,
                "tags": w.tags,
                "price": price,
                "prev_close": prev_close,
                "change": change,
                "change_pct": pct,
                "open": q.open if use_rt else (d.open if d else None),
                "high": q.high if use_rt else (d.high if d else None),
                "low": q.low if use_rt else (d.low if d else None),
                "volume_lots": q.volume if use_rt and q.volume is not None else _lots(d.volume if d else None),
                "quote_time": f"{q.trade_date} {q.trade_time or ''}".strip() if use_rt and q.trade_date else None,
                "realtime": use_rt,
                "daily_date": d.date.isoformat() if d else None,
                "foreign_net_lots": _lots(i.foreign_net) if i else None,
                "trust_net_lots": _lots(i.trust_net) if i else None,
                "dealer_net_lots": _lots(i.dealer_net) if i else None,
                "total_net_lots": _lots(i.total_net) if i else None,
                "inst_date": i.date.isoformat() if i else None,
                "margin_balance": m.margin_balance if m else None,
                "margin_change": (m.margin_balance - m.margin_prev)
                if m and m.margin_balance is not None and m.margin_prev is not None
                else None,
                "short_balance": m.short_balance if m else None,
                "short_change": (m.short_balance - m.short_prev)
                if m and m.short_balance is not None and m.short_prev is not None
                else None,
                "margin_date": m.date.isoformat() if m else None,
            }
        )
    return out
