"""FastAPI dependencies: current user (session cookie, local service token, or an agent key), admin check."""
from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import User
from ..services import agents, auth

SERVICE_PREFIXES = ("/api/market/",)


def _service_user(request: Request, db: Session) -> User | None:
    """Local services (the CRM's MCP server) call the shared layer without a browser session:
    X-Service-Token must equal CRM_FACADE_TOKEN and X-User-Id names the account they act as.
    Only the shared namespace accepts it; personal and admin routes still need a real login."""
    token = request.headers.get("x-service-token")
    if not token or not settings.crm_facade_token:
        return None
    if not hmac.compare_digest(token, settings.crm_facade_token):
        raise HTTPException(status_code=401, detail="bad service token")
    if not request.url.path.startswith(SERVICE_PREFIXES):
        raise HTTPException(status_code=403, detail="service token is limited to /api/market")
    try:
        uid = int(request.headers.get("x-user-id", ""))
    except ValueError:
        raise HTTPException(status_code=401, detail="X-User-Id required with a service token") from None
    user = db.get(User, uid)
    if user is None or user.disabled:
        raise HTTPException(status_code=401, detail="unknown or disabled user")
    return user


def _agent_user(request: Request, db: Session) -> User | None:
    """External agents: `Authorization: Bearer twa_...` or `X-Agent-Key`. The key's scopes decide which
    routes it may call; it acts as its acting user for reads and proposals, never as an admin."""
    raw = agents.raw_key_from_headers(request.headers)
    if not raw:
        return None
    key = agents.authenticate(db, raw)
    if key is None:
        raise HTTPException(status_code=401, detail="bad or disabled agent key")
    if not agents.allowed(key, request.method, request.url.path):
        raise HTTPException(status_code=403, detail=f"agent key '{key.name}' lacks a scope for this route")
    if not agents.within_rate(key):
        raise HTTPException(status_code=429, detail="agent key rate limit", headers={"Retry-After": "60"})
    user = db.get(User, key.acting_user_id)
    if user is None or user.disabled:
        raise HTTPException(status_code=401, detail="agent's acting user is missing or disabled")
    agents.touch(db, key)
    request.state.agent = key
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = auth.session_user(db, request.cookies.get(settings.cookie_name)) or _service_user(request, db) or _agent_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="login required")
    request.state.user = user
    return user


def require_admin(request: Request, user: User = Depends(current_user)) -> User:
    if getattr(request.state, "agent", None) is not None:
        raise HTTPException(status_code=403, detail="agent keys cannot use admin routes")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    return user


def agent_of(request: Request):
    """The AgentKey behind this request, or None for a person / the CRM service."""
    return getattr(request.state, "agent", None)


def client_ip(request: Request) -> str | None:
    # behind Cloudflare Tunnel / a reverse proxy the real address is in these headers
    for h in ("cf-connecting-ip", "x-forwarded-for"):
        v = request.headers.get(h)
        if v:
            return v.split(",")[0].strip()
    return request.client.host if request.client else None
