"""/api/market/knowledge/*: the shared knowledge graph (companies, edges, briefs, actual financials).

Reads: anyone logged in. Writes: admins only, which includes the CRM's processes when they call with
X-Service-Token + X-User-Id of an admin (official-data scripts, approved knowledge-scope proposals).
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..services import knowledge as kn
from ..services import mops
from .deps import current_user, require_admin

router = APIRouter(tags=["knowledge"], dependencies=[Depends(current_user)])


class CompanyIn(BaseModel):
    name: str | None = None
    name_en: str | None = None
    sector: str | None = None
    notes: str | None = None
    source: str | None = None
    confidence: str | None = None
    created_by: str | None = None


class EdgeIn(BaseModel):
    customer_id: str
    supplier_id: str
    revenue_share: float | None = Field(default=None, ge=0, le=1)
    date: dt.date | None = None  # when given with revenue_share, also recorded in the weight history
    lag_days: int | None = None
    confidence: str | None = None
    relation: str | None = None
    source: str | None = None
    notes: str | None = None
    created_by: str | None = None


class WeightIn(BaseModel):
    date: dt.date | None = None
    revenue_share: float = Field(ge=0, le=1)
    source: str | None = None
    created_by: str | None = None


class BriefIn(BaseModel):
    company_id: str
    kind: str
    content: str
    date: dt.date | None = None
    sources: list[dict] | None = None
    created_by: str | None = None


class FinancialIn(BaseModel):
    company_id: str
    year: int
    quarter: int
    revenue: float | None = None
    gross_profit: float | None = None
    opex: float | None = None
    net_income: float | None = None
    eps: float | None = None
    source: str | None = None


class MetricIn(BaseModel):
    company_id: str
    metric: str
    period: str
    value: float
    source: str | None = None
    created_by: str | None = None


def _run(fn, *a, **k):
    try:
        return fn(*a, **k)
    except LookupError as e:
        raise HTTPException(404, f"unknown: {e}") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except IntegrityError as e:
        raise HTTPException(409, f"still referenced: {e.orig}") from None


def _by(user: User, given: str | None) -> str:
    return given or f"user:{user.username}"


# ---------------------------------------------------------------- reads
@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    return kn.stats(db) | {"official_data": mops.status(db)}


@router.get("/companies")
def companies(q: str | None = None, market: str | None = None, limit: int = Query(500, le=2000), db: Session = Depends(get_db)):
    return kn.list_companies(db, q, market, limit)


@router.get("/companies/{company_id}")
def company(company_id: str, db: Session = Depends(get_db)):
    return _run(kn.get_company, db, company_id)


@router.get("/edges")
def edges(company: str | None = None, relation: str | None = None, db: Session = Depends(get_db)):
    return kn.list_edges(db, company, relation)


@router.get("/edges/{edge_id}/weights")
def weights(edge_id: int, db: Session = Depends(get_db)):
    return kn.edge_weights(db, edge_id)


@router.get("/briefs/{company_id}")
def briefs(company_id: str, kind: str | None = None, limit: int = Query(20, le=200), db: Session = Depends(get_db)):
    return kn.list_briefs(db, company_id, kind, limit)


@router.get("/financials/{company_id}")
def financials(company_id: str, db: Session = Depends(get_db)):
    return kn.list_financials(db, company_id)


@router.get("/metrics/{company_id}")
def metrics(company_id: str, metric: str | None = None, db: Session = Depends(get_db)):
    return kn.list_metrics(db, company_id, metric)


# ---------------------------------------------------------------- writes (admin)
@router.put("/companies/{company_id}")
def put_company(company_id: str, body: CompanyIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_none=True) | {"id": company_id}
    data["created_by"] = _by(user, body.created_by)
    return kn.company_dict(_run(kn.upsert_company, db, data))


@router.post("/edges", status_code=201)
def post_edge(body: EdgeIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_none=True)
    data["created_by"] = _by(user, body.created_by)
    return kn.edge_dict(_run(kn.upsert_edge, db, data))


@router.delete("/edges/{edge_id}")
def delete_edge(edge_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    _run(kn.delete_edge, db, edge_id)
    return {"deleted": edge_id}


@router.post("/edges/{edge_id}/weights", status_code=201)
def post_weight(edge_id: int, body: WeightIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_none=True)
    data["created_by"] = _by(user, body.created_by)
    w = _run(kn.add_edge_weight, db, edge_id, data)
    return {"edge_id": w.edge_id, "date": w.date.isoformat(), "revenue_share": w.revenue_share}


@router.post("/briefs", status_code=201)
def post_brief(body: BriefIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_none=True)
    data["created_by"] = _by(user, body.created_by)
    return kn.brief_dict(_run(kn.add_brief, db, data))


@router.post("/financials")
def post_financial(body: FinancialIn, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    return kn.financial_dict(_run(kn.upsert_financial, db, body.model_dump()))


@router.post("/metrics")
def post_metric(body: MetricIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_none=True)
    data["created_by"] = _by(user, body.created_by)
    return kn.metric_dict(_run(kn.upsert_metric, db, data))


@router.post("/financials/batch")
def post_financials(body: list[FinancialIn], _: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [kn.financial_dict(_run(kn.upsert_financial, db, b.model_dump())) for b in body]


@router.post("/metrics/batch")
def post_metrics(body: list[MetricIn], user: User = Depends(require_admin), db: Session = Depends(get_db)):
    out = []
    for b in body:
        data = b.model_dump(exclude_none=True)
        data["created_by"] = _by(user, b.created_by)
        out.append(kn.metric_dict(_run(kn.upsert_metric, db, data)))
    return out
