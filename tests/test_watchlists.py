"""Multiple watchlists: migration from the single-list schema, CRUD, union semantics."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import DEFAULT_LIST_NAME, engine, init_db, session_scope
from app.main import app
from app.models import AlertRule, Stock, Watchlist, WatchlistItem
from app.services import market_data as md
from app.services import watchlists as wls


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No exchange calls: stock master lookups come from rows we insert ourselves."""
    monkeypatch.setattr(md, "refresh_stock_list", lambda db: 0)
    monkeypatch.setattr(md.mis, "fetch_quotes", lambda items: [])
    monkeypatch.setattr(md, "backfill_daily", lambda db, code, months=None: 0)


@pytest.fixture
def db():
    init_db()
    with session_scope() as s:
        s.query(WatchlistItem).delete()
        s.query(Watchlist).delete()
        s.query(AlertRule).delete()
        for code, name, market in (("2330", "台積電", "TWSE"), ("6488", "環球晶", "TPEX"), ("0050", "元大台灣50", "TWSE")):
            if not s.get(Stock, code):
                s.add(Stock(code=code, name=name, market=market, updated_at=datetime.now()))
    with session_scope() as s:
        yield s


def test_migration_moves_legacy_rows_into_default_list(db):
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS watchlist"))
        conn.execute(text("CREATE TABLE watchlist (id INTEGER PRIMARY KEY, code VARCHAR(12) UNIQUE, note TEXT, tags VARCHAR(128), added_at DATETIME)"))
        conn.execute(text("INSERT INTO watchlist (code, note) VALUES ('2330', '台積電'), ('6488', NULL)"))
    init_db()
    init_db()  # idempotent
    lists = wls.list_watchlists(db)
    default = next(w for w in lists if w["name"] == DEFAULT_LIST_NAME)
    assert default["count"] == 2
    assert wls.codes_in(db, default["id"]) == {"2330", "6488"}
    assert {w["system_key"] for w in lists if w["system_key"]} == set(wls.SYSTEM_LISTS)


def test_union_and_last_membership_drops_alert_rules(db):
    a = wls.create_watchlist(db, "AI 供應鏈")
    b = wls.create_watchlist(db, "短線")
    wls.add_code(db, "2330", [a.id, b.id], note="雙清單")
    wls.add_code(db, "6488", [b.id])
    db.add(AlertRule(code="2330", rule_type="price_above", params={"price": 1}, cooldown_minutes=1))
    db.commit()
    assert md.watch_codes(db) == {"2330", "6488"}
    rows = {r["code"]: r for r in md.watchlist_overview(db)}
    assert sorted(rows["2330"]["lists"]) == sorted([a.id, b.id]) and rows["2330"]["note"] == "雙清單"
    assert [r["code"] for r in md.watchlist_overview(db, a.id)] == ["2330"]

    r = wls.remove_code(db, "2330", a.id)
    assert r["lists"] == [b.id] and r["unsubscribed"] is False
    assert db.query(AlertRule).filter_by(code="2330").count() == 1

    r = wls.remove_code(db, "2330")  # from every user list
    assert r["unsubscribed"] is True and r["lists"] == []
    assert db.query(AlertRule).filter_by(code="2330").count() == 0
    assert md.watch_codes(db) == {"6488"}


def test_system_lists_are_read_only(db):
    sys_lists = wls.ensure_system_lists(db)
    with pytest.raises(ValueError):
        wls.add_code(db, "2330", [sys_lists["screener"].id])
    with pytest.raises(ValueError):
        wls.delete_watchlist(db, sys_lists["screener"].id)
    with pytest.raises(ValueError):
        wls.update_watchlist(db, sys_lists["screener"].id, name="改名")


def test_sync_system_lists_without_crm(db, monkeypatch):
    monkeypatch.setattr(wls, "_crm_codes", lambda stage: None)
    r = wls.sync_system_lists(db, backfill=False)
    assert r["crm_hold"] == {"skipped": "crm unreachable"}
    assert r["screener"]["count"] == 0 and r["alerts_today"]["count"] == 0


def test_sync_system_lists_with_crm(db, monkeypatch):
    monkeypatch.setattr(wls, "_crm_codes", lambda stage: ["2330", "0050"] if stage == "hold" else ["6488"])
    r = wls.sync_system_lists(db, backfill=False)
    assert r["crm_hold"]["count"] == 2 and r["crm_watch"]["count"] == 1
    lists = {w["system_key"]: w for w in wls.list_watchlists(db) if w["system_key"]}
    assert wls.codes_in(db, lists["crm_hold"]["id"]) == {"2330", "0050"}
    assert md.watch_codes(db) == {"2330", "0050", "6488"}


def test_api_round_trip(db):
    with TestClient(app) as c:
        r = c.post("/api/watchlists", json={"name": "金融股", "color": "#123456"})
        assert r.status_code == 201
        lid = r.json()["id"]
        r = c.post("/api/watchlist", json={"code": "2330", "lists": [lid], "note": "test", "backfill": False})
        assert r.status_code == 201 and r.json()["lists"] == [lid] and r.json()["is_new"] is True
        r = c.post("/api/watchlist", json={"code": "2330", "lists": [lid], "backfill": False})
        assert r.status_code == 201 and r.json()["added_to"] == [] and r.json()["is_new"] is False
        assert [x["code"] for x in c.get(f"/api/watchlist?list={lid}").json()] == ["2330"]
        assert c.get("/api/watchlist?list=999999").status_code == 404
        r = c.patch(f"/api/watchlists/{lid}", json={"name": "金融保險"})
        assert r.status_code == 200 and r.json()["name"] == "金融保險"
        r = c.delete(f"/api/watchlist/2330?list={lid}")
        assert r.status_code == 200 and r.json()["unsubscribed"] is True
        assert c.delete(f"/api/watchlist/2330?list={lid}").status_code == 404
        r = c.delete(f"/api/watchlists/{lid}")
        assert r.status_code == 200
        names = {w["name"] for w in c.get("/api/watchlists").json()}
        assert "金融保險" not in names and DEFAULT_LIST_NAME in names
