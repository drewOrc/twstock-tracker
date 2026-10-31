"""Knowledge review queue: anyone proposes, admins decide, approval applies through services.knowledge."""
import pytest

from app.db import init_db, session_scope
from app.models import Company, CompanyBrief, Edge, EdgeWeight, FinancialYTD, KnowledgeProposal, MetricActual
from app.services import knowledge as kn
from app.services import knowledge_proposals as kp


@pytest.fixture
def db(admin_id):
    init_db()
    with session_scope() as s:
        for model in (KnowledgeProposal, EdgeWeight, Edge, CompanyBrief, FinancialYTD, MetricActual, Company):
            s.query(model).delete()
    with session_scope() as s:
        yield s


def test_propose_dedupes_pending_and_apply_creates_companies(db, admin_id):
    from app.models import User

    admin = db.get(User, admin_id)
    p1 = kp.propose(db, {"kind": "edge", "payload": {"customer_id": "US:NVDA", "supplier_id": "TW:2330", "revenue_share": 0.1,
                                                      "companies": [{"id": "US:NVDA", "name": "輝達"}, {"id": "TW:2330", "name": "台積電"}]},
                         "rationale": "10-K 主要客戶", "confidence": "high", "created_by": "agent:claude"})
    p2 = kp.propose(db, {"kind": "edge", "payload": {"customer_id": "us:nvda", "supplier_id": "tw:2330", "revenue_share": 0.12}, "created_by": "agent:claude"})
    assert p1.id == p2.id and p2.payload["revenue_share"] == 0.12  # same pending key -> updated, not duplicated
    assert p1.company_ids == ["TW:2330", "US:NVDA"] and "客戶" in p1.summary
    assert kp.counts(db) == {"pending": 1}
    with pytest.raises(ValueError):
        kp.propose(db, {"kind": "nope", "payload": {"x": 1}})

    r = kp.decide(db, p1.id, True, admin)
    assert r.status == "approved" and r.applied_ref.startswith("knowledge_edges:")
    assert db.get(Company, "US:NVDA").name == "輝達" and db.get(Company, "TW:2330").created_by == "agent:claude"
    e = kn.list_edges(db, "TW:2330")[0]
    assert e["revenue_share"] == 0.12 and e["created_by"] == "agent:claude"
    with pytest.raises(ValueError):
        kp.decide(db, p1.id, True, admin)  # already decided

    # a proposal that cannot apply is marked failed with the reason, not raised
    bad = kp.propose(db, {"kind": "brief", "payload": {"company_id": "TW:0000", "kind": "profile", "content": "x"}})
    r = kp.decide(db, bad.id, True, admin)
    assert r.status == "failed" and "LookupError" in r.note
    rej = kp.propose(db, {"kind": "company", "payload": {"id": "US:AAPL", "name": "蘋果"}})
    assert kp.decide(db, rej.id, False, admin, "不需要").status == "rejected"
    assert db.get(Company, "US:AAPL") is None
    assert ("US:NVDA", "TW:2330") in kp.pending_edge_pairs(db)


def test_api_members_propose_admins_decide(client, anon, db):
    assert client.post("/api/admin/users", json={"username": "kidkp", "password": "kid-pass-123"}).status_code in (200, 201)
    assert anon.post("/api/auth/login", json={"username": "kidkp", "password": "kid-pass-123"}).status_code == 200
    r = anon.post("/api/market/knowledge/proposals", json={"kind": "company", "payload": {"id": "TW:2454", "name": "聯發科", "sector": "IC 設計"}, "rationale": "常用", "created_by": "system:fake"})
    assert r.status_code == 201 and r.json()["created_by"] == "user:kidkp"  # members cannot pose as a system
    pid = r.json()["id"]
    r = anon.post("/api/market/knowledge/proposals/batch", json=[
        {"kind": "company", "payload": {"id": "US:AAPL", "name": "蘋果"}},
        {"kind": "edge", "payload": {"customer_id": "US:AAPL", "supplier_id": "TW:2454", "relation": "customer"}, "confidence": "low"},
    ])
    assert r.status_code == 201 and len(r.json()) == 2
    ids = [pid] + [x["id"] for x in r.json()]
    assert anon.post(f"/api/market/knowledge/proposals/{pid}/decide", json={"approve": True}).status_code == 403
    assert len(anon.get("/api/market/knowledge/proposals").json()) == 3
    assert [x["id"] for x in anon.get("/api/market/knowledge/proposals?company=TW:2454").json()] == sorted([pid, ids[2]], reverse=True)
    r = client.post("/api/market/knowledge/proposals/decide", json={"ids": ids, "approve": True})
    assert r.status_code == 200 and r.json()["approved"] == 3, r.json()
    assert client.get("/api/market/knowledge/companies/TW:2454").json()["edges"]["customers"][0]["customer_id"] == "US:AAPL"
    assert anon.get("/api/market/knowledge/proposals/counts").json() == {"approved": 3}
    assert client.get("/api/market/knowledge/proposals?status=approved&kind=edge").json()[0]["applied_ref"].startswith("knowledge_edges:")
