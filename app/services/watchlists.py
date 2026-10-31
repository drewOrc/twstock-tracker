"""Multiple watchlists (追蹤池).

User lists are free-form groupings; system lists are rebuilt by sync_system_lists():
  crm_hold / crm_watch  cards in Stock CRM with stage hold / watch (read through its REST API)
  screener              latest balanced screener top-N
  alerts_today          codes with an alert event in the last 24 hours
Data subscription (daily, flows, realtime, alert evaluation) uses the union of every list.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import DEFAULT_LIST_NAME
from ..models import AlertEvent, AlertRule, ScreenerResult, Watchlist, WatchlistItem
from . import market_data as md

log = logging.getLogger(__name__)

SYSTEM_LISTS: dict[str, dict] = {
    "crm_hold": {"name": "CRM 持有", "color": "#a78bfa", "sort_order": 900},
    "crm_watch": {"name": "CRM 觀察", "color": "#38bdf8", "sort_order": 901},
    "screener": {"name": "掃描候選", "color": "#f5c542", "sort_order": 902},
    "alerts_today": {"name": "今日警示", "color": "#ef5350", "sort_order": 903},
}
SCREENER_LIST_TOP = 20
SYNC_BACKFILL_LIMIT = 10  # new CRM codes backfilled per sync run (each ~6 monthly requests)


# ---------------------------------------------------------------------- lists
def ensure_default_list(db: Session) -> Watchlist:
    wl = db.execute(select(Watchlist).where(Watchlist.system_key.is_(None)).order_by(Watchlist.sort_order, Watchlist.id)).scalars().first()
    if wl:
        return wl
    wl = Watchlist(name=DEFAULT_LIST_NAME, color="#4f8cff", sort_order=0)
    db.add(wl)
    db.commit()
    return wl


def ensure_system_lists(db: Session) -> dict[str, Watchlist]:
    out: dict[str, Watchlist] = {}
    changed = False
    for key, spec in SYSTEM_LISTS.items():
        wl = db.execute(select(Watchlist).where(Watchlist.system_key == key)).scalar_one_or_none()
        if wl is None:
            wl = Watchlist(name=spec["name"], color=spec["color"], sort_order=spec["sort_order"], system_key=key)
            db.add(wl)
            changed = True
        out[key] = wl
    if changed:
        db.commit()
    return out


def list_watchlists(db: Session) -> list[dict]:
    ensure_default_list(db)
    ensure_system_lists(db)
    counts = dict(db.execute(select(WatchlistItem.watchlist_id, func.count()).group_by(WatchlistItem.watchlist_id)).all())
    rows = db.execute(select(Watchlist).order_by(Watchlist.sort_order, Watchlist.id)).scalars()
    return [
        {"id": w.id, "name": w.name, "color": w.color, "sort_order": w.sort_order, "system_key": w.system_key, "count": counts.get(w.id, 0)}
        for w in rows
    ]


def get_list(db: Session, list_id: int) -> Watchlist:
    wl = db.get(Watchlist, list_id)
    if wl is None:
        raise LookupError(f"watchlist {list_id} not found")
    return wl


def create_watchlist(db: Session, name: str, color: str | None = None) -> Watchlist:
    name = name.strip()
    if not name:
        raise ValueError("name is required")
    if db.execute(select(Watchlist).where(Watchlist.name == name)).scalar_one_or_none():
        raise ValueError(f"watchlist '{name}' already exists")
    max_order = db.execute(select(func.max(Watchlist.sort_order)).where(Watchlist.system_key.is_(None))).scalar() or 0
    wl = Watchlist(name=name, color=color, sort_order=max_order + 1)
    db.add(wl)
    db.commit()
    return wl


def update_watchlist(db: Session, list_id: int, name: str | None = None, color: str | None = None, sort_order: int | None = None) -> Watchlist:
    wl = get_list(db, list_id)
    if name is not None and name.strip() and name.strip() != wl.name:
        if wl.system_key:
            raise ValueError("system lists cannot be renamed")
        if db.execute(select(Watchlist).where(Watchlist.name == name.strip())).scalar_one_or_none():
            raise ValueError(f"watchlist '{name}' already exists")
        wl.name = name.strip()
    if color is not None:
        wl.color = color
    if sort_order is not None:
        wl.sort_order = sort_order
    db.commit()
    return wl


def delete_watchlist(db: Session, list_id: int) -> list[str]:
    """Delete a user list. Returns codes that thereby left every list (their alert rules are removed)."""
    wl = get_list(db, list_id)
    if wl.system_key:
        raise ValueError("system lists cannot be deleted")
    codes = codes_in(db, list_id)
    db.delete(wl)
    db.flush()
    orphaned = [c for c in sorted(codes) if not _in_any_list(db, c)]
    if orphaned:
        db.execute(delete(AlertRule).where(AlertRule.code.in_(orphaned)))
    db.commit()
    return orphaned


def codes_in(db: Session, list_id: int) -> set[str]:
    return set(db.execute(select(WatchlistItem.code).where(WatchlistItem.watchlist_id == list_id)).scalars())


def _in_any_list(db: Session, code: str) -> bool:
    return db.execute(select(WatchlistItem.id).where(WatchlistItem.code == code).limit(1)).first() is not None


def memberships(db: Session, codes: set[str] | None = None) -> dict[str, list[int]]:
    stmt = select(WatchlistItem.code, WatchlistItem.watchlist_id)
    if codes is not None:
        if not codes:
            return {}
        stmt = stmt.where(WatchlistItem.code.in_(codes))
    out: dict[str, list[int]] = {}
    for code, lid in db.execute(stmt):
        out.setdefault(code, []).append(lid)
    return out


# ---------------------------------------------------------------------- items
def add_code(db: Session, code: str, list_ids: list[int] | None = None, note: str | None = None) -> dict:
    """Put a code into the given user lists (default list when none given). Returns the membership
    plus is_new=True when the code was not subscribed anywhere before (caller may backfill)."""
    stock = md.ensure_stock(db, code)
    code = stock.code
    targets = [get_list(db, i) for i in list_ids] if list_ids else [ensure_default_list(db)]
    for wl in targets:
        if wl.system_key:
            raise ValueError(f"'{wl.name}' is a system list; it is maintained automatically")
    was_subscribed = _in_any_list(db, code)
    added = []
    for wl in targets:
        exists = db.execute(select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id, WatchlistItem.code == code)).scalar_one_or_none()
        if exists:
            if note is not None:
                exists.note = note
            continue
        db.add(WatchlistItem(watchlist_id=wl.id, code=code, note=note))
        added.append(wl.id)
    db.commit()
    return {
        "code": code, "name": stock.name, "market": stock.market, "note": note,
        "lists": memberships(db, {code}).get(code, []), "added_to": added, "is_new": not was_subscribed,
    }


def set_membership(db: Session, code: str, list_ids: list[int], note: str | None = None) -> dict:
    """Make the code's USER-list membership exactly list_ids (system lists untouched)."""
    code = code.strip().upper()
    user_ids = {w.id for w in db.execute(select(Watchlist).where(Watchlist.system_key.is_(None))).scalars()}
    wanted = {i for i in list_ids if i in user_ids}
    if any(i not in user_ids for i in list_ids):
        raise ValueError("list_ids may only contain user lists")
    current = {i for i in memberships(db, {code}).get(code, []) if i in user_ids}
    for lid in current - wanted:
        db.execute(delete(WatchlistItem).where(WatchlistItem.watchlist_id == lid, WatchlistItem.code == code))
    for lid in wanted - current:
        db.add(WatchlistItem(watchlist_id=lid, code=code, note=note))
    if note is not None:
        for item in db.execute(select(WatchlistItem).where(WatchlistItem.code == code, WatchlistItem.watchlist_id.in_(wanted))).scalars():
            item.note = note
    db.flush()
    if not _in_any_list(db, code):
        db.execute(delete(AlertRule).where(AlertRule.code == code))
    db.commit()
    return {"code": code, "lists": memberships(db, {code}).get(code, [])}


