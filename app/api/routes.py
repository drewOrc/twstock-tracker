from __future__ import annotations

import math
from datetime import date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import scheduler as sched
from ..config import settings
from ..db import get_db
from ..models import AlertRule, JobRun, Stock, WatchlistItem
from ..schemas import (
    AlertRuleCreate,
    AlertRuleUpdate,
    NotifyTest,
    WatchlistCreate,
    WatchlistDef,
    WatchlistPatch,
    WatchlistUpdate,
)
from ..services import alerts, breadth, screener
from ..services import market_data as md
from ..services import watchlists as wls
from ..services.indicators import compute_all
from ..services.notifier import notifier
from ..utils import is_trading_hours, now_tw

router = APIRouter(prefix="/api")


def to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _clean(v):
    """numpy scalars -> Python, NaN/inf -> None (JSON safe)."""
    if v is None:
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


# ---------------------------------------------------------------------- health / meta
@router.get("/health")
async def health():
    from . import crm_proxy

    return {
        "status": "ok",
        "app": settings.app_name,
        "time": now_tw().isoformat(timespec="seconds"),
        "trading_hours": is_trading_hours(),
        "scheduler": {"enabled": settings.scheduler_enabled, "running": sched.scheduler.running},
        "channels": notifier.channels(),
        "crm": await crm_proxy.crm_health(),
    }


@router.get("/health/data")
def health_data(db: Session = Depends(get_db)):
    """Per-table freshness against the publishing schedule, failed jobs in 24h, storage."""
    from ..services.health import data_health

    return data_health(db)


# ---------------------------------------------------------------------- stocks
@router.get("/stocks/search")
def search_stocks(q: str = Query(..., min_length=1), limit: int = 20, db: Session = Depends(get_db)):
    return [to_dict(s) for s in md.search_stocks(db, q, limit)]


@router.get("/stocks/{code}/daily")
def stock_daily(code: str, limit: int = 250, db: Session = Depends(get_db)):
    df = md.load_daily_df(db, code.upper(), limit)
    return [{k: _clean(v) for k, v in row.items()} for row in df.to_dict(orient="records")]


@router.get("/stocks/{code}/indicators")
def stock_indicators(code: str, limit: int = 250, db: Session = Depends(get_db)):
    df = md.load_daily_df(db, code.upper(), limit)
    if df.empty:
        return {"code": code.upper(), "rows": 0, "series": {}}
    ind = compute_all(df)
    series = {col: [_clean(v) for v in ind[col].tolist()] for col in ind.columns if col != "date"}
    series["date"] = [d.isoformat() for d in ind["date"]]
    last = {col: _clean(ind[col].iloc[-1]) for col in ind.columns if col != "date"}
    last["date"] = ind["date"].iloc[-1].isoformat()
    return {"code": code.upper(), "rows": len(ind), "series": series, "latest": last}


@router.get("/stocks/{code}/summary")
def stock_summary(code: str, news: bool = True, db: Session = Depends(get_db)):
    """基本介紹 + 最近狀況: profile, price / relative strength / range / MA, chips, screener & alerts
    context, watchlist membership, latest headlines (news=false skips the RSS call)."""
    from ..services.stock_summary import stock_summary as build

    try:
        return build(db, code, with_news=news)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/stocks/{code}/news")
def stock_news(code: str, limit: int = 10, db: Session = Depends(get_db)):
    from ..services.stock_summary import fetch_news

    stock = db.get(Stock, code.upper())
    name = stock.name if stock and stock.name else code.upper()
    items, err = fetch_news(name, limit)
    return {"query": name, "items": items, "error": err}


@router.get("/stocks/{code}/institutional")
def stock_institutional(code: str, limit: int = 60, days: int | None = None, db: Session = Depends(get_db)):
    """Newest first. `days` is an alias for `limit` (one row per trading day)."""
    return [to_dict(r) for r in md.load_institutional(db, code.upper(), days or limit)]


@router.get("/stocks/{code}/margin")
def stock_margin(code: str, limit: int = 60, days: int | None = None, db: Session = Depends(get_db)):
    return [to_dict(r) for r in md.load_margin(db, code.upper(), days or limit)]


# ---------------------------------------------------------------------- watchlists (多追蹤池)
@router.get("/watchlists")
def get_watchlists(db: Session = Depends(get_db)):
    return wls.list_watchlists(db)


@router.post("/watchlists", status_code=201)
def create_watchlist(body: WatchlistDef, db: Session = Depends(get_db)):
    try:
        return to_dict(wls.create_watchlist(db, body.name, body.color))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/watchlists/{list_id}")
def patch_watchlist(list_id: int, body: WatchlistPatch, db: Session = Depends(get_db)):
    try:
        return to_dict(wls.update_watchlist(db, list_id, body.name, body.color, body.sort_order))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/watchlists/{list_id}")
