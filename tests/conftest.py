"""Test configuration: an isolated SQLite file per test session, no background scheduler, and a
logged-in admin client.

Environment is set before any `app` module is imported so Settings picks the values up.
"""
import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="twstock-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["NOTIFY_CONSOLE"] = "false"
os.environ["ADMIN_USERNAME"] = "drew"
os.environ["ADMIN_PASSWORD"] = "test-pass-123"

ADMIN = ("drew", "test-pass-123")


@pytest.fixture
def admin_id():
    from app.db import init_db, session_scope
    from app.services import auth

    init_db()
    with session_scope() as db:
        return auth.ensure_admin(db).id


@pytest.fixture
def client(admin_id):
    """TestClient logged in as the admin."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"username": ADMIN[0], "password": ADMIN[1]})
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture
def anon():
    """TestClient without a session."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
