"""API-level tests: CRM proxy, SPA fallback, quote filter (logged in as admin via conftest)."""
import httpx
import pytest

from app.api import crm_proxy


@pytest.fixture
def mock_crm(monkeypatch):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = request.content
        if request.url.path.endswith("/boom"):
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={"ok": True, "path": request.url.path})

    monkeypatch.setattr(
        crm_proxy, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://crm")
    )
    return seen


def test_crm_proxy_forwards_method_query_and_body(client, mock_crm):
    r = client.post("/api/crm/positions?stage=hold&tier=core", json={"a": 1})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "path": "/api/positions"}
    assert mock_crm["method"] == "POST"
    assert mock_crm["url"] == "http://crm/api/positions?stage=hold&tier=core"
    assert b'"a"' in mock_crm["body"]


def test_crm_proxy_requires_login(anon, mock_crm):
    assert anon.get("/api/crm/positions").status_code == 401


def test_crm_proxy_reports_unreachable_backend(client, mock_crm):
    r = client.get("/api/crm/boom")
    assert r.status_code == 502
    assert "unreachable" in r.json()["detail"]


def test_health_includes_crm_probe(anon, mock_crm):
    r = anon.get("/api/health")
    assert r.status_code == 200
    assert r.json()["crm"]["reachable"] is True


def test_spa_fallback_and_api_404(anon):
    assert anon.get("/").status_code == 200
    assert anon.get("/board").status_code == 200  # client-side route -> index.html
    assert anon.get("/api/does-not-exist").status_code == 404
    assert anon.get("/legacy/").status_code == 200


def test_quotes_codes_filter_hits_watchlist_cache(client, monkeypatch):
    from app.services import market_data as md

    monkeypatch.setattr(md.mis, "fetch_quotes", lambda items: [])
    r = client.get("/api/market/quotes?codes=2330,ZZZZ")
    assert r.status_code == 200
    assert all(q["code"] in {"2330"} for q in r.json())


def test_institutional_days_alias(client):
    r = client.get("/api/market/stocks/2330/institutional?days=3")
    assert r.status_code == 200 and len(r.json()) <= 3
