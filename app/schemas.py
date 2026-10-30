from typing import Any

from pydantic import BaseModel, Field


class WatchlistCreate(BaseModel):
    code: str = Field(..., min_length=4, max_length=12)
    note: str | None = None
    tags: str | None = None
    backfill: bool = True


class WatchlistUpdate(BaseModel):
    note: str | None = None
    tags: str | None = None


class AlertRuleCreate(BaseModel):
    code: str
    rule_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    one_shot: bool = False
    cooldown_minutes: int | None = None  # None -> default for the rule scope
    note: str | None = None


class AlertRuleUpdate(BaseModel):
    params: dict[str, Any] | None = None
    enabled: bool | None = None
    one_shot: bool | None = None
    cooldown_minutes: int | None = None
    note: str | None = None


class NotifyTest(BaseModel):
    message: str = "TW Stock Tracker test notification"
