"""每日選股掃描器 - whole-market multi-factor screener.

Every factor is computed for every liquid common stock from data already in the database
(daily prices for the whole market, institutional flows, margin balances, breadth stats),
converted to a percentile rank across the universe (0-100) and combined with preset weights.
Results are persisted so later turns can measure how each tag / score bucket actually performed.
"""
from __future__ import annotations

import logging
import math
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import DailyPrice, IndexDaily, InstitutionalFlow, MarginBalance, MarketStat, ScreenerResult, Stock
from . import breadth
from .industries import MAIN_INDEX, is_common_stock, sector_name
from .notifier import notifier

log = logging.getLogger(__name__)

LOOKBACK_DAYS = 70  # trading days of price history pulled for the scan
MIN_HISTORY = 21  # a stock needs at least this many bars to be scored

PRESETS: dict[str, dict] = {
    "balanced": {
        "label": "均衡（動能 + 籌碼 + 量價）",
        "weights": {"rs20": 20, "rs5": 10, "breakout": 15, "vol_ratio": 10, "vol_trend": 5, "trend": 10, "foreign5": 15, "trust5": 5, "contrarian": 5, "sector": 5},
    },
    "momentum": {
        "label": "動能突破",
        "weights": {"rs20": 25, "rs5": 15, "breakout": 25, "vol_ratio": 15, "vol_trend": 5, "trend": 15},
    },
    "chips": {
        "label": "法人籌碼",
        "weights": {"foreign5": 35, "trust5": 20, "foreign_streak": 15, "margin": 10, "rs20": 10, "trend": 10},
    },
    "contrarian": {
        "label": "分化盤逆勢強勢",
        "weights": {"contrarian": 30, "rs5": 20, "rs20": 15, "sector": 10, "vol_ratio": 10, "foreign5": 15},
    },
}

FACTOR_LABELS = {
    "rs20": "20 日相對強弱 (vs 加權, %)",
    "rs5": "5 日相對強弱 (%)",
    "ret20": "20 日漲幅 (%)",
    "ret5": "5 日漲幅 (%)",
    "breakout": "收盤 / 前 20 日高點",
    "breakout60": "收盤 / 前 60 日高點",
    "vol_ratio": "今日量 / 20 日均量",
    "vol_trend": "5 日均量 / 20 日均量",
    "trend": "均線排列分 (0-4)",
    "foreign5": "外資 5 日淨買 / 5 日成交量",
    "trust5": "投信 5 日淨買 / 5 日成交量",
    "foreign_streak": "外資連續買超天數",
    "margin": "融資餘額 5 日變化 (%, 負向計分)",
    "contrarian": "近 20 日弱勢盤逆勢收紅次數",
    "sector": "所屬類股 5 日累計 (%)",
}


# ---------------------------------------------------------------------- factor computation
def _pivot(df: pd.DataFrame, col: str) -> pd.DataFrame:
    return df.pivot_table(index="date", columns="code", values=col, aggfunc="first").sort_index()


