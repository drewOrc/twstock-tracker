"""REST API in three namespaces (see main.py for the mounts):

  public   /api/health                      no login
  market   /api/market/*  (legacy /api/*)   通用層: anyone logged in, same data for everyone
  me       /api/me/*      (legacy /api/*)   個人化層: scoped to the logged-in user
  admin    /api/admin/*                     jobs, notification test, system-list sync
"""
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
from ..models import AlertRule, JobRun, Stock, User, WatchlistItem
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
from .deps import current_user, require_admin

public = APIRouter(tags=["public"])
market = APIRouter(tags=["market"], dependencies=[Depends(current_user)])
me = APIRouter(tags=["me"], dependencies=[Depends(current_user)])
admin = APIRouter(tags=["admin"], dependencies=[Depends(require_admin)])


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


def _parse_date(s: str | None):
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD") from exc


# ====================================================================== public
@public.get("/health")
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


# ====================================================================== market (通用層)
@market.get("/health/data")
def health_data(db: Session = Depends(get_db)):
    """Per-table freshness against the publishing schedule, failed jobs in 24h, storage."""
    from ..services.health import data_health

    return data_health(db)


@market.get("/stocks/search")
def search_stocks(q: str = Query(..., min_length=1), limit: int = 20, db: Session = Depends(get_db)):
    return [to_dict(s) for s in md.search_stocks(db, q, limit)]


@market.get("/stocks/{code}/daily")
def stock_daily(code: str, limit: int = 250, db: Session = Depends(get_db)):
    df = md.load_daily_df(db, code.upper(), limit)
    return [{k: _clean(v) for k, v in row.items()} for row in df.to_dict(orient="records")]


@market.get("/stocks/{code}/indicators")
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


