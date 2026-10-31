"""Shared knowledge layer: writes are admin-only, reads for everyone, import from the CRM file,
adoption of the legacy per-project database."""
import sqlite3

import pytest

from app.db import adopt_legacy_database, init_db, session_scope
from app.models import Company, CompanyBrief, Edge, EdgeWeight, FinancialYTD, MetricActual, SchemaRegistry
from app.services import knowledge as kn


@pytest.fixture
def db(admin_id):
    init_db()
    with session_scope() as s:
        for model in (EdgeWeight, Edge, CompanyBrief, FinancialYTD, MetricActual, Company):
            s.query(model).delete()
    with session_scope() as s:
        yield s


def test_registry_lists_engine_tables(db):
    rows = {r.table_name: r for r in db.query(SchemaRegistry)}
    assert rows["knowledge_companies"].layer == "knowledge" and rows["knowledge_companies"].owner == "engine"
    assert rows["watchlists"].layer == "personal" and rows["users"].layer == "auth"


def test_graph_round_trip(db):
    kn.upsert_company(db, {"id": "tw:2330", "name": "台積電", "sector": "晶圓代工"})
    kn.upsert_company(db, {"id": "US:NVDA", "name": "輝達"})
    e = kn.upsert_edge(db, {"customer_id": "US:NVDA", "supplier_id": "TW:2330", "revenue_share": 0.12, "date": "2026-06-30", "source": "annual report"})
    assert e.revenue_share == 0.12 and kn.edge_weights(db, e.id)[0]["date"] == "2026-06-30"
    # an older weight does not overwrite the latest value on the edge; a newer one does
    kn.add_edge_weight(db, e.id, {"date": "2025-12-31", "revenue_share": 0.10})
    assert db.get(Edge, e.id).revenue_share == 0.12
    kn.add_edge_weight(db, e.id, {"date": "2026-09-30", "revenue_share": 0.15})
    assert db.get(Edge, e.id).revenue_share == 0.15
    kn.add_brief(db, {"company_id": "TW:2330", "kind": "profile", "content": "晶圓代工龍頭", "created_by": "agent:claude"})
    kn.add_brief(db, {"company_id": "TW:2330", "kind": "highlights", "date": "2026-10-01", "content": "舊"})
    kn.add_brief(db, {"company_id": "TW:2330", "kind": "highlights", "date": "2026-10-20", "content": "新"})
    c = kn.get_company(db, "TW:2330")
    assert c["briefs"]["highlights"]["content"] == "新" and c["briefs"]["profile"]["created_by"] == "agent:claude"
    assert c["edges"]["customers"][0]["customer_name"] == "輝達"
    ctx = kn.for_stock(db, "2330")
    assert ctx["customers"][0] == {"id": "US:NVDA", "name": "輝達", "revenue_share": 0.15, "relation": "customer"}
    assert kn.for_stock(db, "9999") is None
    with pytest.raises(ValueError):
        kn.upsert_edge(db, {"customer_id": "US:NVDA", "supplier_id": "TW:2330", "relation": "friend"})
    with pytest.raises(LookupError):
        kn.add_brief(db, {"company_id": "TW:0000", "kind": "profile", "content": "x"})


def test_api_writes_need_admin(client, anon, db):
    r = client.put("/api/market/knowledge/companies/TW:2330", json={"name": "台積電"})
    assert r.status_code == 200 and r.json()["created_by"] == "user:drew"
    r = client.put("/api/market/knowledge/companies/US:AAPL", json={"name": "蘋果", "created_by": "agent:claude", "confidence": "high"})
    assert r.status_code == 200 and r.json()["created_by"] == "agent:claude"
    r = client.post("/api/market/knowledge/edges", json={"customer_id": "US:AAPL", "supplier_id": "TW:2330", "revenue_share": 0.25, "date": "2026-06-30"})
    assert r.status_code == 201 and r.json()["id"]
    edge_id = r.json()["id"]
    r = client.post(f"/api/market/knowledge/edges/{edge_id}/weights", json={"date": "2026-09-30", "revenue_share": 0.3})
    assert r.status_code == 201
    r = client.post("/api/market/knowledge/briefs", json={"company_id": "TW:2330", "kind": "profile", "content": "晶圓代工"})
    assert r.status_code == 201 and r.json()["id"]
    r = client.post("/api/market/knowledge/metrics/batch", json=[
        {"company_id": "TW:2330", "metric": "revenue_m", "period": "2026-09", "value": 511857399, "source": "mops", "created_by": "system:mops"},
        {"company_id": "TW:2330", "metric": "revenue_m", "period": "2026-08", "value": 514805337, "source": "mops", "created_by": "system:mops"},
    ])
    assert r.status_code == 200 and len(r.json()) == 2
    r = client.post("/api/market/knowledge/financials", json={"company_id": "TW:2330", "year": 2026, "quarter": 2, "revenue": 100, "eps": 1.5})
    assert r.status_code == 200
    assert client.post("/api/market/knowledge/metrics", json={"company_id": "TW:2330", "metric": "nope", "period": "2026", "value": 1}).status_code == 400
    assert client.post("/api/market/knowledge/edges", json={"customer_id": "US:MSFT", "supplier_id": "TW:2330"}).status_code == 404

    # a member reads everything but cannot write
    assert client.post("/api/admin/users", json={"username": "kidkn", "password": "kid-pass-123"}).status_code in (200, 201)
    assert anon.post("/api/auth/login", json={"username": "kidkn", "password": "kid-pass-123"}).status_code == 200
    c = anon.get("/api/market/knowledge/companies/TW:2330").json()
    assert c["edges"]["customers"][0]["revenue_share"] == 0.3 and len(c["metrics"]) == 2 and c["financials"][0]["eps"] == 1.5
    assert anon.get("/api/market/knowledge/companies?q=蘋").json()[0]["id"] == "US:AAPL"
    assert anon.get("/api/market/knowledge/edges?company=TW:2330").json()[0]["customer_name"] == "蘋果"
    assert anon.put("/api/market/knowledge/companies/TW:2330", json={"name": "x"}).status_code == 403
    assert anon.post("/api/market/knowledge/briefs", json={"company_id": "TW:2330", "kind": "profile", "content": "x"}).status_code == 403
    assert anon.delete(f"/api/market/knowledge/edges/{edge_id}").status_code == 403
    assert client.delete(f"/api/market/knowledge/edges/{edge_id}").status_code == 200
    assert anon.get("/api/market/knowledge/stats").json()["edges"] == 0
    summary_ctx = anon.get("/api/market/knowledge/companies/TW:2330").json()
    assert summary_ctx["briefs"]["profile"]["content"] == "晶圓代工"


