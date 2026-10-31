"""FastAPI dependencies: current user (session cookie) and admin check."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import User
from ..services import auth


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = auth.session_user(db, request.cookies.get(settings.cookie_name))
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
