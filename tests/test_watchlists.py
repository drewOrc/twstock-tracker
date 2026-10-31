"""Multiple watchlists per user: migration from the single-list schema, CRUD, union semantics."""
from datetime import datetime

import pytest
from sqlalchemy import text

from app.db import DEFAULT_LIST_NAME, engine, init_db, session_scope
from app.models import AlertEvent, AlertRule, Stock, User, Watchlist, WatchlistItem
from app.services import market_data as md
from app.services import watchlists as wls


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No exchange calls: stock master lookups come from rows we insert ourselves."""
    monkeypatch.setattr(md, "refresh_stock_list", lambda db: 0)
    monkeypatch.setattr(md.mis, "fetch_quotes", lambda items: [])
    monkeypatch.setattr(md, "backfill_daily", lambda db, code, months=None: 0)


@pytest.fixture
def db(admin_id):
    init_db()
    with session_scope() as s:
        s.query(WatchlistItem).delete()
        s.query(Watchlist).delete()
        s.query(AlertEvent).delete()
        s.query(AlertRule).delete()
        for code, name, market in (("2330", "台積電", "TWSE"), ("6488", "環球晶", "TPEX"), ("0050", "元大台灣50", "TWSE")):
            if not s.get(Stock, code):
                s.add(Stock(code=code, name=name, market=market, updated_at=datetime.now()))
    with session_scope() as s:
        yield s


def test_migration_moves_legacy_rows_into_default_list(db, admin_id):
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS watchlist"))
        conn.execute(text("CREATE TABLE watchlist (id INTEGER PRIMARY KEY, code VARCHAR(12) UNIQUE, note TEXT, tags VARCHAR(128), added_at DATETIME)"))
        conn.execute(text("INSERT INTO watchlist (code, note) VALUES ('2330', '台積電'), ('6488', NULL)"))
    init_db()
    init_db()  # idempotent
    lists = wls.list_watchlists(db, admin_id)
    default = next(w for w in lists if w["name"] == DEFAULT_LIST_NAME)
    assert default["count"] == 2
    assert wls.codes_in(db, default["id"]) == {"2330", "6488"}
    assert {w["system_key"] for w in lists if w["system_key"]} == set(wls.SYSTEM_LISTS)


def test_union_and_last_membership_drops_alert_rules(db, admin_id):
    a = wls.create_watchlist(db, admin_id, "AI 供應鏈")
    b = wls.create_watchlist(db, admin_id, "短線")
    wls.add_code(db, admin_id, "2330", [a.id, b.id], note="雙清單")
    wls.add_code(db, admin_id, "6488", [b.id])
    db.add(AlertRule(user_id=admin_id, code="2330", rule_type="price_above", params={"price": 1}, cooldown_minutes=1))
    db.commit()
    assert md.watch_codes(db) == {"2330", "6488"}
    rows = {r["code"]: r for r in md.watchlist_overview(db, user_id=admin_id)}
    assert sorted(rows["2330"]["lists"]) == sorted([a.id, b.id]) and rows["2330"]["note"] == "雙清單"
    assert [r["code"] for r in md.watchlist_overview(db, a.id)] == ["2330"]

    r = wls.remove_code(db, admin_id, "2330", a.id)
    assert r["lists"] == [b.id] and r["unsubscribed"] is False
    assert db.query(AlertRule).filter_by(code="2330").count() == 1

    r = wls.remove_code(db, admin_id, "2330")  # from every user list of mine
    assert r["unsubscribed"] is True and r["lists"] == []
    assert db.query(AlertRule).filter_by(code="2330").count() == 0
    assert md.watch_codes(db) == {"6488"}


def test_two_users_share_subscription_but_not_lists(db, admin_id):
    other = User(username="kid", password_hash="x", role="member")
    db.add(other)
    db.commit()
    wls.add_code(db, admin_id, "2330")
    r = wls.add_code(db, other.id, "2330")
    assert r["is_new"] is False  # already subscribed by admin -> no second backfill
    assert md.watch_codes(db) == {"2330"}
    assert [x["code"] for x in md.watchlist_overview(db, user_id=other.id)] == ["2330"]
    r = wls.remove_code(db, other.id, "2330")
    assert r["unsubscribed"] is True  # for the kid
    assert md.watch_codes(db) == {"2330"}  # admin still has it
    with pytest.raises(LookupError):
        wls.get_list(db, other.id, wls.ensure_default_list(db, admin_id).id)


def test_system_lists_are_read_only(db, admin_id):
    sys_lists = wls.ensure_system_lists(db, admin_id)
    with pytest.raises(ValueError):
        wls.add_code(db, admin_id, "2330", [sys_lists["screener"].id])
    with pytest.raises(ValueError):
        wls.delete_watchlist(db, admin_id, sys_lists["screener"].id)
    with pytest.raises(ValueError):
        wls.update_watchlist(db, admin_id, sys_lists["screener"].id, name="改名")


def test_sync_system_lists_without_crm(db, admin_id, monkeypatch):
    from app.services import crm_link

    monkeypatch.setattr(crm_link, "crm_get", lambda *a, **k: None)
    r = wls.sync_system_lists(db, backfill=False)
    per = r["users"]["drew"]
    assert per["crm_hold"] == {"skipped": "crm unreachable"}
    assert per["screener"]["count"] == 0 and per["alerts_today"]["count"] == 0


def test_sync_system_lists_with_crm(db, admin_id, monkeypatch):
    def fake_get(path, params=None, user=None, user_id=None):
        stage = (params or {}).get("stage")
        rows = {"hold": ["TW:2330", "TW:0050", "US:NVDA"], "watch": ["TW:6488"]}[stage]
        return [{"id": i, "company_id": c, "stage": stage} for i, c in enumerate(rows, 1)]

    from app.services import crm_link

    monkeypatch.setattr(crm_link, "crm_get", fake_get)
    r = wls.sync_system_lists(db, backfill=False)
    per = r["users"]["drew"]
    assert per["crm_hold"]["count"] == 2 and per["crm_watch"]["count"] == 1
    lists = {w["system_key"]: w for w in wls.list_watchlists(db, admin_id) if w["system_key"]}
    assert wls.codes_in(db, lists["crm_hold"]["id"]) == {"2330", "0050"}
    assert md.watch_codes(db) == {"2330", "0050", "6488"}


def test_api_round_trip(client, db):
    r = client.post("/api/me/watchlists", json={"name": "金融股", "color": "#123456"})
    assert r.status_code == 201
    lid = r.json()["id"]
    r = client.post("/api/me/watchlist", json={"code": "2330", "lists": [lid], "note": "test", "backfill": False})
    assert r.status_code == 201 and r.json()["lists"] == [lid] and r.json()["is_new"] is True
    r = client.post("/api/me/watchlist", json={"code": "2330", "lists": [lid], "backfill": False})
    assert r.status_code == 201 and r.json()["added_to"] == [] and r.json()["is_new"] is False
    assert [x["code"] for x in client.get(f"/api/me/watchlist?list={lid}").json()] == ["2330"]
    assert client.get("/api/me/watchlist?list=999999").status_code == 404
    r = client.patch(f"/api/me/watchlists/{lid}", json={"name": "金融保險"})
    assert r.status_code == 200 and r.json()["name"] == "金融保險"
    r = client.delete(f"/api/me/watchlist/2330?list={lid}")
    assert r.status_code == 200 and r.json()["unsubscribed"] is True
    assert client.delete(f"/api/me/watchlist/2330?list={lid}").status_code == 404
    r = client.delete(f"/api/me/watchlists/{lid}")
    assert r.status_code == 200
    names = {w["name"] for w in client.get("/api/me/watchlists").json()}
    assert "金融保險" not in names and DEFAULT_LIST_NAME in names


def test_multiuser_migration_keeps_items(db, admin_id):
    """v0.3 (per-list, no user_id) -> v0.4: lists get user_id, items must survive the table rebuild."""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM watchlist_items"))
        conn.execute(text("DELETE FROM watchlists"))
    # park the current table as the old shape: recreate watchlists without user_id
    from app.db import _raw_exec

    _raw_exec(
        "PRAGMA foreign_keys=OFF",
        "DROP TABLE watchlists",
        "CREATE TABLE watchlists (id INTEGER PRIMARY KEY, name VARCHAR(64) UNIQUE, color VARCHAR(16), sort_order INTEGER, system_key VARCHAR(32) UNIQUE, created_at DATETIME)",
        "INSERT INTO watchlists (id, name, color, sort_order, system_key) VALUES (11, '我的追蹤', '#4f8cff', 0, NULL), (12, '掃描候選', '#f5c542', 902, 'screener')",
        "INSERT INTO watchlist_items (watchlist_id, code, note, added_at) VALUES (11, '2330', 'keep me', CURRENT_TIMESTAMP), (12, '6488', NULL, CURRENT_TIMESTAMP)",
    )
    init_db()
    lists = {w["name"]: w for w in wls.list_watchlists(db, admin_id)}
    assert lists["我的追蹤"]["id"] == 11 and lists["我的追蹤"]["count"] == 1
    assert lists["掃描候選"]["id"] == 12 and lists["掃描候選"]["count"] == 1
    assert wls.codes_in(db, 11) == {"2330"}
    rows = db.execute(text("SELECT name FROM sqlite_master WHERE name='watchlists_v1'")).all()
    assert rows == []
