"""/api/admin/agents: issue, scope, rotate and disable agent keys. Admins only; agent keys themselves
can never call these."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AgentKey, User
from ..services import agents
from .deps import require_admin

router = APIRouter(prefix="/api/admin/agents", tags=["admin"], dependencies=[Depends(require_admin)])


class AgentCreate(BaseModel):
    name: str
    scopes: list[str] = Field(default_factory=lambda: ["market:read", "knowledge:propose"])
    acting_user_id: int | None = None  # default: the admin issuing the key
    rate_per_minute: int = 60
    note: str | None = None


class AgentPatch(BaseModel):
    scopes: list[str] | None = None
    acting_user_id: int | None = None
    rate_per_minute: int | None = None
    note: str | None = None
    disabled: bool | None = None


def _get(db: Session, agent_id: int) -> AgentKey:
    k = db.get(AgentKey, agent_id)
    if k is None:
        raise HTTPException(404, "no such agent key")
    return k


@router.get("/scopes")
def scopes():
    return agents.SCOPES


@router.get("")
def list_agents(db: Session = Depends(get_db)):
    return agents.list_keys(db)


@router.post("", status_code=201)
def create_agent(body: AgentCreate, me: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        k, raw = agents.create_key(db, body.name, body.scopes, body.acting_user_id or me.id, body.rate_per_minute, body.note, me.id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except LookupError as e:
        raise HTTPException(404, f"unknown {e}") from None
    return {"key": raw, "agent": agents.public(k, db.get(User, k.acting_user_id))}


@router.patch("/{agent_id}")
def patch_agent(agent_id: int, body: AgentPatch, db: Session = Depends(get_db)):
    k = _get(db, agent_id)
    try:
        if body.scopes is not None:
            k.scopes = agents.validate_scopes(body.scopes)
        if body.acting_user_id is not None:
            if db.get(User, body.acting_user_id) is None:
                raise HTTPException(404, "unknown user")
            k.acting_user_id = body.acting_user_id
        if body.rate_per_minute is not None:
            if not 1 <= body.rate_per_minute <= 6000:
                raise ValueError("rate_per_minute must be 1..6000")
            k.rate_per_minute = body.rate_per_minute
        if body.note is not None:
            k.note = body.note
        if body.disabled is not None:
            k.disabled = body.disabled
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    db.commit()
    return agents.public(k, db.get(User, k.acting_user_id))


@router.post("/{agent_id}/rotate")
def rotate_agent(agent_id: int, db: Session = Depends(get_db)):
    k = _get(db, agent_id)
    raw = agents.rotate_key(db, k)
    return {"key": raw, "agent": agents.public(k, db.get(User, k.acting_user_id))}


@router.delete("/{agent_id}")
def delete_agent(agent_id: int, db: Session = Depends(get_db)):
    k = _get(db, agent_id)
    db.delete(k)
    db.commit()
    return {"deleted": agent_id}
