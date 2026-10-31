"""Engine <-> Stock CRM links (read CRM over REST; write only through its proposal queue).

- sync_target_alerts(): every CRM card with a target_price / stop_price gets a mirrored
  price_above / price_below rule (source = crm_target / crm_stop). Changes update the rule,
  removed prices or exited cards delete it.
- notify_alert(): a fired alert becomes an interaction *proposal* on the matching card, which
  the user approves in the CRM. Never writes interactions directly.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AlertRule
from . import market_data as md

log = logging.getLogger(__name__)

AGENT = "engine:twstock-tracker"
TARGET_COOLDOWN_MIN = 7 * 24 * 60  # a mirrored price level re-fires at most weekly
_client = httpx.Client(timeout=8.0)
_position_cache: dict[str, tuple[float, int | None]] = {}
POSITION_TTL = 600


# ---------------------------------------------------------------------- http helpers
def _url(path: str) -> str:
    return f"{settings.crm_base_url.rstrip('/')}{path}"


def crm_get(path: str, params: dict | None = None) -> Any | None:
    try:
        r = _client.get(_url(path), params=params)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as exc:
        log.info("CRM GET %s failed: %s", path, type(exc).__name__)
        return None


def crm_post(path: str, body: dict) -> tuple[int, Any]:
    """Returns (status_code, json|text). status 0 = unreachable."""
    try:
        r = _client.post(_url(path), json=body)
        try:
            payload = r.json()
        except ValueError:
            payload = r.text
        return r.status_code, payload
    except httpx.HTTPError as exc:
        log.info("CRM POST %s failed: %s", path, type(exc).__name__)
        return 0, str(exc)


def fetch_positions(stages: tuple[str, ...] = ("hold", "watch")) -> list[dict] | None:
    """TW cards of the given stages; None when the CRM is unreachable."""
    out: list[dict] = []
    for stage in stages:
        rows = crm_get("/api/positions", {"stage": stage})
        if rows is None:
            return None
        out += [p for p in rows if str(p.get("company_id", "")).startswith("TW:")]
    return out


def position_id_for(code: str) -> int | None:
    now = time.time()
    hit = _position_cache.get(code)
    if hit and now - hit[0] < POSITION_TTL:
        return hit[1]
    p = crm_get(f"/api/positions/TW:{code}")
    pid = p.get("id") if isinstance(p, dict) else None
    _position_cache[code] = (now, pid)
    return pid


def forget_position(code: str) -> None:
    _position_cache.pop(code, None)


# ---------------------------------------------------------------------- target / stop -> alert rules
def sync_target_alerts(db: Session) -> dict:
    positions = fetch_positions()
    if positions is None:
        return {"skipped": "crm unreachable"}
    desired: dict[tuple[str, str], dict] = {}
    for p in positions:
        code = p["company_id"][3:]
        for field, source, rule_type, label in (
            ("target_price", "crm_target", "price_above", "目標價"),
            ("stop_price", "crm_stop", "price_below", "停損價"),
        ):
            price = p.get(field)
            if price in (None, 0, ""):
                continue
            desired[(code, source)] = {
                "price": float(price), "rule_type": rule_type, "position_id": p["id"],
                "note": f"CRM {label}（{p.get('name') or code}）",
            }
    existing = {
        (r.code, r.source): r
        for r in db.execute(select(AlertRule).where(AlertRule.source.in_(["crm_target", "crm_stop"]))).scalars()
    }
    created = updated = deleted = unchanged = 0
    for key, rule in existing.items():
        want = desired.get(key)
        if want is None:
            db.delete(rule)
            deleted += 1
        elif float(rule.params.get("price", -1)) != want["price"] or rule.rule_type != want["rule_type"]:
            rule.params = {"price": want["price"]}
            rule.rule_type = want["rule_type"]
            rule.enabled = True
            rule.last_triggered_at = None
            rule.note = want["note"]
            rule.source_ref = str(want["position_id"])
            updated += 1
        else:
            unchanged += 1
    skipped: list[str] = []
    for key, want in desired.items():
        if key in existing:
            continue
        code, source = key
        try:
            md.ensure_stock(db, code)
        except Exception as exc:  # noqa: BLE001
            log.info("skip CRM alert for %s: %s", code, exc)
            skipped.append(code)
            continue
        db.add(
            AlertRule(
                code=code, rule_type=want["rule_type"], params={"price": want["price"]}, enabled=True, one_shot=False,
                cooldown_minutes=TARGET_COOLDOWN_MIN, note=want["note"], source=source, source_ref=str(want["position_id"]),
            )
        )
        created += 1
    db.commit()
    return {"created": created, "updated": updated, "deleted": deleted, "unchanged": unchanged, "skipped": skipped, "cards": len(positions)}


# ---------------------------------------------------------------------- fired alert -> CRM proposal
def notify_alert(code: str, rule: AlertRule, title: str, message: str, value: float | None) -> str:
    """Returns a short delivery status for the event log: 'ok', 'no card', or 'error: ...'."""
    if not settings.crm_proposals:
        return "disabled"
    pid = position_id_for(code)
    if pid is None:
        return "no card"
    content = f"[引擎警示] {title}：{message}"
    rationale = f"引擎警示規則 {rule.rule_type} {rule.params} 於 {code} 觸發" + (f"（{rule.note}）" if rule.note else "")
    payload = {"position_id": pid, "kind": settings.crm_alert_kind, "content": content, "price": value}
    body = {"kind": "interaction", "payload": payload, "rationale": rationale, "created_by": AGENT}
    status, resp = crm_post("/api/proposals", body)
    if status == 400 and settings.crm_alert_kind != "news" and "kind" in str(resp):
        # CRM without the 'alert' interaction kind: fall back to 'news'
        payload["kind"] = "news"
        status, resp = crm_post("/api/proposals", body)
    if status in (200, 201):
        return "ok"
    if status == 0:
        return "error: crm unreachable"
    return f"error: HTTP {status} {str(resp)[:120]}"
