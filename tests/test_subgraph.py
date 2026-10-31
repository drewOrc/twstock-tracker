"""Subgraph endpoint: seeds, hops, holding edges on/off."""
import pytest

from app.db import init_db, session_scope
from app.models import Company, CompanyBrief, Edge, EdgeWeight, FinancialYTD, MetricActual
from app.services import knowledge as kn


@pytest.fixture
def db(admin_id):
    init_db()
    with session_scope() as s:
        for model in (EdgeWeight, Edge, CompanyBrief, FinancialYTD, MetricActual, Company):
            s.query(model).delete()
    with session_scope() as s:
        for cid, name in (("US:NVDA", "輝達"), ("TW:2330", "台積電"), ("TW:3017", "奇鋐"), ("TW:2382", "廣達"), ("US:AMAT", "應用材料"), ("TW:0050", "元大台灣50")):
            kn.upsert_company(s, {"id": cid, "name": name, "sector": "ETF" if cid == "TW:0050" else None})
        kn.upsert_edge(s, {"customer_id": "US:NVDA", "supplier_id": "TW:2330", "revenue_share": 0.15})
        kn.upsert_edge(s, {"customer_id": "US:NVDA", "supplier_id": "TW:3017"})
        kn.upsert_edge(s, {"customer_id": "TW:2382", "supplier_id": "TW:3017"})
        kn.upsert_edge(s, {"customer_id": "TW:2330", "supplier_id": "US:AMAT", "revenue_share": 0.2})
        kn.upsert_edge(s, {"customer_id": "TW:2330", "supplier_id": "TW:0050", "relation": "holding", "revenue_share": 0.56})
        yield s


def test_subgraph_hops_and_holding(db):
    g0 = kn.subgraph(db, ["TW:3017"], depth=0)
    assert [n["id"] for n in g0["nodes"]] == ["TW:3017"] and g0["edges"] == []
    g1 = kn.subgraph(db, ["TW:3017"], depth=1)
    assert {n["id"] for n in g1["nodes"]} == {"TW:3017", "US:NVDA", "TW:2382"} and len(g1["edges"]) == 2
    assert g1["nodes"][0]["seed"] is True and g1["nodes"][0]["id"] == "TW:3017"
    g2 = kn.subgraph(db, ["TW:3017"], depth=2)
    assert {n["id"] for n in g2["nodes"]} == {"TW:3017", "US:NVDA", "TW:2382", "TW:2330"}  # holding edge to 0050 excluded
    assert "TW:0050" in {n["id"] for n in kn.subgraph(db, ["TW:2330"], depth=1, include_holding=True)["nodes"]}
    assert "TW:0050" not in {n["id"] for n in kn.subgraph(db, ["TW:2330"], depth=1)["nodes"]}
    g_all = kn.subgraph(db, None)
    assert len(g_all["edges"]) == 4 and g_all["seeds"] == []
    # several seeds: edges among them plus their neighbours
    g = kn.subgraph(db, ["tw:2330", "TW:2382"], depth=1)
    assert {n["id"] for n in g["nodes"]} == {"TW:2330", "TW:2382", "US:NVDA", "US:AMAT", "TW:3017"} and len(g["edges"]) == 4


def test_graph_endpoint(client, db):
    r = client.get("/api/market/knowledge/graph?ids=TW:3017,TW:2330&depth=1&holding=true")
    assert r.status_code == 200
    d = r.json()
    assert d["seeds"] == ["TW:2330", "TW:3017"] and d["include_holding"] is True
    assert any(e["relation"] == "holding" for e in d["edges"]) and d["edges"][0]["customer_name"]
    assert client.get("/api/market/knowledge/graph?depth=9").status_code == 422
    assert len(client.get("/api/market/knowledge/graph").json()["edges"]) == 4
