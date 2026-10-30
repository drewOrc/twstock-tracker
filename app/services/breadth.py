"""盤面分化 - market breadth and sector divergence.

Data: one MI_INDEX request (TWSE) + one afterTrading/otc request (TPEx) per trading day gives
every security's close/change/turnover, the official TWSE advance/decline counts and all TWSE
price indices. Everything here is derived from those rows stored in daily_prices / market_stats /
index_daily.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..datasources import tpex, twse
from ..models import DailyPrice, IndexDaily, MarketStat, Stock
from .industries import MAIN_INDEX, TWSE_SECTOR_INDEX, is_common_stock, sector_name
from .market_data import business_days_back, last_business_day, upsert

log = logging.getLogger(__name__)

LIMIT_PCT = 9.5  # 10% daily limit; a few ticks of rounding tolerance
MIN_TURNOVER_FOR_MOVERS = 20_000_000  # NTD, filters illiquid names out of the top/bottom lists
BUCKETS = [(-100, -7), (-7, -5), (-5, -3), (-3, -1), (-1, 0), (0, 0), (0, 1), (1, 3), (3, 5), (5, 7), (7, 100)]


# ---------------------------------------------------------------------- ingestion
def _pct(close: float | None, change: float | None) -> float | None:
    if close is None or change is None:
        return None
    prev = close - change
    return round(change / prev * 100, 2) if prev > 0 else None


def _compute_stat(prices: list[dict], market: str, d: date) -> dict:
    adv = dec = flat = lu = ld = total = 0
    turnover = 0.0
    for p in prices:
        if not is_common_stock(p["code"]) or p.get("close") is None:
            continue
        total += 1
        turnover += p.get("turnover") or 0
        ch = p.get("change")
        if ch is None:
            continue
        pct = _pct(p["close"], ch) or 0
        if ch > 0:
            adv += 1
            lu += pct >= LIMIT_PCT
        elif ch < 0:
            dec += 1
            ld += pct <= -LIMIT_PCT
        else:
            flat += 1
    return {
        "market": market,
        "date": d,
        "advance": adv,
        "decline": dec,
        "flat": flat,
        "limit_up": lu,
        "limit_down": ld,
        "total": total,
        "turnover": turnover,
        "source": "computed",
    }


def update_market_day(db: Session, d: date | None = None) -> dict:
    """Fetch + store the whole market for one trading day (2 requests)."""
    d = last_business_day(d)
    result: dict = {"date": d.isoformat()}
    now = datetime.now()
    for client in (twse, tpex):
        try:
            day = client.fetch_market_day(d)
        except Exception as exc:  # noqa: BLE001
            log.warning("market day fetch failed %s %s: %s", client.market, d, exc)
            result[client.market] = {"error": str(exc)}
            continue
        prices = day["prices"]
        if not prices:
            result[client.market] = {"rows": 0}
            continue
        codes = [p["code"] for p in prices]
        known: set[str] = set()
        for i in range(0, len(codes), 500):
            known |= {c for (c,) in db.execute(select(Stock.code).where(Stock.code.in_(codes[i : i + 500])))}
        new_stocks = [
            {"code": p["code"], "name": p["name"], "market": client.market, "updated_at": now}
            for p in prices
            if p["code"] not in known
        ]
        upsert(db, Stock, new_stocks, ["code"])
        n = upsert(db, DailyPrice, [{k: v for k, v in p.items() if k != "name"} for p in prices], ["code", "date"])
        stat = _compute_stat(prices, client.market, d)
        if day.get("counts"):
            c = day["counts"]
            stat.update({k: c[k] for k in ("advance", "decline", "flat", "limit_up", "limit_down")})
            stat["source"] = "official"
        upsert(db, MarketStat, [stat], ["market", "date"])
        idx_rows = [{"name": i["name"], "date": d, "close": i["close"], "change_pct": i["change_pct"]} for i in day.get("indices") or []]
        upsert(db, IndexDaily, idx_rows, ["name", "date"])
        db.commit()
        result[client.market] = {"rows": n, "new_stocks": len(new_stocks), "indices": len(idx_rows), "breadth": stat["source"]}
    return result


def backfill_market(db: Session, days: int = 20) -> dict:
    """Store the last N business days of whole-market data (skips days already present)."""
    dates = business_days_back(last_business_day(), days)
    have = {
        (r.market, r.date)
        for r in db.execute(select(MarketStat.market, MarketStat.date).where(MarketStat.date >= dates[-1]))
    }
    fetched, skipped = 0, 0
    for d in dates:
        if ("TWSE", d) in have and ("TPEX", d) in have:
            skipped += 1
            continue
        update_market_day(db, d)
        fetched += 1
    return {"fetched": fetched, "skipped": skipped, "from": dates[-1].isoformat(), "to": dates[0].isoformat()}


# ---------------------------------------------------------------------- loading
def available_dates(db: Session, limit: int = 60) -> list[date]:
    rows = db.execute(select(MarketStat.date).distinct().order_by(MarketStat.date.desc()).limit(limit)).scalars()
    return list(rows)


def latest_date(db: Session) -> date | None:
    return db.execute(select(func.max(MarketStat.date))).scalar()


def _load_days(db: Session, dates: list[date]) -> pd.DataFrame:
    if not dates:
        return pd.DataFrame()
    stmt = (
        select(
            DailyPrice.code,
            DailyPrice.date,
            DailyPrice.close,
            DailyPrice.change,
            DailyPrice.turnover,
            DailyPrice.volume,
            Stock.name,
            Stock.market,
            Stock.industry,
        )
        .join(Stock, Stock.code == DailyPrice.code, isouter=True)
        .where(DailyPrice.date.in_(dates))
    )
    df = pd.DataFrame(db.execute(stmt).all(), columns=["code", "date", "close", "change", "turnover", "volume", "name", "market", "industry"])
    if df.empty:
        return df
    prev = df["close"] - df["change"]
    df["pct"] = (df["change"] / prev.where(prev > 0) * 100).round(2)
    df["common"] = df["code"].map(is_common_stock)
    df["sector"] = [sector_name(c, i) for c, i in zip(df["code"], df["industry"])]
    df["turnover"] = df["turnover"].fillna(0.0)
    return df


def _index_pct(db: Session, d: date) -> dict[str, float | None]:
    rows = db.execute(select(IndexDaily.name, IndexDaily.change_pct).where(IndexDaily.date == d)).all()
    return {n: p for n, p in rows}


# ---------------------------------------------------------------------- snapshot
def compute_breadth(db: Session, d: date | None = None) -> dict:
    d = d or latest_date(db)
    if d is None:
        return {"date": None, "available": False}
    df = _load_days(db, [d])
    if df.empty:
        return {"date": d.isoformat(), "available": False}
    common = df[df["common"] & df["pct"].notna()]
    stats = {r.market: r for r in db.execute(select(MarketStat).where(MarketStat.date == d)).scalars()}

    markets: dict[str, dict] = {}
    for m in ("TWSE", "TPEX"):
        sub = common[common["market"] == m]
        r = stats.get(m)
        if r is not None:
            mk = {
                "advance": r.advance or 0, "decline": r.decline or 0, "flat": r.flat or 0,
                "limit_up": r.limit_up or 0, "limit_down": r.limit_down or 0,
                "total": r.total or len(sub), "turnover": r.turnover or float(sub["turnover"].sum()), "source": r.source,
            }
        else:
            mk = {
                "advance": int((sub["change"] > 0).sum()), "decline": int((sub["change"] < 0).sum()),
                "flat": int((sub["change"] == 0).sum()), "limit_up": int((sub["pct"] >= LIMIT_PCT).sum()),
                "limit_down": int((sub["pct"] <= -LIMIT_PCT).sum()), "total": len(sub),
                "turnover": float(sub["turnover"].sum()), "source": "computed",
            }
        mk["median_pct"] = round(float(sub["pct"].median()), 2) if len(sub) else None
        mk["mean_pct"] = round(float(sub["pct"].mean()), 2) if len(sub) else None
        markets[m] = mk
    all_mk = {k: markets["TWSE"][k] + markets["TPEX"][k] for k in ("advance", "decline", "flat", "limit_up", "limit_down", "total", "turnover")}
    all_mk["median_pct"] = round(float(common["pct"].median()), 2) if len(common) else None
    all_mk["mean_pct"] = round(float(common["pct"].mean()), 2) if len(common) else None
    markets["ALL"] = all_mk
    for mk in markets.values():
        n = mk["advance"] + mk["decline"] + mk["flat"]
        mk["adv_ratio"] = round(mk["advance"] / n * 100, 1) if n else None

    idx = _index_pct(db, d)
    main_pct = idx.get(MAIN_INDEX)

    # sectors (common stocks only, both markets merged by industry name)
    total_turnover = float(common["turnover"].sum()) or 1.0
    sectors = []
    for name, g in common.groupby("sector"):
        g_sorted = g.sort_values("pct", ascending=False)
        liquid = g_sorted[g_sorted["turnover"] >= MIN_TURNOVER_FOR_MOVERS]
        pick = liquid if len(liquid) >= 3 else g_sorted
        sectors.append(
            {
                "name": name,
                "count": int(len(g)),
                "advance": int((g["change"] > 0).sum()),
                "decline": int((g["change"] < 0).sum()),
                "avg_pct": round(float(g["pct"].mean()), 2),
                "median_pct": round(float(g["pct"].median()), 2),
                "turnover": float(g["turnover"].sum()),
                "turnover_share": round(float(g["turnover"].sum()) / total_turnover * 100, 2),
                "index_pct": idx.get(TWSE_SECTOR_INDEX.get(name, "")),
                "leaders": [{"code": r.code, "name": r.name, "pct": _py(r.pct)} for r in pick.head(3).itertuples()],
                "laggards": [{"code": r.code, "name": r.name, "pct": _py(r.pct)} for r in pick.tail(3).iloc[::-1].itertuples()],
            }
        )
    sectors.sort(key=lambda s: s["avg_pct"], reverse=True)

    # distribution of daily returns
    dist = []
    for lo, hi in BUCKETS:
        if lo == hi == 0:
            n = int((common["pct"] == 0).sum())
            label = "0"
        elif lo < 0:
            n = int(((common["pct"] > lo) & (common["pct"] <= hi)).sum()) if hi != 0 else int(((common["pct"] > lo) & (common["pct"] < 0)).sum())
            label = f"{lo}~{hi}%" if lo > -100 else f"<{hi}%"
        else:
            n = int(((common["pct"] > lo) & (common["pct"] <= hi)).sum()) if hi != 100 else int((common["pct"] > lo).sum())
            label = f"{lo}~{hi}%" if hi < 100 else f">{lo}%"
        dist.append({"label": label, "count": n})

    liquid = common[common["turnover"] >= MIN_TURNOVER_FOR_MOVERS].sort_values("pct", ascending=False)
    movers = lambda frame: [  # noqa: E731
        {"code": r.code, "name": r.name, "market": r.market, "sector": r.sector, "pct": _py(r.pct), "close": _py(r.close), "turnover": _py(r.turnover)}
        for r in frame.itertuples()
    ]
    by_turnover = df.sort_values("turnover", ascending=False)
    top5_share = round(float(common.sort_values("turnover", ascending=False).head(5)["turnover"].sum()) / total_turnover * 100, 1)

    return {
        "date": d.isoformat(),
        "available": True,
        "markets": markets,
        "index_pct": main_pct,
        "divergence": {
            # positive = index outperforming the typical stock (large caps carrying the market)
            "index_minus_median": round(main_pct - all_mk["median_pct"], 2) if main_pct is not None and all_mk["median_pct"] is not None else None,
            "top5_turnover_share": top5_share,
        },
        "sectors": sectors,
        "distribution": dist,
        "top_gainers": movers(liquid.head(15)),
        "top_losers": movers(liquid.tail(15).iloc[::-1]),
        "turnover_leaders": [
            {**m, "share": round(m["turnover"] / total_turnover * 100, 1)} for m in movers(by_turnover.head(10))
        ],
    }


# ---------------------------------------------------------------------- history
def breadth_history(db: Session, days: int = 30) -> list[dict]:
    dates = available_dates(db, days)
    if not dates:
        return []
    rows = db.execute(select(MarketStat).where(MarketStat.date.in_(dates))).scalars()
    by_date: dict[date, dict] = {}
    for r in rows:
        e = by_date.setdefault(r.date, {"date": r.date.isoformat(), "advance": 0, "decline": 0, "flat": 0, "limit_up": 0, "limit_down": 0, "turnover": 0.0})
        for k in ("advance", "decline", "flat", "limit_up", "limit_down"):
            e[k] += getattr(r, k) or 0
        e["turnover"] += r.turnover or 0
    idx = {
        r.date: r.change_pct
        for r in db.execute(select(IndexDaily).where(IndexDaily.name == MAIN_INDEX, IndexDaily.date.in_(dates))).scalars()
    }
    out = []
    for d in sorted(by_date):
        e = by_date[d]
        n = e["advance"] + e["decline"] + e["flat"]
        e["adv_ratio"] = round(e["advance"] / n * 100, 1) if n else None
        e["index_pct"] = idx.get(d)
        out.append(e)
    return out


def sector_history(db: Session, days: int = 10) -> dict:
    dates = sorted(available_dates(db, days))
    df = _load_days(db, dates)
    if df.empty:
        return {"dates": [], "sectors": []}
    common = df[df["common"] & df["pct"].notna()]
    pivot = common.pivot_table(index="sector", columns="date", values="pct", aggfunc="mean").reindex(columns=dates)
    idx_rows = db.execute(select(IndexDaily).where(IndexDaily.date.in_(dates))).scalars()
    idx: dict[str, dict[date, float | None]] = {}
    for r in idx_rows:
        idx.setdefault(r.name, {})[r.date] = r.change_pct
    sectors = []
    for name, row in pivot.iterrows():
        series = [None if pd.isna(v) else round(float(v), 2) for v in row.tolist()]
        valid = [v for v in series if v is not None]
        cum = round(float((pd.Series(valid) / 100 + 1).prod() - 1) * 100, 2) if valid else None
        iname = TWSE_SECTOR_INDEX.get(name)
        sectors.append(
            {
                "name": name,
                "avg": series,
                "cum_pct": cum,
                "index": [idx.get(iname, {}).get(d) for d in dates] if iname else None,
            }
        )
    sectors.sort(key=lambda s: (s["cum_pct"] is None, -(s["cum_pct"] or 0)))
    main = [idx.get(MAIN_INDEX, {}).get(d) for d in dates]
    return {"dates": [d.isoformat() for d in dates], "sectors": sectors, "index": main}


def sector_stocks(db: Session, name: str, d: date | None = None) -> list[dict]:
    d = d or latest_date(db)
    if d is None:
        return []
    df = _load_days(db, [d])
    if df.empty:
        return []
    g = df[df["sector"] == name].sort_values("pct", ascending=False)
    return [
        {
            "code": r.code, "name": r.name, "market": r.market,
            "close": _py(r.close), "change": _py(r.change), "pct": _py(r.pct),
            "turnover": _py(r.turnover), "volume": _py(r.volume),
        }
        for r in g.itertuples()
    ]


def _py(v):
    """numpy scalar / NaN -> plain Python value or None (FastAPI cannot encode numpy.int64)."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v.item() if hasattr(v, "item") else v
