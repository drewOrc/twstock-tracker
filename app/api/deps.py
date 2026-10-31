"""FastAPI dependencies: current user (session cookie, or a local service token), admin check."""
from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import User
from ..services import auth

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


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = auth.session_user(db, request.cookies.get(settings.cookie_name)) or _service_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="login required")
    request.state.user = user
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    return user


def client_ip(request: Request) -> str | None:
    # behind Cloudflare Tunnel / a reverse proxy the real address is in these headers
    for h in ("cf-connecting-ip", "x-forwarded-for"):
        v = request.headers.get(h)
        if v:
            return v.split(",")[0].strip()
    return request.client.host if request.client else None
