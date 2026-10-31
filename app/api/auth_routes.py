"""/api/auth: login, logout, me, password change; /api/admin/users: account management."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import User
from ..services import auth
from .deps import client_ip, current_user, require_admin

router = APIRouter(prefix="/api/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api/admin/users", tags=["admin"], dependencies=[Depends(require_admin)])


class LoginBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=1, max_length=256)


class PasswordBody(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=256)


class UserCreate(BaseModel):
    username: str
    password: str = Field(..., min_length=8)
    role: str = "member"
    display_name: str | None = None
    line_user_id: str | None = None
    email: str | None = None


class UserPatch(BaseModel):
    display_name: str | None = None
    role: str | None = None
    line_user_id: str | None = None
    email: str | None = None
    disabled: bool | None = None
    password: str | None = Field(default=None, min_length=8)


def _is_https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    return proto == "https" or '"scheme":"https"' in (request.headers.get("cf-visitor") or "")


def _set_cookie(response: Response, token: str, request: Request) -> None:
    # Secure when the client reached us over HTTPS (Cloudflare Tunnel); plain http on the LAN still works.
    response.set_cookie(
        settings.cookie_name, token, max_age=settings.session_days * 86400, httponly=True,
        secure=settings.cookie_secure or _is_https(request), samesite="lax", path="/",
    )


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    try:
        user = auth.authenticate(db, body.username, body.password, ip)
    except PermissionError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
    s = auth.create_session(db, user, ip, request.headers.get("user-agent"))
    _set_cookie(response, s.token, request)
    return auth.public_user(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    auth.destroy_session(db, request.cookies.get(settings.cookie_name))
    response.delete_cookie(settings.cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return auth.public_user(user)


@router.post("/password")
def change_password(body: PasswordBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not auth.verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="目前密碼錯誤")
    auth.set_password(db, user, body.new_password)
    return {"ok": True, "note": "所有裝置已登出，請重新登入"}


# ---------------------------------------------------------------------- admin: users
@admin_router.get("")
def list_users(db: Session = Depends(get_db)):
    return [auth.public_user(u) for u in auth.list_users(db)]


@admin_router.post("", status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db)):
    try:
        return auth.public_user(auth.create_user(db, body.username, body.password, body.role, body.display_name, body.line_user_id, body.email))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@admin_router.patch("/{user_id}")
def patch_user(user_id: int, body: UserPatch, me_: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="user not found")
    if body.role is not None:
        if body.role not in auth.ROLES:
            raise HTTPException(status_code=400, detail="bad role")
        if u.id == me_.id and body.role != "admin":
            raise HTTPException(status_code=400, detail="不能取消自己的管理員權限")
        u.role = body.role
    if body.disabled is not None:
        if u.id == me_.id and body.disabled:
            raise HTTPException(status_code=400, detail="不能停用自己")
        u.disabled = body.disabled
    for f in ("display_name", "line_user_id", "email"):
        v = getattr(body, f)
        if v is not None:
            setattr(u, f, v or None)
    if body.password:
        auth.set_password(db, u, body.password)
    db.commit()
    return auth.public_user(u)
