"""Agent keys: issued once, hashed, scoped, rate limited, never admin; proposals stamped agent:<name>."""
import pytest

from app.db import init_db, session_scope
from app.models import AgentKey, Company, CompanyBrief, Edge, EdgeWeight, FinancialYTD, KnowledgeProposal, MetricActual
from app.services import agents
from app.services import knowledge as kn


@pytest.fixture
def db(admin_id):
    init_db()
    agents.reset_limits()
    with session_scope() as s:
        for model in (AgentKey, KnowledgeProposal, EdgeWeight, Edge, CompanyBrief, FinancialYTD, MetricActual, Company):
            s.query(model).delete()
    with session_scope() as s:
        kn.upsert_company(s, {"id": "TW:2330", "name": "台積電"})
        yield s


def _issue(client, **over):
    body = {"name": "grok", "scopes": ["market:read", "knowledge:propose"], "rate_per_minute": 60} | over
    r = client.post("/api/admin/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["key"], r.json()["agent"]


def test_issue_and_use_key(client, anon, db):
    key, agent = _issue(client)
    assert key.startswith("twa_") and agent["prefix"] == key[:10] and agent["acting_username"] == "drew"
    assert "key" not in client.get("/api/admin/agents").json()[0]  # secrets never listed
    h = {"Authorization": f"Bearer {key}"}
    assert anon.get("/api/market/knowledge/stats").status_code == 401
    assert anon.get("/api/market/knowledge/stats", headers=h).status_code == 200
    assert anon.get("/api/market/knowledge/companies/TW:2330", headers={"X-Agent-Key": key}).status_code == 200
    assert anon.get("/api/auth/me", headers=h).json()["username"] == "drew"
    # scopes: no personal read, never admin, no direct knowledge writes even though acting user is the admin
    assert anon.get("/api/me/watchlists", headers=h).status_code == 403
    assert anon.get("/api/admin/users", headers=h).status_code == 403
    assert anon.get("/api/admin/agents", headers=h).status_code == 403
    assert anon.post("/api/market/knowledge/briefs", headers=h, json={"company_id": "TW:2330", "kind": "profile", "content": "x"}).status_code == 403
    assert anon.post("/api/market/knowledge/proposals/decide", headers=h, json={"ids": [1], "approve": True}).status_code == 403
    # proposals are allowed and stamped with the agent's name whatever it claims
    r = anon.post("/api/market/knowledge/proposals", headers=h, json={"kind": "brief", "payload": {"company_id": "TW:2330", "kind": "profile", "content": "晶圓代工"}, "created_by": "system:mops"})
    assert r.status_code == 201 and r.json()["created_by"] == "agent:grok" and r.json()["user_id"] == agent["acting_user_id"]
    r = anon.post("/api/market/knowledge/proposals/batch", headers=h, json=[{"kind": "company", "payload": {"id": "US:NVDA", "name": "輝達"}}])
    assert r.status_code == 201 and r.json()[0]["created_by"] == "agent:grok"
    assert anon.get("/api/market/knowledge/proposals?status=pending", headers=h).json()[0]["created_by"] == "agent:grok"
    # bad / rotated / disabled keys
    assert anon.get("/api/market/knowledge/stats", headers={"Authorization": "Bearer twa_nope"}).status_code == 401
    r = client.post(f"/api/admin/agents/{agent['id']}/rotate")
    new_key = r.json()["key"]
    assert anon.get("/api/market/knowledge/stats", headers=h).status_code == 401
    assert anon.get("/api/market/knowledge/stats", headers={"Authorization": f"Bearer {new_key}"}).status_code == 200
    assert client.patch(f"/api/admin/agents/{agent['id']}", json={"disabled": True}).json()["disabled"] is True
    assert anon.get("/api/market/knowledge/stats", headers={"Authorization": f"Bearer {new_key}"}).status_code == 401
    assert client.patch(f"/api/admin/agents/{agent['id']}", json={"disabled": False, "scopes": ["market:read", "personal:read"]}).status_code == 200
    assert anon.get("/api/me/watchlists", headers={"Authorization": f"Bearer {new_key}"}).status_code == 200
    assert anon.post("/api/market/knowledge/proposals", headers={"Authorization": f"Bearer {new_key}"}, json={"kind": "company", "payload": {"id": "US:AMD"}}).status_code == 403
    assert client.patch(f"/api/admin/agents/{agent['id']}", json={"scopes": ["root"]}).status_code == 400
    assert client.post("/api/admin/agents", json={"name": "grok", "scopes": ["market:read"]}).status_code == 400  # duplicate name
    assert client.delete(f"/api/admin/agents/{agent['id']}").status_code == 200
    assert client.get("/api/admin/agents").json() == []


def test_rate_limit_and_last_used(client, anon, db):
    key, agent = _issue(client, name="burst", rate_per_minute=3)
    h = {"Authorization": f"Bearer {key}"}
    codes = [anon.get("/api/market/knowledge/stats", headers=h).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert client.get("/api/admin/agents").json()[0]["last_used_at"] is not None


def test_tasks_bundle_material(client, anon, db, monkeypatch):
    from app.services import stock_summary

    monkeypatch.setattr(stock_summary, "fetch_news", lambda name, limit=10: ([{"title": "台積電法說", "link": "https://x", "published": None, "source": "test"}], None))
    key, _ = _issue(client, name="reader", scopes=["market:read"])
    r = anon.get("/api/market/knowledge/tasks?limit=3", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200, r.text
    t = r.json()[0]
    assert t["company_id"] == "TW:2330" and "profile" in t["needs"] and "edges" in t["needs"]
    assert t["material"]["company"]["name"] == "台積電" and "known_edges" in t["material"]
    assert t["answer_with"]["endpoint"].endswith("/proposals/batch")
    assert anon.get("/api/market/knowledge/tasks?company=TW:2330&news=false", headers={"Authorization": f"Bearer {key}"}).json()[0]["needs"] == ["requested"]
    assert anon.get("/api/market/knowledge/tasks?company=TW:0000", headers={"Authorization": f"Bearer {key}"}).status_code == 404
