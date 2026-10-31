"""/api/market/knowledge/*: the shared knowledge graph (companies, edges, briefs, actual financials).

Reads: anyone logged in. Writes: admins only, which includes the CRM's processes when they call with
X-Service-Token + X-User-Id of an admin (official-data scripts, approved knowledge-scope proposals).
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..services import etf_holdings, knowledge_jobs, mops
from ..services import knowledge as kn
from .deps import agent_of, current_user, require_admin

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


@router.get("/todo")
def todo(stale_days: int = 45, db: Session = Depends(get_db)):
    """What still needs a human or an LLM: missing profiles, stale highlights, isolated nodes, unsourced edges."""
    return knowledge_jobs.todo(db, stale_days)


@router.get("/funds")
def funds(db: Session = Depends(get_db)):
    return etf_holdings.funds(db)


@router.get("/funds/{fund_id}/holdings")
def fund_holdings(fund_id: str, db: Session = Depends(get_db)):
    return etf_holdings.holdings(db, fund_id)


class HoldingsIn(BaseModel):
    as_of: dt.date
    source: str
    fund_name: str | None = None
    rows: list[dict]
    prune: bool = True


@router.post("/funds/{fund_id}/holdings")
def put_fund_holdings(fund_id: str, body: HoldingsIn, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _run(etf_holdings.apply_holdings, db, fund_id, body.rows, body.as_of, body.source, body.fund_name, body.prune)


@router.post("/funds/{fund_id}/refresh")
def refresh_fund(fund_id: str, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    return etf_holdings.refresh_tw_funds(db, [fund_id.upper()])


@router.get("/tasks")
def tasks(limit: int = Query(5, le=20), company: str | None = None, news: bool = True, db: Session = Depends(get_db)):
    """Work packets for agents: companies that still lack a profile / fresh highlights / relations, each
    with the engine's own material bundled (exchange profile, numbers, known edges, headlines). An
    agent reads these and answers with proposals; it never has to scrape the engine's sources itself."""
    from ..models import Company
    from ..services import extractor

    if company:
        c = db.get(Company, company.upper())
        if c is None:
            raise HTTPException(404, "unknown company")
        targets = [(c, ["requested"])]
    else:
        todo = knowledge_jobs.todo(db, limit=10000)
        needs: dict[str, list[str]] = {}
        for key, label in (("missing_profile", "profile"), ("stale_highlights", "highlights"), ("isolated_companies", "edges")):
            for r in todo[key]:
                needs.setdefault(r["id"], []).append(label)
        targets = []
        for cid, labels in needs.items():
            c = db.get(Company, cid)
            if c is not None and c.sector != "ETF":
                targets.append((c, labels))
            if len(targets) >= limit:
                break
    out = []
    for c, labels in targets:
        m = extractor.material(db, c, with_news=news)
        out.append({"company_id": c.id, "name": c.name, "needs": labels, "material": m,
                    "answer_with": {"endpoint": "POST /api/market/knowledge/proposals/batch", "kinds": ["brief", "edge", "metric"], "company_id_format": "TW:2330 / US:NVDA / KR:005930"}})
    return out


@router.get("/graph")
def graph(ids: str | None = None, depth: int = Query(1, ge=0, le=3), holding: bool = False, db: Session = Depends(get_db)):
    """Subgraph for the graph page: ids = comma separated company ids (TW:2330,US:NVDA); omit for the
    whole graph. depth = hops around the ids. holding = include ETF constituent edges."""
    id_list = [x.strip() for x in ids.split(",") if x.strip()] if ids else None
    return kn.subgraph(db, id_list, depth, holding)


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


# ---------------------------------------------------------------- proposals (review queue)
from ..services import knowledge_proposals as kp  # noqa: E402


class ProposalIn(BaseModel):
    kind: str
    payload: dict
    summary: str | None = None
    rationale: str | None = None
    evidence: list[dict] | None = None
    source: str | None = None
    confidence: str | None = None
    created_by: str | None = None


class DecideIn(BaseModel):
    approve: bool
    note: str | None = None


class DecideBatchIn(DecideIn):
    ids: list[int]


@router.get("/proposals")
def proposals(status: str | None = "pending", kind: str | None = None, company: str | None = None, limit: int = Query(200, le=2000), db: Session = Depends(get_db)):
    return kp.list_proposals(db, status, kind, company, limit)


@router.get("/proposals/counts")
def proposal_counts(db: Session = Depends(get_db)):
    return kp.counts(db)


def _stamp(request: Request, user: User, data: dict) -> dict:
    """Who a proposal is from: an agent key is always `agent:<name>`; members cannot pose as a system."""
    agent = agent_of(request)
    if agent is not None:
        data["created_by"] = f"agent:{agent.name}"
    elif user.role != "admin" and str(data.get("created_by", "")).startswith("system:"):
        data["created_by"] = f"user:{user.username}"
    return data


@router.post("/proposals", status_code=201)
def post_proposal(body: ProposalIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = _stamp(request, user, body.model_dump(exclude_none=True))
    return kp.to_dict(_run(kp.propose, db, data, user))


@router.post("/proposals/batch", status_code=201)
def post_proposals(body: list[ProposalIn], request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = [_stamp(request, user, b.model_dump(exclude_none=True)) for b in body]
    return [kp.to_dict(r) for r in _run(kp.propose_many, db, items, user)]


@router.post("/proposals/decide")
def decide_batch(body: DecideBatchIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return kp.decide_many(db, body.ids, body.approve, user, body.note)


@router.post("/proposals/{proposal_id}/decide")
def decide_one(proposal_id: int, body: DecideIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return kp.to_dict(_run(kp.decide, db, proposal_id, body.approve, user, body.note))