def compute_factors(db: Session, d: date | None = None, min_turnover: float = 50_000_000) -> tuple[pd.DataFrame, date | None]:
    """Return (factor table indexed by code, scan date). Empty frame when there is no market data."""
    all_dates = sorted(breadth.available_dates(db, 400))
    if d:
        all_dates = [x for x in all_dates if x <= d]
    if not all_dates:
        return pd.DataFrame(), None
    dates = all_dates[-LOOKBACK_DAYS:]
    d = dates[-1]

    stmt = select(DailyPrice.code, DailyPrice.date, DailyPrice.close, DailyPrice.high, DailyPrice.volume, DailyPrice.turnover).where(
        DailyPrice.date.in_(dates)
    )
    px_df = pd.DataFrame(db.execute(stmt).all(), columns=["code", "date", "close", "high", "volume", "turnover"])
    if px_df.empty:
        return pd.DataFrame(), d
    px_df = px_df[px_df["code"].map(is_common_stock)]
    close = _pivot(px_df, "close")
    high = _pivot(px_df, "high")
    vol = _pivot(px_df, "volume").astype(float)
    turn = _pivot(px_df, "turnover").astype(float)
    n = len(close)

    last = close.iloc[-1]
    history = close.notna().sum()
    universe = last.index[(history >= MIN_HISTORY) & (turn.iloc[-1] >= min_turnover) & last.notna()]
    if len(universe) == 0:
        return pd.DataFrame(), d
    close, high, vol, turn = close[universe], high[universe], vol[universe], turn[universe]
    last = close.iloc[-1]

    # index returns for relative strength
    idx = pd.Series(
        {r.date: r.close for r in db.execute(select(IndexDaily).where(IndexDaily.name == MAIN_INDEX, IndexDaily.date.in_(dates))).scalars()}
    ).sort_index()

    def ret(frame_or_series, k: int):
        if len(frame_or_series) <= k:
            return None
        return (frame_or_series.iloc[-1] / frame_or_series.iloc[-1 - k] - 1) * 100

    ret5, ret20 = ret(close, 5), ret(close, 20)
    idx5, idx20 = ret(idx, 5), ret(idx, 20)
    f = pd.DataFrame(index=universe)
    f["close"] = last
    f["pct"] = ret(close, 1)
    f["turnover"] = turn.iloc[-1]
    f["volume"] = vol.iloc[-1]
    f["ret5"], f["ret20"] = ret5, ret20
    f["rs5"] = (ret5 - idx5) if ret5 is not None and idx5 is not None else ret5
    f["rs20"] = (ret20 - idx20) if ret20 is not None and idx20 is not None else ret20

    prior_hi20 = high.iloc[-21:-1].max()
    f["breakout"] = last / prior_hi20
    if n >= 41:
        prior_hi60 = high.iloc[-61:-1].max()
        f["breakout60"] = last / prior_hi60
    else:
        f["breakout60"] = np.nan

    avg20 = vol.iloc[-21:-1].mean()
    f["vol_ratio"] = vol.iloc[-1] / avg20.replace(0, np.nan)
    f["vol_trend"] = vol.iloc[-5:].mean() / avg20.replace(0, np.nan)

    ma5, ma20 = close.iloc[-5:].mean(), close.iloc[-20:].mean()
    ma60 = close.iloc[-60:].mean() if n >= 60 else None
    ma20_prev = close.iloc[-25:-5].mean() if n >= 25 else ma20
    trend = (last > ma5).astype(int) + (ma5 > ma20).astype(int) + (ma20 > ma20_prev).astype(int)
    trend = trend + ((ma20 > ma60).astype(int) if ma60 is not None else (ma20 > ma20_prev).astype(int))
    f["trend"] = trend

    # chips: whole-market institutional flows (shares) over the last 10 trading days
    flow_dates = dates[-10:]
    inst = pd.DataFrame(
        db.execute(
            select(InstitutionalFlow.code, InstitutionalFlow.date, InstitutionalFlow.foreign_net, InstitutionalFlow.trust_net).where(
                InstitutionalFlow.date.in_(flow_dates), InstitutionalFlow.code.in_(list(universe))
            )
        ).all(),
        columns=["code", "date", "foreign_net", "trust_net"],
    )
    vol5 = vol.iloc[-5:].sum().replace(0, np.nan)
    if not inst.empty:
        fn = _pivot(inst, "foreign_net").reindex(columns=universe)
        tn = _pivot(inst, "trust_net").reindex(columns=universe)
        f["foreign5"] = fn.iloc[-5:].sum(min_count=1) / vol5
        f["trust5"] = tn.iloc[-5:].sum(min_count=1) / vol5
        streak = pd.Series(0, index=universe, dtype=int)
        alive = pd.Series(True, index=universe)
        for i in range(len(fn) - 1, -1, -1):
            pos = (fn.iloc[i] > 0).fillna(False)
            alive &= pos
            streak += alive.astype(int)
        f["foreign_streak"] = streak
    else:
        f["foreign5"] = f["trust5"] = f["foreign_streak"] = np.nan

    mg = pd.DataFrame(
        db.execute(
            select(MarginBalance.code, MarginBalance.date, MarginBalance.margin_balance).where(
                MarginBalance.date.in_(dates[-6:]), MarginBalance.code.in_(list(universe))
            )
        ).all(),
        columns=["code", "date", "margin_balance"],
    )
    if not mg.empty and len(mg["date"].unique()) >= 2:
        mb = _pivot(mg, "margin_balance").reindex(columns=universe).astype(float)
        first, lastb = mb.iloc[0], mb.iloc[-1]
        chg = (lastb - first) / first.replace(0, np.nan) * 100
        f["margin_change"] = chg
        f["margin"] = -chg  # shrinking margin balance scores higher
    else:
        f["margin_change"] = f["margin"] = np.nan

    # contrarian: closed up on days when fewer than 40% of stocks advanced
    stats = pd.DataFrame(
        db.execute(select(MarketStat.date, MarketStat.advance, MarketStat.decline, MarketStat.flat).where(MarketStat.date.in_(dates[-21:]))).all(),
        columns=["date", "advance", "decline", "flat"],
    )
    if not stats.empty:
        agg = stats.groupby("date").sum()
        ratio = agg["advance"] / (agg["advance"] + agg["decline"] + agg["flat"]).replace(0, np.nan) * 100
        weak_days = [x for x in ratio.index if ratio[x] < 40]
        daily = close.pct_change(fill_method=None)
        f["contrarian"] = (daily.loc[daily.index.isin(weak_days)] > 0).sum() if weak_days else 0
        f["weak_days"] = len(weak_days)
    else:
        f["contrarian"], f["weak_days"] = np.nan, 0

    # sector strength (5-day cumulative average return of the stock's sector)
    sh = breadth.sector_history(db, 5)
    sec_cum = {s["name"]: s["cum_pct"] for s in sh.get("sectors", [])}
    meta = {s.code: s for s in db.execute(select(Stock).where(Stock.code.in_(list(universe)))).scalars()}
    f["name"] = [meta[c].name if c in meta else None for c in f.index]
    f["market"] = [meta[c].market if c in meta else None for c in f.index]
    f["sector_name"] = [sector_name(c, meta[c].industry if c in meta else None) for c in f.index]
    f["sector"] = f["sector_name"].map(sec_cum)
    f["days"] = history[universe]
    return f, d


