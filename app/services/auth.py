"""Local accounts, password hashing (stdlib PBKDF2), server-side sessions and login throttling."""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import User, UserSession

log = logging.getLogger(__name__)

PBKDF2_ROUNDS = 200_000
ROLES = ("admin", "member")


# ---------------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), PBKDF2_ROUNDS).hex()
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), int(rounds)).hex()
        return hmac.compare_digest(calc, digest)
    except ValueError:
        return False


# ---------------------------------------------------------------------- users
def create_user(db: Session, username: str, password: str, role: str = "member", display_name: str | None = None,
                line_user_id: str | None = None, email: str | None = None) -> User:
    username = username.strip().lower()
    if not username or not username.replace("_", "").replace(".", "").isalnum():
        raise ValueError("username must be letters, digits, '.' or '_'")
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    if db.execute(select(User).where(User.username == username)).scalar_one_or_none():
        raise ValueError(f"user '{username}' already exists")
    u = User(username=username, password_hash=hash_password(password), role=role, display_name=display_name or username,
             line_user_id=line_user_id or None, email=email or None)
    db.add(u)
    db.commit()
    return u


def set_password(db: Session, user: User, password: str) -> None:
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    user.password_hash = hash_password(password)
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))  # log out everywhere
    db.commit()


def list_users(db: Session) -> list[User]:
    return list(db.execute(select(User).order_by(User.id)).scalars())


def ensure_admin(db: Session) -> User:
    """First boot: create the admin from ADMIN_USERNAME / ADMIN_PASSWORD, or a placeholder 'admin'
    with a random password written to the log (change it with `cli.py users passwd`)."""
    existing = db.execute(select(User).where(User.role == "admin").order_by(User.id)).scalars().first()
    if existing:
        return existing
    any_user = db.execute(select(User).order_by(User.id)).scalars().first()
    if any_user:  # users exist but none is admin: promote the first one
        any_user.role = "admin"
        db.commit()
        return any_user
    if settings.admin_username and settings.admin_password:
        return create_user(db, settings.admin_username, settings.admin_password, role="admin")
    pw = secrets.token_urlsafe(12)
    u = create_user(db, "admin", pw, role="admin", display_name="Admin")
    log.warning("No users existed: created admin account 'admin' with password %s  (change it: python cli.py users passwd admin)", pw)
    return u


def public_user(u: User) -> dict:
    return {
        "id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role,
        "line_user_id": u.line_user_id, "email": u.email, "disabled": u.disabled,
        "created_at": u.created_at, "last_login_at": u.last_login_at,
    }


# ---------------------------------------------------------------------- login throttle
_failures: dict[str, list[float]] = {}


def _throttle_key(username: str, ip: str | None) -> str:
    return f"{username.lower()}|{ip or '-'}"


def is_locked(username: str, ip: str | None) -> bool:
    key = _throttle_key(username, ip)
    window = time.time() - settings.login_lockout_minutes * 60
    recent = [t for t in _failures.get(key, []) if t > window]
    _failures[key] = recent
    return len(recent) >= settings.login_max_failures


def record_failure(username: str, ip: str | None) -> None:
    _failures.setdefault(_throttle_key(username, ip), []).append(time.time())


def clear_failures(username: str, ip: str | None) -> None:
    _failures.pop(_throttle_key(username, ip), None)


# ---------------------------------------------------------------------- sessions
def authenticate(db: Session, username: str, password: str, ip: str | None = None) -> User | None:
    username = username.strip().lower()
    if is_locked(username, ip):
        raise PermissionError("too many failed logins; try again later")
    u = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if not u or u.disabled or not verify_password(password, u.password_hash):
        record_failure(username, ip)
        return None
    clear_failures(username, ip)
    u.last_login_at = datetime.now()
    db.commit()
    return u


def create_session(db: Session, user: User, ip: str | None = None, user_agent: str | None = None) -> UserSession:
    s = UserSession(
        token=secrets.token_urlsafe(32), user_id=user.id,
        expires_at=datetime.now() + timedelta(days=settings.session_days), ip=ip, user_agent=(user_agent or "")[:256],
    )
    db.add(s)
    db.commit()
    return s


def session_user(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    s = db.get(UserSession, token)
    if not s or s.expires_at < datetime.now() or s.user.disabled:
        return None
    return s.user


def destroy_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(UserSession).where(UserSession.token == token))
        db.commit()


def purge_expired_sessions(db: Session) -> int:
    n = db.execute(delete(UserSession).where(UserSession.expires_at < datetime.now())).rowcount
    db.commit()
    return n