def remove_code(db: Session, code: str, list_id: int | None = None) -> dict:
    """Remove from one list, or from every user list when list_id is None. When the code is no
    longer in any list at all, its alert rules go too (events are kept)."""
    code = code.strip().upper()
    stmt = delete(WatchlistItem).where(WatchlistItem.code == code)
    if list_id is not None:
        wl = get_list(db, list_id)
        if wl.system_key:
            raise ValueError(f"'{wl.name}' is a system list; it is maintained automatically")
        stmt = stmt.where(WatchlistItem.watchlist_id == list_id)
    else:
        user_ids = select(Watchlist.id).where(Watchlist.system_key.is_(None))
        stmt = stmt.where(WatchlistItem.watchlist_id.in_(user_ids))
    removed = db.execute(stmt).rowcount
    db.flush()
    unsubscribed = not _in_any_list(db, code)
    if unsubscribed:
        db.execute(delete(AlertRule).where(AlertRule.code == code))
    db.commit()
    return {"code": code, "removed": removed, "lists": memberships(db, {code}).get(code, []), "unsubscribed": unsubscribed}


# ---------------------------------------------------------------------- system lists
def _crm_codes(stage: str) -> list[str] | None:
    """TW codes of CRM cards in a stage; None when the CRM is unreachable (keep the previous list)."""
    try:
        r = httpx.get(f"{settings.crm_base_url}/api/positions", params={"stage": stage}, timeout=5.0)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        log.info("CRM not reachable for list sync: %s", type(exc).__name__)
        return None
    return [p["company_id"][3:] for p in r.json() if str(p.get("company_id", "")).startswith("TW:")]


