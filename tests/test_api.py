"""API-level tests with FastAPI's TestClient (no network, no scheduler)."""
import os

os.environ.setdefault("SCHEDULER_ENABLED", "false")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api import crm_proxy  # noqa: E402
from app.main import app  # noqa: E402


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


def test_crm_proxy_forwards_method_query_and_body(mock_crm):
    with TestClient(app) as c:
        r = c.post("/api/crm/positions?stage=hold&tier=core", json={"a": 1})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "path": "/api/positions"}
    assert mock_crm["method"] == "POST"
    assert mock_crm["url"] == "http://crm/api/positions?stage=hold&tier=core"
    assert b'"a"' in mock_crm["body"]


def test_crm_proxy_reports_unreachable_backend(mock_crm):
    with TestClient(app) as c:
        r = c.get("/api/crm/boom")
    assert r.status_code == 502
    assert "unreachable" in r.json()["detail"]


def test_health_includes_crm_probe(mock_crm):
    with TestClient(app) as c:
        r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["crm"]["reachable"] is True


def test_spa_fallback_and_api_404():
    with TestClient(app) as c:
        assert c.get("/").status_code == 200
        assert c.get("/board").status_code == 200  # client-side route -> index.html
        assert c.get("/api/does-not-exist").status_code == 404
        assert c.get("/legacy/").status_code == 200


def test_quotes_codes_filter_hits_watchlist_cache(monkeypatch):
    from app.services import market_data as md

    monkeypatch.setattr(md.mis, "fetch_quotes", lambda items: [])
    with TestClient(app) as c:
        r = c.get("/api/quotes?codes=2330,ZZZZ")
    assert r.status_code == 200
    assert all(q["code"] in {"2330"} for q in r.json())


def test_institutional_days_alias():
    with TestClient(app) as c:
        r = c.get("/api/stocks/2330/institutional?days=3")
    assert r.status_code == 200 and len(r.json()) <= 3
