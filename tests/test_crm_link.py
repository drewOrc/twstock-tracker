"""CRM links per user: target / stop prices mirrored as alert rules, fired alerts proposed back."""
from datetime import datetime

import httpx
import pytest

from app.db import init_db, session_scope
from app.models import AlertEvent, AlertRule, Stock, User
from app.services import alerts, crm_link
from app.services import market_data as md


@pytest.fixture
def crm(monkeypatch, admin_id):
    """Fake CRM: positions list + detail + proposals inbox, recording identity headers."""
    state = {"positions": [], "proposals": [], "alert_kind_supported": True, "headers": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["headers"].append(dict(request.headers))
        path = request.url.path
        if path == "/api/positions":
            stage = request.url.params.get("stage")
            return httpx.Response(200, json=[p for p in state["positions"] if p["stage"] == stage])
        if path.startswith("/api/positions/"):
            ref = path.rsplit("/", 1)[1]
            for p in state["positions"]:
                if p["company_id"] == ref:
                    return httpx.Response(200, json=p)
            return httpx.Response(404, json={"detail": "no card"})
        if path == "/api/proposals":
            import json

            body = json.loads(request.content)
            if body["payload"]["kind"] == "alert" and not state["alert_kind_supported"]:
                return httpx.Response(400, json={"detail": "payload.kind must be one of [...]"})
            state["proposals"].append(body)
            return httpx.Response(201, json={"id": len(state["proposals"]), **body})
        return httpx.Response(404)

    monkeypatch.setattr(crm_link, "_client", httpx.Client(transport=httpx.MockTransport(handler), base_url="http://crm"))
    monkeypatch.setattr(crm_link.settings, "crm_base_url", "http://crm")
    monkeypatch.setattr(crm_link.settings, "crm_facade_token", "tok")
    crm_link._position_cache.clear()
    monkeypatch.setattr(md, "refresh_stock_list", lambda db: 0)
    monkeypatch.setattr(md.mis, "fetch_quotes", lambda items: [])
    monkeypatch.setattr(alerts.notifier, "send", lambda title, msg, user=None: {"console": "ok"})
    init_db()
    with session_scope() as s:
        s.query(AlertEvent).delete()
        s.query(AlertRule).delete()
        for code, name in (("2330", "台積電"), ("2382", "廣達")):
            if not s.get(Stock, code):
                s.add(Stock(code=code, name=name, market="TWSE", industry="24", updated_at=datetime.now()))
    state["admin_id"] = admin_id
    return state


def _admin(db, crm):
    return db.get(User, crm["admin_id"])


def test_sync_creates_updates_and_deletes_mirrored_rules(crm):
    crm["positions"] = [
        {"id": 7, "company_id": "TW:2330", "name": "台積電", "stage": "hold", "target_price": 1500, "stop_price": 800},
        {"id": 8, "company_id": "TW:2382", "name": "廣達", "stage": "watch", "target_price": 400, "stop_price": None},
        {"id": 9, "company_id": "US:NVDA", "name": "輝達", "stage": "hold", "target_price": 300, "stop_price": 100},
    ]
    with session_scope() as db:
        admin = _admin(db, crm)
        r = crm_link.sync_target_alerts(db, admin)
        assert (r["created"], r["updated"], r["deleted"]) == (3, 0, 0)
        rules = {(x.code, x.source): x for x in db.query(AlertRule).all()}
        assert rules[("2330", "crm_target")].rule_type == "price_above" and rules[("2330", "crm_target")].params == {"price": 1500.0}
        assert rules[("2330", "crm_stop")].source_ref == "7" and rules[("2330", "crm_stop")].user_id == admin.id
        assert ("2382", "crm_target") in rules and ("2382", "crm_stop") not in rules
        db.add(AlertRule(user_id=admin.id, code="2330", rule_type="rsi_above", params={"period": 14, "value": 70}, cooldown_minutes=60))
        db.commit()
    assert crm["headers"][-1]["x-user-id"] == str(crm["admin_id"]) and crm["headers"][-1]["x-facade-token"] == "tok"

    crm["positions"][0]["target_price"] = 1600
    crm["positions"][0]["stop_price"] = None
    crm["positions"].pop(1)
    with session_scope() as db:
        r = crm_link.sync_target_alerts(db, _admin(db, crm))
        assert (r["created"], r["updated"], r["deleted"], r["unchanged"]) == (0, 1, 2, 0)
        remaining = db.query(AlertRule).all()
        assert {(x.code, x.source) for x in remaining} == {("2330", "crm_target"), ("2330", None)}
        assert next(x for x in remaining if x.source == "crm_target").params == {"price": 1600.0}


def test_sync_all_users_and_unreachable(crm, monkeypatch):
    with session_scope() as db:
        r = crm_link.sync_target_alerts(db)  # every active user
        assert set(r) == {"drew"} and r["drew"]["cards"] == 0
    monkeypatch.setattr(crm_link, "crm_get", lambda *a, **k: None)
    with session_scope() as db:
        assert crm_link.sync_target_alerts(db, _admin(db, crm)) == {"skipped": "crm unreachable"}


def test_fired_alert_becomes_crm_proposal(crm):
    crm["positions"] = [{"id": 7, "company_id": "TW:2330", "name": "台積電", "stage": "hold"}]
    with session_scope() as db:
        rule = AlertRule(user_id=crm["admin_id"], code="2330", rule_type="price_above", params={"price": 2000.0}, cooldown_minutes=60, note="CRM 目標價")
        db.add(rule)
        db.commit()
        ev = alerts.fire(db, rule, "收盤 2370 已突破 2000", 2370.0, datetime.now())
        assert ev.delivery["crm"] == "ok" and ev.user_id == crm["admin_id"]
    prop = crm["proposals"][0]
    assert prop["kind"] == "interaction" and prop["created_by"] == "engine:twstock-tracker"
    assert prop["payload"]["position_id"] == 7 and prop["payload"]["kind"] == "alert" and prop["payload"]["price"] == 2370.0
    assert "[引擎警示]" in prop["payload"]["content"] and "price_above" in prop["rationale"]


def test_fired_alert_falls_back_to_news_kind_and_skips_without_card(crm):
    crm["alert_kind_supported"] = False
    crm["positions"] = [{"id": 7, "company_id": "TW:2330", "name": "台積電", "stage": "hold"}]
    with session_scope() as db:
        rule = AlertRule(user_id=crm["admin_id"], code="2330", rule_type="volume_spike", params={"multiplier": 2, "window": 20}, cooldown_minutes=60)
        db.add(rule)
        db.commit()
        ev = alerts.fire(db, rule, "爆量", 3.1, datetime.now())
        assert ev.delivery["crm"] == "ok"
        assert crm["proposals"][-1]["payload"]["kind"] == "news"
        rule2 = AlertRule(user_id=crm["admin_id"], code="2382", rule_type="price_below", params={"price": 1.0}, cooldown_minutes=60)
        db.add(rule2)
        db.commit()
        assert alerts.fire(db, rule2, "x", 0.5, datetime.now()).delivery["crm"] == "no card"


def test_sync_endpoint(crm, client):
    crm["positions"] = [{"id": 7, "company_id": "TW:2330", "name": "台積電", "stage": "hold", "target_price": 1500, "stop_price": None}]
    r = client.post("/api/me/alerts/sync-crm")
    assert r.status_code == 200 and r.json()["created"] == 1
    rules = client.get("/api/me/alerts?code=2330").json()
    assert any(x["source"] == "crm_target" for x in rules)