def delete_watchlist(list_id: int, db: Session = Depends(get_db)):
    try:
        return {"deleted": list_id, "unsubscribed": wls.delete_watchlist(db, list_id)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/watchlists/sync")
def sync_watchlists(bg: BackgroundTasks):
    """Rebuild the system lists (CRM 持有 / 觀察、掃描候選、今日警示) in the background."""
    bg.add_task(sched.run_job, "sync_lists")
    return {"started": "sync_lists"}


# ---------------------------------------------------------------------- watchlist items
@router.get("/watchlist")
def get_watchlist(list: int | None = None, db: Session = Depends(get_db)):  # noqa: A002
    """Overview rows; `list` narrows to one list, otherwise the union of every list."""
    if list is not None:
        try:
            wls.get_list(db, list)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return md.watchlist_overview(db, list)


def _backfill_new(db: Session, code: str) -> dict:
    daily = md.backfill_daily(db, code)
    md.update_daily_prices(db, {code})
    flows = md.backfill_flows(db, days=20, check_codes={code})
    try:
        md.update_realtime(db, {code})
    except Exception:  # noqa: BLE001
        pass
    return {"code": code, "daily_rows": daily, **flows}


@router.post("/watchlist", status_code=201)
def add_watchlist(body: WatchlistCreate, bg: BackgroundTasks, db: Session = Depends(get_db)):
    """Add a code to one or more user lists (the default list when `lists` is omitted).
    Adding a code that is already in those lists just updates the note (idempotent)."""
    try:
        r = wls.add_code(db, body.code, body.lists, body.note)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        status = 404 if "unknown security" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    do_backfill = body.backfill and r["is_new"]
    if do_backfill:
        bg.add_task(sched.run_job, f"backfill:{r['code']}", _backfill_new, r["code"])
    return {**r, "backfill": do_backfill}


@router.patch("/watchlist/{code}")
def update_watchlist(code: str, body: WatchlistUpdate, db: Session = Depends(get_db)):
    code = code.upper()
    if not wls.memberships(db, {code}).get(code):
        raise HTTPException(status_code=404, detail="not in any watchlist")
    try:
        if body.lists is not None:
            return wls.set_membership(db, code, body.lists, body.note)
        if body.note is not None:
            for item in db.execute(select(WatchlistItem).where(WatchlistItem.code == code)).scalars():
                item.note = body.note
            db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"code": code, "lists": wls.memberships(db, {code}).get(code, []), "note": body.note}


@router.delete("/watchlist/{code}")
def remove_watchlist(code: str, list: int | None = None, db: Session = Depends(get_db)):  # noqa: A002
    """Remove from one list (`?list=`) or from every user list. Alert rules are dropped only
    when the code is no longer in any list."""
    try:
        r = wls.remove_code(db, code, list)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not r["removed"]:
        raise HTTPException(status_code=404, detail="not in that watchlist")
    return r


# ---------------------------------------------------------------------- realtime quotes
@router.get("/quotes")
def get_quotes(codes: str | None = None, db: Session = Depends(get_db)):
    """Latest realtime snapshot per code (price, change, change_pct, volume in lots, trade_date/time).
    `codes=2330,2382` filters; codes outside the watchlist are fetched live from the MIS feed."""
    wanted = {c.strip().upper() for c in codes.split(",") if c.strip()} if codes else None
    rows = {q.code: to_dict(q) for q in md.load_realtime(db, wanted)}
    missing = sorted(wanted - rows.keys()) if wanted else []
    if missing:
        for q in md.mis.fetch_quotes([(c, "TWSE") for c in missing] + [(c, "TPEX") for c in missing]):
            rows.setdefault(q["code"], {k: v for k, v in q.items() if k not in ("limit_up", "limit_down")})
    return list(rows.values())


@router.post("/quotes/refresh")
def refresh_quotes(db: Session = Depends(get_db)):
    """Poll the MIS feed right now (works outside trading hours too; returns last session's data)."""
    quotes = md.update_realtime(db)
    events = alerts.evaluate_intraday(db, quotes)
    return {"quotes": quotes, "alerts": [to_dict(e) for e in events]}


# ---------------------------------------------------------------------- alerts
@router.get("/alerts/rule-types")
def rule_types():
    return [
        {"type": k, **v, "default_cooldown": alerts.DEFAULT_COOLDOWN[v["scope"]]} for k, v in alerts.RULE_TYPES.items()
    ]


@router.get("/alerts")
def list_alerts(code: str | None = None, db: Session = Depends(get_db)):
    stmt = select(AlertRule).order_by(AlertRule.created_at.desc())
    if code:
        stmt = stmt.where(AlertRule.code == code.upper())
    return [to_dict(r) for r in db.execute(stmt).scalars()]