# ---------------------------------------------------------------------- scoring
def score_factors(f: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    total = sum(weights.values()) or 1
    score = pd.Series(0.0, index=f.index)
    for name, w in weights.items():
        if name not in f.columns:
            continue
        col = pd.to_numeric(f[name], errors="coerce")
        rank = col.rank(pct=True) * 100
        score += rank.fillna(50) * (w / total)
    return score.round(1)


def make_tags(row: pd.Series, strong_sectors: set[str]) -> list[str]:
    tags = []
    g = lambda k: row.get(k)  # noqa: E731
    v = lambda k: (None if g(k) is None or (isinstance(g(k), float) and math.isnan(g(k))) else g(k))  # noqa: E731
    if v("breakout60") is not None and v("breakout60") >= 1:
        tags.append("創 60 日新高")
    elif v("breakout") is not None and v("breakout") >= 1:
        tags.append("創 20 日新高")
    if v("vol_ratio") is not None and v("vol_ratio") >= 2:
        tags.append(f"量能 {v('vol_ratio'):.1f}x")
    if v("trend") is not None and v("trend") >= 4:
        tags.append("多頭排列")
    if v("rs20") is not None and v("rs20") >= 10:
        tags.append(f"20 日 RS +{v('rs20'):.0f}%")
    if v("foreign_streak") is not None and v("foreign_streak") >= 3:
        tags.append(f"外資連買 {int(v('foreign_streak'))} 日")
    if v("foreign5") is not None and v("foreign5") >= 0.10:
        tags.append("外資 5 日大買")
    if v("trust5") is not None and v("trust5") >= 0.03:
        tags.append("投信買超")
    if v("margin_change") is not None and v("margin_change") <= -5 and (v("ret5") or 0) > 0:
        tags.append("融資減價漲")
    if v("contrarian") is not None and v("contrarian") >= 3:
        tags.append(f"逆勢收紅 {int(v('contrarian'))} 次")
    if row.get("sector_name") in strong_sectors:
        tags.append("強勢類股")
    return tags


def _clean(v):
    if v is None:
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return round(v, 4) if isinstance(v, float) else v


# ---------------------------------------------------------------------- run / persist
def run_screener(
    db: Session,
    d: date | None = None,
    preset: str = "balanced",
    min_turnover: float = 50_000_000,
    top: int = 30,
    notify: bool = False,
    weights: dict[str, float] | None = None,
) -> dict:
    if preset not in PRESETS and not weights:
        raise ValueError(f"unknown preset: {preset}")
    weights = weights or PRESETS[preset]["weights"]
    f, d = compute_factors(db, d, min_turnover)
    if f.empty:
        return {"date": d.isoformat() if d else None, "preset": preset, "universe": 0, "results": []}
    f["score"] = score_factors(f, weights)
    f = f.sort_values("score", ascending=False)
    sec_sorted = sorted(((s, c) for s, c in f.groupby("sector_name")["sector"].first().items() if c is not None), key=lambda x: -x[1])
    strong = {s for s, _ in sec_sorted[:5]}

    results = []
    for rank, (code, row) in enumerate(f.head(top).iterrows(), start=1):
        factors = {k: _clean(row.get(k)) for k in FACTOR_LABELS if k in row.index}
        factors["margin_change"] = _clean(row.get("margin_change"))
        results.append(
            {
                "date": d,
                "preset": preset,
                "rank": rank,
                "code": code,
                "score": float(row["score"]),
                "factors": {
                    **factors,
                    "close": _clean(row["close"]),
                    "pct": _clean(row["pct"]),
                    "turnover": _clean(row["turnover"]),
                    "sector_name": row["sector_name"],
                    "name": row["name"],
                    "market": row["market"],
                },
                "tags": make_tags(row, strong),
            }
        )
    db.execute(delete(ScreenerResult).where(ScreenerResult.date == d, ScreenerResult.preset == preset))
    db.add_all(ScreenerResult(**r) for r in results)
    db.commit()
    out = {"date": d.isoformat(), "preset": preset, "label": PRESETS.get(preset, {}).get("label", preset), "universe": int(len(f)), "results": [_serialise(r) for r in results]}
    if notify and results:
        lines = [f"{r['rank']}. {r['code']} {r['factors']['name'] or ''} {r['score']:.0f}分 {' / '.join(r['tags'])}".rstrip() for r in results[:10]]
        delivery = notifier.send(f"選股掃描 {d} · {out['label']}", "\n".join(lines))
        out["delivery"] = delivery
    log.info("screener %s %s: universe %d, top %d", d, preset, len(f), len(results))
    return out


def _serialise(r: dict) -> dict:
    return {**r, "date": r["date"].isoformat() if isinstance(r["date"], date) else r["date"]}


def load_results(db: Session, d: date | None = None, preset: str = "balanced", limit: int = 30) -> dict:
    if d is None:
        d = db.execute(select(ScreenerResult.date).where(ScreenerResult.preset == preset).order_by(ScreenerResult.date.desc()).limit(1)).scalar()
    if d is None:
        return {"date": None, "preset": preset, "results": []}
    rows = db.execute(
        select(ScreenerResult).where(ScreenerResult.date == d, ScreenerResult.preset == preset).order_by(ScreenerResult.rank).limit(limit)
    ).scalars()
    return {
        "date": d.isoformat(),
        "preset": preset,
        "label": PRESETS.get(preset, {}).get("label", preset),
        "results": [
            {"date": r.date.isoformat(), "preset": r.preset, "rank": r.rank, "code": r.code, "score": r.score, "factors": r.factors, "tags": r.tags}
            for r in rows
        ],
    }


def result_dates(db: Session, preset: str | None = None, limit: int = 60) -> list[date]:
    stmt = select(ScreenerResult.date).distinct().order_by(ScreenerResult.date.desc()).limit(limit)
    if preset:
        stmt = stmt.where(ScreenerResult.preset == preset)
    return list(db.execute(stmt).scalars())
