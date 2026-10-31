"""Automatic knowledge growth: node sync from the master list, revenue highlights, todo, seed proposals."""
from datetime import datetime

import pytest

from app.db import init_db, session_scope
from app.models import (
    Company,
    CompanyBrief,
    Edge,
    EdgeWeight,
    FinancialYTD,
    KnowledgeProposal,
    MetricActual,
    Stock,
    Watchlist,
    WatchlistItem,
)
from app.services import knowledge as kn
from app.services import knowledge_jobs as kj
from app.services import knowledge_proposals as kp


@pytest.fixture
def db(admin_id):
    init_db()
    with session_scope() as s:
        for model in (KnowledgeProposal, EdgeWeight, Edge, CompanyBrief, FinancialYTD, MetricActual, Company):
            s.query(model).delete()
        s.query(WatchlistItem).delete()
        for code, name, industry in (("2330", "台積電", "24"), ("0050", "元大台灣50", None), ("2882", "國泰金", "17")):
            if not s.get(Stock, code):
                s.add(Stock(code=code, name=name, market="TWSE", industry=industry, updated_at=datetime.now()))
    with session_scope() as s:
        yield s


def test_sync_companies_from_tracked_codes(db, admin_id):
    lid = db.query(Watchlist).filter_by(user_id=admin_id, system_key=None).first() or None
    if lid is None:
        from app.services import watchlists as wls

        lid = wls.ensure_default_list(db, admin_id)
    db.add(WatchlistItem(watchlist_id=lid.id, code="2330"))
    db.add(WatchlistItem(watchlist_id=lid.id, code="0050"))
    db.commit()
    r = kj.sync_companies(db)
    assert set(r["created"]) == {"TW:2330", "TW:0050"}
    assert db.get(Company, "TW:0050").sector == "ETF" and db.get(Company, "TW:2330").sector  # sector from the industry table
    assert kj.sync_companies(db)["created"] == []  # idempotent
    assert kj.sync_companies(db, {"2882"})["created"] == ["TW:2882"]


def test_revenue_highlights_once_per_month(db):
    kn.upsert_company(db, {"id": "TW:2330", "name": "台積電"})
    for period, v in (("2026-09", 511857399), ("2026-08", 514805337), ("2025-09", 330980920)):
        kn.upsert_metric(db, {"company_id": "TW:2330", "metric": "revenue_m", "period": period, "value": v, "source": "https://openapi.twse.com.tw/x", "created_by": "system:mops"})
    r = kj.revenue_highlights(db)
    assert r["period"] == "2026-09" and r["written"] == ["TW:2330"]
    b = kn.latest_briefs(db, "TW:2330")["highlights"]
    assert b["date"] == "2026-09-30" and "年增 +54.6%" in b["content"] and "月增 -0.6%" in b["content"] and b["created_by"] == "system:mops"
    assert kj.revenue_highlights(db)["written"] == []  # not twice
    todo = kj.todo(db)
    assert [x["id"] for x in todo["missing_profile"]] == ["TW:2330"] and todo["stale_highlights"] == [] and todo["isolated_companies"][0]["id"] == "TW:2330"


def test_propose_seed_queues_everything_and_edges_carry_their_companies(db, admin_id):
    from app.models import User

    spec = {
        "created_by": "agent:claude", "default_source": "年報整理",
        "companies": [{"id": "US:NVDA", "name": "輝達"}],
        "profiles": [{"company_id": "TW:2330", "content": "晶圓代工龍頭"}],
        "edges": [{"customer_id": "US:NVDA", "supplier_id": "TW:2330", "revenue_share": 0.15, "confidence": "medium", "source": "台積電年報"}],
    }
    kn.upsert_company(db, {"id": "TW:2330", "name": "台積電"})
    assert kp.propose_seed(db, spec) == {"company": 1, "brief": 1, "edge": 1}
    edge = next(r for r in kp.list_proposals(db, "pending", "edge") if r["kind"] == "edge")
    assert edge["payload"]["companies"][0]["id"] == "US:NVDA" and edge["created_by"] == "agent:claude"
    assert kp.propose_seed(db, spec) == {"company": 1, "brief": 1, "edge": 1}  # re-running updates, no duplicates
    assert kp.counts(db) == {"pending": 3}
    admin = db.get(User, admin_id)
    r = kp.decide(db, edge["id"], True, admin)
    assert r.status == "approved" and db.get(Company, "US:NVDA").name == "輝達"
    assert kn.list_edges(db, "TW:2330")[0]["source"] == "台積電年報"