def _replace_items(db: Session, wl: Watchlist, codes: list[str]) -> tuple[int, list[str]]:
    """Set a system list's content; returns (count, codes that were not subscribed anywhere before)."""
    wanted = []
    for c in codes:
        try:
            wanted.append(md.ensure_stock(db, c).code)
        except Exception as exc:  # noqa: BLE001
            log.info("skip %s in %s: %s", c, wl.name, exc)
    before = set(db.execute(select(distinct(WatchlistItem.code))).scalars())
    db.execute(delete(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id))
    for c in dict.fromkeys(wanted):
        db.add(WatchlistItem(watchlist_id=wl.id, code=c))
    db.commit()
    return len(set(wanted)), [c for c in dict.fromkeys(wanted) if c not in before]


def sync_system_lists(db: Session, backfill: bool = True) -> dict:
    lists = ensure_system_lists(db)
    result: dict = {}
    new_codes: list[str] = []

    for key, stage in (("crm_hold", "hold"), ("crm_watch", "watch")):
        codes = _crm_codes(stage)
        if codes is None:
            result[key] = {"skipped": "crm unreachable"}
            continue
        n, fresh = _replace_items(db, lists[key], codes)
        result[key] = {"count": n}
        new_codes += fresh

    latest = db.execute(select(ScreenerResult.date).where(ScreenerResult.preset == "balanced").order_by(ScreenerResult.date.desc()).limit(1)).scalar()
    if latest:
        codes = list(
            db.execute(
                select(ScreenerResult.code)
                .where(ScreenerResult.preset == "balanced", ScreenerResult.date == latest)
                .order_by(ScreenerResult.rank)
                .limit(SCREENER_LIST_TOP)
            ).scalars()
        )
        n, _ = _replace_items(db, lists["screener"], codes)
        result["screener"] = {"count": n, "date": latest.isoformat()}
    else:
        result["screener"] = {"count": 0}

    since = datetime.now() - timedelta(hours=24)
    codes = list(db.execute(select(distinct(AlertEvent.code)).where(AlertEvent.triggered_at >= since)).scalars())
    n, _ = _replace_items(db, lists["alerts_today"], codes)
    result["alerts_today"] = {"count": n}

    if backfill and new_codes:
        done = 0
        for c in new_codes[:SYNC_BACKFILL_LIMIT]:
            try:
                md.backfill_daily(db, c)
                done += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("backfill for synced %s failed: %s", c, exc)
        result["backfilled"] = done
    return result