def test_import_from_crm_file(db, tmp_path):
    src = tmp_path / "stockcrm.db"
    c = sqlite3.connect(src)
    c.executescript(
        """
        CREATE TABLE companies (id TEXT PRIMARY KEY, market TEXT, ticker TEXT, name TEXT, name_en TEXT, sector TEXT, notes TEXT, created_at TEXT);
        CREATE TABLE edges (id INTEGER PRIMARY KEY, customer_id TEXT, supplier_id TEXT, revenue_share REAL, lag_days INTEGER, confidence TEXT, relation TEXT, source TEXT, notes TEXT, created_by TEXT, created_at TEXT);
        CREATE TABLE company_briefs (id INTEGER PRIMARY KEY, company_id TEXT, date TEXT, kind TEXT, content TEXT, sources TEXT, created_by TEXT, created_at TEXT);
        CREATE TABLE financials_ytd (id INTEGER PRIMARY KEY, company_id TEXT, year INTEGER, quarter INTEGER, revenue REAL, gross_profit REAL, opex REAL, net_income REAL, eps REAL, source TEXT, fetched_at TEXT);
        CREATE TABLE metrics (id INTEGER PRIMARY KEY, company_id TEXT, metric TEXT, period TEXT, kind TEXT, value REAL, source TEXT, created_by TEXT, created_at TEXT);
        INSERT INTO companies VALUES ('TW:2330','TW','2330','台積電','TSMC','晶圓代工',NULL,'2026-10-01 08:00:00'), ('US:NVDA','US','NVDA','輝達',NULL,NULL,NULL,'2026-10-01 08:00:00');
        INSERT INTO edges VALUES (7,'US:NVDA','TW:2330',0.11,60,'high','customer','10-K',NULL,'user','2026-10-02 09:00:00');
        INSERT INTO company_briefs VALUES (3,'TW:2330','2026-10-20','profile','晶圓代工龍頭','[{"title":"官網","url":"https://x"}]','agent:claude','2026-10-20 10:00:00');
        INSERT INTO financials_ytd VALUES (1,'TW:2330',2026,2,2404483690,1611606116,192987740,1279041690,49.33,'twse','2026-08-15 00:00:00');
        INSERT INTO metrics VALUES (1,'TW:2330','revenue_m','2026-09','actual',511857399,'twse','system:mops','2026-10-10 00:00:00'), (2,'TW:2330','revenue_q','2027Q1','model',1,NULL,'user','2026-10-10 00:00:00');
        """
    )
    c.commit()
    c.close()
    counts = kn.import_from_crm(db, src)
    assert counts == {"companies": 2, "edges": 1, "briefs": 1, "financials": 1, "metrics": 1}
    assert kn.import_from_crm(db, src)["edges"] == 1  # idempotent
    e = db.get(Edge, 7)
    assert e.customer_id == "US:NVDA" and e.lag_days == 60 and e.created_at.year == 2026
    b = db.get(CompanyBrief, 3)
    assert b.sources[0]["title"] == "官網" and b.date.isoformat() == "2026-10-20"
    assert kn.list_metrics(db, "TW:2330") and all(m["created_by"] == "system:mops" for m in kn.list_metrics(db, "TW:2330"))
    assert kn.stats(db)["financials"] == 1


def test_adopt_legacy_database_only_into_a_new_market_db(tmp_path):
    legacy = tmp_path / "data" / "twstock.db"
    legacy.parent.mkdir()
    c = sqlite3.connect(legacy)
    c.execute("CREATE TABLE t (x)")
    c.execute("INSERT INTO t VALUES (42)")
    c.commit()
    c.close()
    target = tmp_path / "shared" / "market.db"
    assert adopt_legacy_database(target, legacy) is True
    assert sqlite3.connect(target).execute("SELECT x FROM t").fetchone()[0] == 42
    assert (legacy.parent / "MOVED_TO_market.db.txt").exists()
    assert adopt_legacy_database(target, legacy) is False  # never overwrite an existing file
    assert adopt_legacy_database(tmp_path / "other.db", legacy) is False  # only the shared file name
    assert adopt_legacy_database(None, legacy) is False
