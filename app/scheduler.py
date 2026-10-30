"""APScheduler jobs: realtime polling during market hours + after-close data jobs."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import settings
from .db import session_scope
from .models import JobRun
from .services import alerts, breadth, screener
from .services import market_data as md
from .utils import is_trading_hours, now_tw

log = logging.getLogger(__name__)

scheduler = BackgroundScheduler(
    timezone=settings.timezone,
    job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 600},
)

realtime_status: dict = {"last_run": None, "last_success": None, "quotes": 0, "alerts": 0, "error": None, "skipped": None}


# ---------------------------------------------------------------------- job bodies (each takes a Session)
def job_daily_prices(db) -> dict:
    result = md.update_daily_prices(db)
    result["market"] = breadth.update_market_day(db)
    result["fill"] = md.fill_missing_latest(db)
    result["alerts"] = len(alerts.evaluate_daily(db))
    return result


def job_market_daily(db) -> dict:
    return breadth.update_market_day(db)


def job_market_backfill(db) -> dict:
    return breadth.backfill_market(db, days=20)


def job_institutional(db) -> dict:
    result = md.update_institutional(db)
    result["alerts"] = len(alerts.evaluate_daily(db))
    result["screener"] = _run_screens(db)
    return result


def _run_screens(db) -> dict:
    """Run every preset on the latest market day; notify with the balanced top 10."""
    out = {}
    for key in screener.PRESETS:
        try:
            r = screener.run_screener(db, preset=key, notify=(key == "balanced"))
            out[key] = {"universe": r["universe"], "top": len(r["results"])}
        except Exception as exc:  # noqa: BLE001
            log.warning("screener %s failed: %s", key, exc)
            out[key] = {"error": str(exc)}
    return out


def job_screener(db) -> dict:
    return _run_screens(db)


def job_margin(db) -> dict:
    result = md.update_margin(db)
    result["alerts"] = len(alerts.evaluate_daily(db))
    return result


def job_flows_backfill(db) -> dict:
    return md.backfill_flows(db, days=20)


def job_stock_list(db) -> dict:
    return {"rows": md.refresh_stock_list(db)}


def job_alerts_daily(db) -> dict:
    events = alerts.evaluate_daily(db)
    return {"alerts": len(events), "messages": [e.message for e in events]}


def job_full_daily(db) -> dict:
    """Prices + institutional + margin + alerts in one go (manual catch-up)."""
    out = {
        "prices": md.update_daily_prices(db),
        "market": breadth.update_market_day(db),
        "fill": md.fill_missing_latest(db),
        "institutional": md.update_institutional(db),
        "margin": md.update_margin(db),
    }
    out["alerts"] = len(alerts.evaluate_daily(db))
    out["screener"] = _run_screens(db)
    return out


def job_realtime_once(db) -> dict:
    quotes = md.update_realtime(db)
    events = alerts.evaluate_intraday(db, quotes)
    return {"quotes": len(quotes), "alerts": len(events)}


JOBS: dict[str, Callable] = {
    "daily_prices": job_daily_prices,
    "institutional": job_institutional,
    "margin": job_margin,
    "flows_backfill": job_flows_backfill,
    "market_daily": job_market_daily,
    "market_backfill": job_market_backfill,
    "screener": job_screener,
    "stock_list": job_stock_list,
    "alerts_daily": job_alerts_daily,
    "full_daily": job_full_daily,
    "realtime": job_realtime_once,
}


# ---------------------------------------------------------------------- runner
def run_job(name: str, fn: Callable | None = None, *args) -> dict:
    """Run a job body in its own session and record the outcome in job_runs."""
    fn = fn or JOBS[name]
    started = datetime.now()
    ok, detail = True, ""
    try:
        with session_scope() as db:
            result = fn(db, *args)
        detail = json.dumps(result, default=str, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        ok = False
        detail = f"{type(exc).__name__}: {exc}"
        result = {"error": detail}
        log.exception("job %s failed", name)
    with session_scope() as db:
        db.add(JobRun(job=name, started_at=started, finished_at=datetime.now(), ok=ok, detail=detail[:4000]))
    log.info("job %s finished ok=%s %s", name, ok, detail[:200])
    return result


def _realtime_tick() -> None:
    now = now_tw()
    realtime_status["last_run"] = now.isoformat(timespec="seconds")
    if not is_trading_hours(now):
        realtime_status["skipped"] = "outside trading hours"
        return
    realtime_status["skipped"] = None
    try:
        with session_scope() as db:
            quotes = md.update_realtime(db)
            events = alerts.evaluate_intraday(db, quotes)
        realtime_status.update(
            {"last_success": now.isoformat(timespec="seconds"), "quotes": len(quotes), "alerts": len(events), "error": None}
        )
    except Exception as exc:  # noqa: BLE001
        realtime_status["error"] = str(exc)
        log.warning("realtime tick failed: %s", exc)


# ---------------------------------------------------------------------- schedule
def _cron(**kw) -> CronTrigger:
    return CronTrigger(day_of_week="mon-fri", timezone=settings.timezone, **kw)


def start() -> None:
    if scheduler.running:
        return
    scheduler.add_job(
        _realtime_tick,
        IntervalTrigger(seconds=settings.realtime_interval_seconds),
        id="realtime",
        name="realtime quotes (trading hours)",
    )
    # TWSE publishes STOCK_DAY_ALL ~14:30-15:00; run twice in case of delays (upsert is idempotent)
    scheduler.add_job(run_job, _cron(hour=15, minute=5), args=["daily_prices"], id="daily_prices_1", name="daily prices 15:05")
    scheduler.add_job(run_job, _cron(hour=17, minute=5), args=["daily_prices"], id="daily_prices_2", name="daily prices 17:05")
    # T86 / TPEx institutional appear ~16:00-16:30
    scheduler.add_job(run_job, _cron(hour=16, minute=40), args=["institutional"], id="institutional_1", name="institutional 16:40")
    scheduler.add_job(run_job, _cron(hour=18, minute=40), args=["institutional"], id="institutional_2", name="institutional 18:40")
    # margin balances are published ~21:00
    scheduler.add_job(run_job, _cron(hour=21, minute=35), args=["margin"], id="margin_1", name="margin 21:35")
    scheduler.add_job(run_job, _cron(hour=22, minute=35), args=["margin"], id="margin_2", name="margin 22:35")
    scheduler.add_job(
        run_job,
        CronTrigger(day_of_week="sun", hour=6, minute=0, timezone=settings.timezone),
        args=["stock_list"],
        id="stock_list",
        name="refresh stock master (Sun 06:00)",
    )
    scheduler.start()
    log.info("scheduler started (%d jobs)", len(scheduler.get_jobs()))


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


def list_jobs() -> list[dict]:
    if not scheduler.running:
        return []
    return [
        {
            "id": j.id,
            "name": j.name,
            "next_run": j.next_run_time.isoformat(timespec="seconds") if j.next_run_time else None,
        }
        for j in scheduler.get_jobs()
    ]
