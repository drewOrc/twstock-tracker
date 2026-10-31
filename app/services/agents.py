"""Agent keys: scoped API credentials for external agents (a Grok bot, a Claude session, a script).

A key is `twa_` + 40 random characters, shown once; only its SHA-256 lands in the database. Each key
acts as one user (acting_user_id) and carries scopes:

  market:read        GET under /api/market  (shared knowledge: prices, graph, briefs, todo, tasks)
  knowledge:propose  POST /api/market/knowledge/proposals[/batch]  (never direct knowledge writes)
  personal:read      GET under /api/me  (the acting user's lists, alerts)

Admin routes are closed to agent keys whatever the acting user's role. A sliding one-minute window per
key enforces rate_per_minute (per process).
"""
from __future__ import annotations

import hashlib
import secrets
import time
from collections import deque
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AgentKey, User

PREFIX = "twa_"
SCOPES: dict[str, str] = {
    "market:read": "讀通用層（行情、知識圖、簡介、待補、任務）",
    "knowledge:propose": "對知識層提案（不能直接寫入）",
    "personal:read": "讀代表使用者的個人資料（清單、警示）",
}
_hits: dict[int, deque] = {}
_touched: dict[int, float] = {}


def generate() -> tuple[str, str, str]:
    raw = PREFIX + secrets.token_urlsafe(30)[:40]
    return raw, raw[: len(PREFIX) + 6], hash_key(raw)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_scopes(scopes: list[str]) -> list[str]:
    bad = [s for s in scopes if s not in SCOPES]
    if bad:
        raise ValueError(f"unknown scope(s): {', '.join(bad)}; valid: {', '.join(SCOPES)}")
    if not scopes:
        raise ValueError("at least one scope is required")
    return sorted(set(scopes))


def public(k: AgentKey, acting: User | None = None) -> dict:
    return {
        "id": k.id, "name": k.name, "prefix": k.prefix, "scopes": k.scopes or [], "acting_user_id": k.acting_user_id,
        "acting_username": acting.username if acting else None, "rate_per_minute": k.rate_per_minute, "note": k.note,
        "disabled": k.disabled, "created_at": k.created_at.isoformat(timespec="seconds") if k.created_at else None,
        "last_used_at": k.last_used_at.isoformat(timespec="seconds") if k.last_used_at else None,
    }


def create_key(db: Session, name: str, scopes: list[str], acting_user_id: int, rate_per_minute: int = 60, note: str | None = None, created_by: int | None = None) -> tuple[AgentKey, str]:
    name = name.strip()
    if not name or len(name) > 48:
        raise ValueError("name must be 1-48 characters")
    if db.execute(select(AgentKey).where(AgentKey.name == name)).scalar_one_or_none():
        raise ValueError(f"an agent named {name!r} already exists")
    if db.get(User, acting_user_id) is None:
        raise LookupError(f"user {acting_user_id}")
    if not 1 <= rate_per_minute <= 6000:
        raise ValueError("rate_per_minute must be 1..6000")
    raw, prefix, digest = generate()
    k = AgentKey(name=name, prefix=prefix, key_hash=digest, scopes=validate_scopes(scopes), acting_user_id=acting_user_id, rate_per_minute=rate_per_minute, note=note, created_by_user_id=created_by)
    db.add(k)
    db.commit()
    db.refresh(k)
    return k, raw


def rotate_key(db: Session, k: AgentKey) -> str:
    raw, prefix, digest = generate()
    k.prefix, k.key_hash = prefix, digest
    db.commit()
    return raw


def list_keys(db: Session) -> list[dict]:
    rows = db.execute(select(AgentKey).order_by(AgentKey.name)).scalars().all()
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_({r.acting_user_id for r in rows}))).scalars()} if rows else {}
    return [public(k, users.get(k.acting_user_id)) for k in rows]


def get_by_name(db: Session, name: str) -> AgentKey | None:
    return db.execute(select(AgentKey).where(AgentKey.name == name.strip())).scalar_one_or_none()


# ---------------------------------------------------------------- request side
def raw_key_from_headers(headers) -> str | None:
    auth = headers.get("authorization") or ""
    if auth.lower().startswith("bearer ") and auth[7:].strip().startswith(PREFIX):
        return auth[7:].strip()
    x = headers.get("x-agent-key")
    return x.strip() if x and x.strip().startswith(PREFIX) else None


def authenticate(db: Session, raw: str) -> AgentKey | None:
    k = db.execute(select(AgentKey).where(AgentKey.key_hash == hash_key(raw))).scalar_one_or_none()
    if k is None or k.disabled:
        return None
    return k


def allowed(k: AgentKey, method: str, path: str) -> bool:
    scopes = set(k.scopes or [])
    method = method.upper()
    if path.startswith("/api/market/knowledge/proposals") and method == "POST":
        return "knowledge:propose" in scopes
    if path.startswith("/api/market/") and method in ("GET", "HEAD"):
        return "market:read" in scopes
    if path.startswith("/api/me/") and method in ("GET", "HEAD"):
        return "personal:read" in scopes
    if path in ("/api/auth/me",) and method == "GET":
        return True
    return False


def within_rate(k: AgentKey, now: float | None = None) -> bool:
    now = now or time.monotonic()
    q = _hits.setdefault(k.id, deque())
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= k.rate_per_minute:
        return False
    q.append(now)
    return True


def touch(db: Session, k: AgentKey) -> None:
    """Record last use, at most once a minute per key so reads do not turn into writes."""
    now = time.monotonic()
    last = _touched.get(k.id)
    if last is not None and now - last < 60:  # monotonic() can be < 60 on a fresh machine, so no 0 sentinel
        return
    _touched[k.id] = now
    k.last_used_at = datetime.now()
    db.commit()


def reset_limits() -> None:  # tests
    _hits.clear()
    _touched.clear()