@router.post("/alerts", status_code=201)
def create_alert(body: AlertRuleCreate, db: Session = Depends(get_db)):
    code = body.code.strip().upper()
    try:
        md.ensure_stock(db, code)
        params = alerts.normalise_params(body.rule_type, body.params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rule = AlertRule(
        code=code,
        rule_type=body.rule_type,
        params=params,
        enabled=body.enabled,
        one_shot=body.one_shot,
        cooldown_minutes=body.cooldown_minutes
        if body.cooldown_minutes is not None
        else alerts.DEFAULT_COOLDOWN[alerts.rule_scope(body.rule_type)],
        note=body.note,
    )
    db.add(rule)
    db.commit()
    return to_dict(rule)


@router.patch("/alerts/{rule_id}")
def update_alert(rule_id: int, body: AlertRuleUpdate, db: Session = Depends(get_db)):
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="rule not found")
    if body.params is not None:
        try:
            rule.params = alerts.normalise_params(rule.rule_type, body.params)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    for field in ("enabled", "one_shot", "cooldown_minutes", "note"):
        v = getattr(body, field)
        if v is not None:
            setattr(rule, field, v)
    if body.enabled:
        rule.last_triggered_at = None  # re-arm
    db.commit()
    return to_dict(rule)


@router.delete("/alerts/{rule_id}", status_code=204)
def delete_alert(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="rule not found")
    db.delete(rule)
    db.commit()
    return None


@router.get("/alerts/events")
def alert_events(limit: int = 100, code: str | None = None, db: Session = Depends(get_db)):
    return [to_dict(e) for e in alerts.recent_events(db, limit, code.upper() if code else None)]


@router.post("/alerts/evaluate")
def evaluate_alerts(db: Session = Depends(get_db)):
    events = alerts.evaluate_daily(db)
    return {"alerts": [to_dict(e) for e in events]}


# ---------------------------------------------------------------------- market breadth (盤面分化)
def _parse_date(s: str | None):
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD") from exc


@router.get("/market/dates")
def market_dates(limit: int = 60, db: Session = Depends(get_db)):
    return [d.isoformat() for d in breadth.available_dates(db, limit)]


@router.get("/market/breadth")
def market_breadth(date: str | None = None, db: Session = Depends(get_db)):  # noqa: A002
    return breadth.compute_breadth(db, _parse_date(date))


@router.get("/market/breadth/history")
def market_breadth_history(days: int = 30, db: Session = Depends(get_db)):
    return breadth.breadth_history(db, days)


@router.get("/market/sectors/history")
def market_sector_history(days: int = 10, db: Session = Depends(get_db)):
    return breadth.sector_history(db, days)


@router.get("/market/sectors/{name}/stocks")
def market_sector_stocks(name: str, date: str | None = None, db: Session = Depends(get_db)):  # noqa: A002
    return breadth.sector_stocks(db, name, _parse_date(date))


# ---------------------------------------------------------------------- screener (選股掃描)
class ScreenerRun(BaseModel):
    preset: str = "balanced"
    date: str | None = None
    min_turnover: float = 50_000_000
    top: int = 30
    notify: bool = False
    weights: dict[str, float] | None = None


@router.get("/screener/presets")
def screener_presets():
    return {
        "presets": [{"key": k, "label": v["label"], "weights": v["weights"]} for k, v in screener.PRESETS.items()],
        "factors": screener.FACTOR_LABELS,
    }


@router.get("/screener/dates")
def screener_dates(preset: str | None = None, db: Session = Depends(get_db)):
    return [d.isoformat() for d in screener.result_dates(db, preset)]


@router.get("/screener")
def screener_results(preset: str = "balanced", date: str | None = None, limit: int = 30, db: Session = Depends(get_db)):  # noqa: A002
    return screener.load_results(db, _parse_date(date), preset, limit)


@router.post("/screener/run")
def screener_run(body: ScreenerRun, db: Session = Depends(get_db)):
    try:
        return screener.run_screener(
            db, _parse_date(body.date), body.preset, body.min_turnover, body.top, body.notify, body.weights
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------- jobs
@router.get("/jobs")
def jobs():
    return {
        "available": list(sched.JOBS.keys()),
        "scheduled": sched.list_jobs(),
        "realtime": sched.realtime_status,
        "trading_hours": is_trading_hours(),
    }


@router.post("/jobs/{name}/run", status_code=202)
def run_job(name: str, bg: BackgroundTasks):
    if name not in sched.JOBS:
        raise HTTPException(status_code=404, detail=f"unknown job: {name}")
    bg.add_task(sched.run_job, name)
    return {"started": name, "at": datetime.now().isoformat(timespec="seconds")}


@router.get("/jobs/runs")
def job_runs(limit: int = 30, db: Session = Depends(get_db)):
    stmt = select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
    return [to_dict(r) for r in db.execute(stmt).scalars()]


# ---------------------------------------------------------------------- notifications
@router.post("/notify/test")
def notify_test(body: NotifyTest):
    return {"channels": notifier.channels(), "result": notifier.send("TW Stock Tracker", body.message)}
