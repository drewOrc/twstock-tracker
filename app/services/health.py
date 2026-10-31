"""Data health: is every table as fresh as it should be right now?

Expectations follow the publishing schedule (Asia/Taipei): daily prices / whole market after 15:00,
institutional flows after 17:00, margin after 22:00, screener after 17:00. Before the cut-off the
previous business day counts as fresh. Holidays are not modelled, so a holiday shows as "warn"
(one business day behind) rather than "bad".
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import BASE_DIR, settings
from ..models import (
    AlertEvent,
    AlertRule,
    DailyPrice,
    IndexDaily,
    InstitutionalFlow,
    JobRun,
    MarginBalance,
    MarketStat,
    RealtimeQuote,
    ScreenerResult,
    Stock,
    WatchlistItem,
)
from ..utils import is_trading_hours, now_tw
from .market_data import last_business_day

# (table key, label, model, date column, publish hour on a trading day)
DATED_TABLES = [
    ("daily_prices", "日線（追蹤池 + 全市場）", DailyPrice, DailyPrice.date, 15),
    ("market_stats", "盤面分化（家數）", MarketStat, MarketStat.date, 15),
    ("index_daily", "加權 / 類股指數", IndexDaily, IndexDaily.date, 15),
    ("institutional_flows", "三大法人", InstitutionalFlow, InstitutionalFlow.date, 17),
    ("margin_balances", "融資融券", MarginBalance, MarginBalance.date, 22),
    ("screener_results", "選股掃描", ScreenerResult, ScreenerResult.date, 17),
]


def expected_date(now: datetime, publish_hour: int) -> date:
    """The newest trading date a table should contain at `now`."""
    today = now.date()
    d = last_business_day(today)
    if d == today and now.hour < publish_hour:
        d = last_business_day(today - timedelta(days=1))
    return d


def business_days_between(a: date, b: date) -> int:
    """Number of weekdays in (a, b]; 0 when a >= b."""
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def freshness(latest: date | None, expected: date) -> str:
    if latest is None:
        return "missing"
    behind = business_days_between(latest, expected)
    return "ok" if behind == 0 else "warn" if behind == 1 else "bad"


def data_health(db: Session, now: datetime | None = None) -> dict:
    now = now or now_tw().replace(tzinfo=None)
    tables = []
    for key, label, model, col, hour in DATED_TABLES:
        latest, rows = db.execute(select(func.max(col), func.count()).select_from(model)).one()
        exp = expected_date(now, hour)
        tables.append(
            {
                "table": key,
                "label": label,
                "rows": rows,
                "latest": latest.isoformat() if latest else None,
                "expected": exp.isoformat(),
                "status": freshness(latest, exp),
                "publish_hour": hour,
            }
        )

    # realtime: only meaningful during trading hours
    rt_latest = db.execute(select(func.max(RealtimeQuote.updated_at))).scalar()
    rt_rows = db.execute(select(func.count()).select_from(RealtimeQuote)).scalar()
    trading = is_trading_hours(now_tw())
    if trading:
        rt_status = "missing" if rt_latest is None else ("ok" if now - rt_latest < timedelta(seconds=90) else "bad")
    else:
        rt_status = "idle"
    tables.append(
        {
            "table": "realtime_quotes",
            "label": "即時報價",
            "rows": rt_rows,
            "latest": rt_latest.isoformat(timespec="seconds") if rt_latest else None,
            "expected": f"盤中每 {settings.realtime_interval_seconds}s" if trading else "非交易時段",
            "status": rt_status,
            "publish_hour": None,
        }
    )

    # stock master
    st_latest = db.execute(select(func.max(Stock.updated_at))).scalar()
    st_rows = db.execute(select(func.count()).select_from(Stock)).scalar()
    tables.append(
        {
            "table": "stocks",
            "label": "公司清單",
            "rows": st_rows,
            "latest": st_latest.isoformat(timespec="seconds") if st_latest else None,
            "expected": "8 天內",
            "status": "missing" if st_latest is None else ("ok" if now - st_latest < timedelta(days=8) else "warn"),
            "publish_hour": None,
        }
    )

    # jobs in the last 24 hours
    since = now - timedelta(hours=24)
    runs = db.execute(select(JobRun).where(JobRun.started_at >= since).order_by(JobRun.started_at.desc())).scalars().all()
    failed = [{"job": r.job, "at": r.started_at.isoformat(timespec="seconds"), "detail": (r.detail or "")[:200]} for r in runs if r.ok is False]
    last_ok: dict[str, str] = {}
    for r in db.execute(select(JobRun).where(JobRun.ok.is_(True)).order_by(JobRun.started_at.desc()).limit(300)).scalars():
        last_ok.setdefault(r.job, r.started_at.isoformat(timespec="seconds"))

    # storage
    db_path = BASE_DIR / "data" / "twstock.db"
    size_mb = round(os.path.getsize(db_path) / 1e6, 1) if db_path.exists() else None
    wal = db_path.with_name(db_path.name + "-wal")
    wal_mb = round(os.path.getsize(wal) / 1e6, 1) if wal.exists() else 0.0
    log_path = BASE_DIR / "data" / "logs" / "engine.log"

    counts = {
        "watched_codes": db.execute(select(func.count(func.distinct(WatchlistItem.code)))).scalar(),
        "alert_rules": db.execute(select(func.count()).select_from(AlertRule).where(AlertRule.enabled.is_(True))).scalar(),
        "alert_events_24h": db.execute(select(func.count()).select_from(AlertEvent).where(AlertEvent.triggered_at >= since)).scalar(),
    }
    statuses = [t["status"] for t in tables]
    overall = "bad" if "bad" in statuses or failed else "warn" if "warn" in statuses or "missing" in statuses else "ok"
    return {
        "checked_at": now.isoformat(timespec="seconds"),
        "overall": overall,
        "tables": tables,
        "jobs": {"runs_24h": len(runs), "failed_24h": failed, "last_ok": last_ok},
        "counts": counts,
        "storage": {"db_mb": size_mb, "wal_mb": wal_mb, "log": str(log_path) if log_path.exists() else None},
    }