@market.get("/stocks/{code}/summary")
def stock_summary(code: str, news: bool = True, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """基本介紹 + 最近狀況. The `context` block (lists, alerts) is the caller's own."""
    from ..services.stock_summary import stock_summary as build

    try:
        return build(db, code, with_news=news, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@market.get("/stocks/{code}/news")
def stock_news(code: str, limit: int = 10, db: Session = Depends(get_db)):
    from ..services.stock_summary import fetch_news

    stock = db.get(Stock, code.upper())
    name = stock.name if stock and stock.name else code.upper()
    items, err = fetch_news(name, limit)
    return {"query": name, "items": items, "error": err}


@market.get("/stocks/{code}/institutional")
def stock_institutional(code: str, limit: int = 60, days: int | None = None, db: Session = Depends(get_db)):
    """Newest first. `days` is an alias for `limit` (one row per trading day)."""
    return [to_dict(r) for r in md.load_institutional(db, code.upper(), days or limit)]


@market.get("/stocks/{code}/margin")
def stock_margin(code: str, limit: int = 60, days: int | None = None, db: Session = Depends(get_db)):
    return [to_dict(r) for r in md.load_margin(db, code.upper(), days or limit)]


@market.get("/quotes")
def get_quotes(codes: str | None = None, db: Session = Depends(get_db)):
    """Latest realtime snapshot per code. `codes=2330,2382` filters; unknown codes are fetched live."""
    wanted = {c.strip().upper() for c in codes.split(",") if c.strip()} if codes else None
    rows = {q.code: to_dict(q) for q in md.load_realtime(db, wanted)}
    missing = sorted(wanted - rows.keys()) if wanted else []
    if missing:
        for q in md.mis.fetch_quotes([(c, "TWSE") for c in missing] + [(c, "TPEX") for c in missing]):
            rows.setdefault(q["code"], {k: v for k, v in q.items() if k not in ("limit_up", "limit_down")})
    return list(rows.values())


@market.post("/quotes/refresh")
def refresh_quotes(db: Session = Depends(get_db)):
    """Poll the MIS feed right now (outside trading hours returns last session's data)."""
    quotes = md.update_realtime(db)
    events = alerts.evaluate_intraday(db, quotes)
    return {"quotes": quotes, "alerts": [to_dict(e) for e in events]}


@market.get("/market/dates")
def market_dates(limit: int = 60, db: Session = Depends(get_db)):
    return [d.isoformat() for d in breadth.available_dates(db, limit)]


@market.get("/market/breadth")
def market_breadth(date: str | None = None, db: Session = Depends(get_db)):  # noqa: A002
    return breadth.compute_breadth(db, _parse_date(date))


@market.get("/market/breadth/history")
def market_breadth_history(days: int = 30, db: Session = Depends(get_db)):
    return breadth.breadth_history(db, days)


@market.get("/market/sectors/history")
def market_sector_history(days: int = 10, db: Session = Depends(get_db)):
    return breadth.sector_history(db, days)


@market.get("/market/sectors/{name}/stocks")
def market_sector_stocks(name: str, date: str | None = None, db: Session = Depends(get_db)):  # noqa: A002
    return breadth.sector_stocks(db, name, _parse_date(date))


class ScreenerRun(BaseModel):
    preset: str = "balanced"
    date: str | None = None
    min_turnover: float = 50_000_000
    top: int = 30
    notify: bool = False
    weights: dict[str, float] | None = None


@market.get("/screener/presets")
def screener_presets():
    return {
        "presets": [{"key": k, "label": v["label"], "weights": v["weights"]} for k, v in screener.PRESETS.items()],
        "factors": screener.FACTOR_LABELS,
    }


@market.get("/screener/dates")
def screener_dates(preset: str | None = None, db: Session = Depends(get_db)):
    return [d.isoformat() for d in screener.result_dates(db, preset)]


@market.get("/screener")
def screener_results(preset: str = "balanced", date: str | None = None, limit: int = 30, db: Session = Depends(get_db)):  # noqa: A002
    return screener.load_results(db, _parse_date(date), preset, limit)


@market.post("/screener/run")
def screener_run(body: ScreenerRun, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        return screener.run_screener(
            db, _parse_date(body.date), body.preset, body.min_turnover, body.top, body.notify and user.role == "admin", body.weights
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@market.get("/alerts/rule-types")
def rule_types():
    return [
        {"type": k, **v, "default_cooldown": alerts.DEFAULT_COOLDOWN[v["scope"]]} for k, v in alerts.RULE_TYPES.items()
    ]


@market.get("/jobs")
def jobs():
    return {
        "available": list(sched.JOBS.keys()),
        "scheduled": sched.list_jobs(),
        "realtime": sched.realtime_status,
        "trading_hours": is_trading_hours(),
    }


@market.get("/jobs/runs")
def job_runs(limit: int = 30, db: Session = Depends(get_db)):
    stmt = select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
    return [to_dict(r) for r in db.execute(stmt).scalars()]


# ====================================================================== me (個人化層)
@me.get("/watchlists")
def get_watchlists(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return wls.list_watchlists(db, user.id)


@me.post("/watchlists", status_code=201)
def create_watchlist(body: WatchlistDef, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        return to_dict(wls.create_watchlist(db, user.id, body.name, body.color))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@me.patch("/watchlists/{list_id}")
def patch_watchlist(list_id: int, body: WatchlistPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        return to_dict(wls.update_watchlist(db, user.id, list_id, body.name, body.color, body.sort_order))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@me.delete("/watchlists/{list_id}")
def delete_watchlist(list_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        return {"deleted": list_id, "unsubscribed": wls.delete_watchlist(db, user.id, list_id)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@me.get("/watchlist")
def get_watchlist(list: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):  # noqa: A002
    """Overview rows of my lists; `list` narrows to one list, otherwise the union of my lists."""
    if list is not None:
        try:
            wls.get_list(db, user.id, list)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return md.watchlist_overview(db, list, user_id=user.id)


def _backfill_new(db: Session, code: str) -> dict:
    daily = md.backfill_daily(db, code)
    md.update_daily_prices(db, {code})
    flows = md.backfill_flows(db, days=20, check_codes={code})
    try:
        md.update_realtime(db, {code})
    except Exception:  # noqa: BLE001
        pass
    return {"code": code, "daily_rows": daily, **flows}


@me.post("/watchlist", status_code=201)
def add_watchlist(body: WatchlistCreate, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Add a code to one or more of my lists (my default list when `lists` is omitted)."""
    try:
        r = wls.add_code(db, user.id, body.code, body.lists, body.note)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        status = 404 if "unknown security" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    do_backfill = body.backfill and r["is_new"]
    if do_backfill:
        bg.add_task(sched.run_job, f"backfill:{r['code']}", _backfill_new, r["code"])
    return {**r, "backfill": do_backfill}


@me.patch("/watchlist/{code}")
def update_watchlist(code: str, body: WatchlistUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    code = code.upper()
    if not wls.memberships(db, {code}, user.id).get(code):
        raise HTTPException(status_code=404, detail="not in any of your watchlists")
    try:
        if body.lists is not None:
            return wls.set_membership(db, user.id, code, body.lists, body.note)
        if body.note is not None:
            my_lists = [w["id"] for w in wls.list_watchlists(db, user.id)]
            for item in db.execute(select(WatchlistItem).where(WatchlistItem.code == code, WatchlistItem.watchlist_id.in_(my_lists))).scalars():
                item.note = body.note
            db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"code": code, "lists": wls.memberships(db, {code}, user.id).get(code, []), "note": body.note}


@me.delete("/watchlist/{code}")
def remove_watchlist(code: str, list: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):  # noqa: A002
    """Remove from one of my lists (`?list=`) or from all my user lists."""
    try:
        r = wls.remove_code(db, user.id, code, list)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not r["removed"]:
        raise HTTPException(status_code=404, detail="not in that watchlist")
    return r


@me.get("/alerts")
def list_alerts(code: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(AlertRule).where(AlertRule.user_id == user.id).order_by(AlertRule.created_at.desc())
    if code:
        stmt = stmt.where(AlertRule.code == code.upper())
    return [to_dict(r) for r in db.execute(stmt).scalars()]


@me.post("/alerts", status_code=201)
def create_alert(body: AlertRuleCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    code = body.code.strip().upper()
    try:
        md.ensure_stock(db, code)
        params = alerts.normalise_params(body.rule_type, body.params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rule = AlertRule(
        user_id=user.id, code=code, rule_type=body.rule_type, params=params, enabled=body.enabled, one_shot=body.one_shot,
        cooldown_minutes=body.cooldown_minutes if body.cooldown_minutes is not None else alerts.DEFAULT_COOLDOWN[alerts.rule_scope(body.rule_type)],
        note=body.note,
    )
    db.add(rule)
    db.commit()
    return to_dict(rule)


def _my_rule(db: Session, user: User, rule_id: int) -> AlertRule:
    rule = db.get(AlertRule, rule_id)
    if not rule or rule.user_id != user.id:
        raise HTTPException(status_code=404, detail="rule not found")
    return rule


@me.patch("/alerts/{rule_id}")
def update_alert(rule_id: int, body: AlertRuleUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rule = _my_rule(db, user, rule_id)
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


@me.delete("/alerts/{rule_id}", status_code=204)
def delete_alert(rule_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_my_rule(db, user, rule_id))
    db.commit()
    return None


@me.post("/alerts/sync-crm")
def sync_crm_alerts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Mirror my CRM cards' target / stop prices into alert rules right now."""
    from ..services import crm_link

    crm_link.forget_positions(user.id)
    return crm_link.sync_target_alerts(db, user)


@me.get("/alerts/events")
def alert_events(limit: int = 100, code: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [to_dict(e) for e in alerts.recent_events(db, limit, code.upper() if code else None, user_id=user.id)]


@me.post("/alerts/evaluate")
def evaluate_alerts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    events = alerts.evaluate_daily(db, user_id=user.id)
    return {"alerts": [to_dict(e) for e in events]}


# ====================================================================== admin
@admin.post("/jobs/{name}/run", status_code=202)
def run_job(name: str, bg: BackgroundTasks):
    if name not in sched.JOBS:
        raise HTTPException(status_code=404, detail=f"unknown job: {name}")
    bg.add_task(sched.run_job, name)
    return {"started": name, "at": datetime.now().isoformat(timespec="seconds")}


@admin.post("/watchlists/sync")
def sync_watchlists(bg: BackgroundTasks):
    """Rebuild every user's system lists (CRM 持有 / 觀察、掃描候選、今日警示) in the background."""
    bg.add_task(sched.run_job, "sync_lists")
    return {"started": "sync_lists"}


@admin.post("/notify/test")
def notify_test(body: NotifyTest, user: User = Depends(require_admin)):
    return {"channels": notifier.channels(user), "result": notifier.send("TW Stock Tracker", body.message, user=user)}
