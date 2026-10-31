"""Accounts, sessions, namespaces and per-user isolation."""
from app.db import session_scope
from app.models import User
from app.services import auth
from tests.conftest import ADMIN


def test_password_hashing_roundtrip():
    h = auth.hash_password("correct horse")
    assert h.startswith("pbkdf2_sha256$") and auth.verify_password("correct horse", h)
    assert not auth.verify_password("wrong", h) and not auth.verify_password("x", "garbage")


def test_login_logout_me(anon):
    assert anon.get("/api/auth/me").status_code == 401
    assert anon.get("/api/market/jobs").status_code == 401
    assert anon.get("/api/health").status_code == 200  # public
    r = anon.post("/api/auth/login", json={"username": ADMIN[0], "password": "nope"})
    assert r.status_code == 401
    r = anon.post("/api/auth/login", json={"username": ADMIN[0].upper(), "password": ADMIN[1]})
    assert r.status_code == 200 and r.json()["role"] == "admin"
    assert "tw_session" in anon.cookies
    me = anon.get("/api/auth/me").json()
    assert me["username"] == ADMIN[0]
    assert anon.get("/api/market/jobs").status_code == 200
    assert anon.get("/api/jobs").status_code == 200  # legacy path still works
    anon.post("/api/auth/logout")
    assert anon.get("/api/auth/me").status_code == 401


def test_login_lockout(anon, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "login_max_failures", 2)
    auth._failures.clear()
    for _ in range(2):
        anon.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    r = anon.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert r.status_code == 429
    auth._failures.clear()


def test_admin_user_management_and_member_scope(client, admin_id):
    r = client.post("/api/admin/users", json={"username": "mom", "password": "momsecret1", "display_name": "媽媽"})
    assert r.status_code == 201 and r.json()["role"] == "member"
    mom_id = r.json()["id"]
    assert client.post("/api/admin/users", json={"username": "mom", "password": "momsecret1"}).status_code == 400
    assert client.post("/api/admin/users", json={"username": "bad name", "password": "momsecret1"}).status_code == 400
    assert client.patch(f"/api/admin/users/{admin_id}", json={"role": "member"}).status_code == 400  # not yourself

    # members cannot reach admin endpoints; their personal data is isolated
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as mom:
        assert mom.post("/api/auth/login", json={"username": "mom", "password": "momsecret1"}).status_code == 200
        assert mom.post("/api/admin/jobs/full_daily/run").status_code == 403
        assert mom.get("/api/admin/users").status_code == 403
        lists = mom.get("/api/me/watchlists").json()
        names = {w["name"] for w in lists}
        assert "我的追蹤" in names and "CRM 持有" in names
        mom_default = next(w for w in lists if not w["system_key"])
        admin_lists = client.get("/api/me/watchlists").json()
        assert all(w["id"] != mom_default["id"] for w in admin_lists)  # separate per user
        # mom cannot touch admin's list
        admin_default = next(w for w in admin_lists if not w["system_key"])
        assert mom.patch(f"/api/me/watchlists/{admin_default['id']}", json={"name": "hijack"}).status_code == 404
        # password change logs mom out of that session
        r = mom.post("/api/auth/password", json={"current_password": "momsecret1", "new_password": "momsecret2"})
        assert r.status_code == 200
        assert mom.get("/api/auth/me").status_code == 401

    r = client.patch(f"/api/admin/users/{mom_id}", json={"disabled": True})
    assert r.status_code == 200 and r.json()["disabled"] is True
    with session_scope() as db:
        assert db.get(User, mom_id).disabled is True


def test_crm_proxy_carries_identity(client, admin_id, monkeypatch):
    import httpx

    from app.api import crm_proxy
    from app.config import settings

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        return httpx.Response(200, json=[])

    monkeypatch.setattr(crm_proxy, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://crm"))
    monkeypatch.setattr(settings, "crm_facade_token", "sekret")
    assert client.get("/api/crm/positions").status_code == 200
    assert seen["x-user-id"] == str(admin_id) and seen["x-user-name"] == ADMIN[0] and seen["x-facade-token"] == "sekret"
    assert "cookie" not in seen
