"""Shared knowledge layer: companies, supply-chain edges, briefs, actual financials.

The engine is the only writer of these tables (see db.ENGINE_TABLES). The CRM reads them from the
same SQLite file and sends changes through /api/market/knowledge/*; its agents only ever propose.
Every write carries source / confidence / created_by so provenance survives the move.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import Company, CompanyBrief, Edge, EdgeWeight, FinancialYTD, MetricActual

CONFIDENCES = ("high", "medium", "low")
RELATIONS = ("customer", "partner", "holding")
BRIEF_KINDS = ("profile", "highlights")
METRICS = ("revenue_m", "revenue_q", "gross_margin", "opex", "eps", "shares")
MARKETS = ("TW", "US", "KR")  # KR: Korean names in the supply chain (Samsung, SK hynix); knowledge only, no quotes


def company_id_for(code: str, market: str = "TW") -> str:
    return f"{market}:{code}"


def _check(value, allowed, label) -> str:
    if value not in allowed:
        raise ValueError(f"{label} must be one of {', '.join(allowed)}")
    return value


def _date(v) -> date:
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _dt(v) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", ""))
    except ValueError:
        return None


# ------------------------------------------------------------------ serializers
def company_dict(c: Company) -> dict:
    return {
        "id": c.id, "market": c.market, "ticker": c.ticker, "name": c.name, "name_en": c.name_en,
        "sector": c.sector, "notes": c.notes, "source": c.source, "confidence": c.confidence,
        "created_by": c.created_by, "created_at": c.created_at.isoformat(timespec="seconds") if c.created_at else None,
        "updated_at": c.updated_at.isoformat(timespec="seconds") if c.updated_at else None,
    }


def edge_dict(e: Edge, names: dict[str, str] | None = None) -> dict:
    d = {
        "id": e.id, "customer_id": e.customer_id, "supplier_id": e.supplier_id, "revenue_share": e.revenue_share,
        "lag_days": e.lag_days, "confidence": e.confidence, "relation": e.relation, "source": e.source,
        "notes": e.notes, "created_by": e.created_by,
        "created_at": e.created_at.isoformat(timespec="seconds") if e.created_at else None,
    }
    if names is not None:
        d["customer_name"] = names.get(e.customer_id)
        d["supplier_name"] = names.get(e.supplier_id)
    return d


def brief_dict(b: CompanyBrief) -> dict:
    return {
        "id": b.id, "company_id": b.company_id, "date": b.date.isoformat(), "kind": b.kind, "content": b.content,
        "sources": b.sources or [], "created_by": b.created_by,
        "created_at": b.created_at.isoformat(timespec="seconds") if b.created_at else None,
    }


def financial_dict(f: FinancialYTD) -> dict:
    return {
        "id": f.id, "company_id": f.company_id, "year": f.year, "quarter": f.quarter, "revenue": f.revenue,
        "gross_profit": f.gross_profit, "opex": f.opex, "net_income": f.net_income, "eps": f.eps, "source": f.source,
        "fetched_at": f.fetched_at.isoformat(timespec="seconds") if f.fetched_at else None,
    }


def metric_dict(m: MetricActual) -> dict:
    return {
        "id": m.id, "company_id": m.company_id, "metric": m.metric, "period": m.period, "value": m.value,
        "source": m.source, "created_by": m.created_by,
        "created_at": m.created_at.isoformat(timespec="seconds") if m.created_at else None,
    }


# ------------------------------------------------------------------ companies
def upsert_company(db: Session, data: dict) -> Company:
    cid = (data.get("id") or "").strip().upper()
    if ":" not in cid:
        raise ValueError("id must look like TW:2330, US:NVDA or KR:005930")
    market, ticker = cid.split(":", 1)
    _check(market, MARKETS, "market")
    c = db.get(Company, cid)
    if c is None:
        c = Company(id=cid, market=market, ticker=ticker, name=data.get("name") or ticker)
        db.add(c)
    for k in ("name", "name_en", "sector", "notes", "source", "created_by"):
        if data.get(k) is not None:
            setattr(c, k, data[k])
    if data.get("confidence"):
        c.confidence = _check(data["confidence"], CONFIDENCES, "confidence")
    c.updated_at = datetime.now()
    db.commit()
    db.refresh(c)
    return c


def list_companies(db: Session, q: str | None = None, market: str | None = None, limit: int = 500) -> list[dict]:
    stmt = select(Company)
    if market:
        stmt = stmt.where(Company.market == market.upper())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Company.id.ilike(like), Company.name.ilike(like), Company.name_en.ilike(like), Company.sector.ilike(like)))
    rows = db.execute(stmt.order_by(Company.market, Company.ticker).limit(limit)).scalars()
    return [company_dict(c) for c in rows]


def _names(db: Session, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    return {c.id: c.name for c in db.execute(select(Company).where(Company.id.in_(ids))).scalars()}


def latest_briefs(db: Session, company_id: str) -> dict[str, dict | None]:
    out: dict[str, dict | None] = {k: None for k in BRIEF_KINDS}
    for kind in BRIEF_KINDS:
        b = db.execute(
            select(CompanyBrief).where(CompanyBrief.company_id == company_id, CompanyBrief.kind == kind)
            .order_by(CompanyBrief.date.desc(), CompanyBrief.id.desc()).limit(1)
        ).scalar_one_or_none()
        out[kind] = brief_dict(b) if b else None
    return out


def edges_for(db: Session, company_id: str) -> dict[str, list[dict]]:
    rows = db.execute(select(Edge).where(or_(Edge.customer_id == company_id, Edge.supplier_id == company_id)).order_by(Edge.revenue_share.desc().nullslast())).scalars().all()
    names = _names(db, {e.customer_id for e in rows} | {e.supplier_id for e in rows})
    return {
        "customers": [edge_dict(e, names) for e in rows if e.supplier_id == company_id],  # who buys from us
        "suppliers": [edge_dict(e, names) for e in rows if e.customer_id == company_id],  # whom we buy from / hold
    }


def get_company(db: Session, company_id: str) -> dict:
    c = db.get(Company, company_id.upper())
    if c is None:
        raise LookupError(company_id)
    d = company_dict(c)
    d["briefs"] = latest_briefs(db, c.id)
    d["edges"] = edges_for(db, c.id)
    d["metrics"] = [metric_dict(m) for m in db.execute(select(MetricActual).where(MetricActual.company_id == c.id).order_by(MetricActual.metric, MetricActual.period.desc())).scalars()]
    d["financials"] = [financial_dict(f) for f in db.execute(select(FinancialYTD).where(FinancialYTD.company_id == c.id).order_by(FinancialYTD.year.desc(), FinancialYTD.quarter.desc())).scalars()]
    return d


# ------------------------------------------------------------------ edges
def list_edges(db: Session, company_id: str | None = None, relation: str | None = None, limit: int = 1000) -> list[dict]:
    stmt = select(Edge)
    if company_id:
        cid = company_id.upper()
        stmt = stmt.where(or_(Edge.customer_id == cid, Edge.supplier_id == cid))
    if relation:
        stmt = stmt.where(Edge.relation == relation)
    rows = db.execute(stmt.order_by(Edge.supplier_id, Edge.revenue_share.desc().nullslast()).limit(limit)).scalars().all()
    names = _names(db, {e.customer_id for e in rows} | {e.supplier_id for e in rows})
    return [edge_dict(e, names) for e in rows]


def upsert_edge(db: Session, data: dict) -> Edge:
    cust = (data.get("customer_id") or "").upper()
    supp = (data.get("supplier_id") or "").upper()
    if not cust or not supp or cust == supp:
        raise ValueError("customer_id and supplier_id must be two different company ids")
    for cid in (cust, supp):
        if db.get(Company, cid) is None:
            raise LookupError(cid)
    e = db.execute(select(Edge).where(Edge.customer_id == cust, Edge.supplier_id == supp)).scalar_one_or_none()
    if e is None:
        e = Edge(customer_id=cust, supplier_id=supp)
        if data.get("id"):
            e.id = int(data["id"])
        db.add(e)
    for k in ("lag_days", "source", "notes", "created_by"):
        if data.get(k) is not None:
            setattr(e, k, data[k])
    if data.get("confidence"):
        e.confidence = _check(data["confidence"], CONFIDENCES, "confidence")
    if data.get("relation"):
        e.relation = _check(data["relation"], RELATIONS, "relation")
    if "revenue_share" in data and data["revenue_share"] is not None:
        share = float(data["revenue_share"])
        if not 0 <= share <= 1:
            raise ValueError("revenue_share must be between 0 and 1")
        e.revenue_share = share
        db.flush()
        if data.get("date"):
            _record_weight(db, e, _date(data["date"]), share, data.get("source"), data.get("created_by") or "user")
    e.updated_at = datetime.now()
    db.commit()
    db.refresh(e)
    return e


def delete_edge(db: Session, edge_id: int) -> None:
    e = db.get(Edge, edge_id)
    if e is None:
        raise LookupError(str(edge_id))
    db.delete(e)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def _record_weight(db: Session, e: Edge, d: date, share: float, source: str | None, created_by: str) -> EdgeWeight:
    w = db.execute(select(EdgeWeight).where(EdgeWeight.edge_id == e.id, EdgeWeight.date == d)).scalar_one_or_none()
    if w is None:
        w = EdgeWeight(edge_id=e.id, date=d)
        db.add(w)
    w.revenue_share, w.source, w.created_by = share, source, created_by
    latest = db.execute(select(func.max(EdgeWeight.date)).where(EdgeWeight.edge_id == e.id)).scalar()
    if latest is None or d >= latest:
        e.revenue_share = share
    return w


def add_edge_weight(db: Session, edge_id: int, data: dict) -> EdgeWeight:
    e = db.get(Edge, edge_id)
    if e is None:
        raise LookupError(str(edge_id))
    share = float(data["revenue_share"])
    if not 0 <= share <= 1:
        raise ValueError("revenue_share must be between 0 and 1")
    w = _record_weight(db, e, _date(data.get("date") or date.today()), share, data.get("source"), data.get("created_by") or "user")
    db.commit()
    db.refresh(w)
    return w


def edge_weights(db: Session, edge_id: int) -> list[dict]:
    rows = db.execute(select(EdgeWeight).where(EdgeWeight.edge_id == edge_id).order_by(EdgeWeight.date)).scalars()
    return [{"date": w.date.isoformat(), "revenue_share": w.revenue_share, "source": w.source, "created_by": w.created_by} for w in rows]


# ------------------------------------------------------------------ briefs
def add_brief(db: Session, data: dict) -> CompanyBrief:
    cid = (data.get("company_id") or "").upper()
    if db.get(Company, cid) is None:
        raise LookupError(cid)
    content = (data.get("content") or "").strip()
    if not content:
        raise ValueError("content is required")
    b = CompanyBrief(
        company_id=cid, date=_date(data.get("date") or date.today()), kind=_check(data.get("kind"), BRIEF_KINDS, "kind"),
        content=content, sources=data.get("sources") or [], created_by=data.get("created_by") or "user",
    )
    if data.get("id"):
        b.id = int(data["id"])
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def list_briefs(db: Session, company_id: str, kind: str | None = None, limit: int = 20) -> list[dict]:
    stmt = select(CompanyBrief).where(CompanyBrief.company_id == company_id.upper())
    if kind:
        stmt = stmt.where(CompanyBrief.kind == kind)
    return [brief_dict(b) for b in db.execute(stmt.order_by(CompanyBrief.date.desc(), CompanyBrief.id.desc()).limit(limit)).scalars()]


# ------------------------------------------------------------------ financials / metrics
def upsert_financial(db: Session, data: dict) -> FinancialYTD:
    cid = (data.get("company_id") or "").upper()
    if db.get(Company, cid) is None:
        raise LookupError(cid)
    year, quarter = int(data["year"]), int(data["quarter"])
    if not 1 <= quarter <= 4:
        raise ValueError("quarter must be 1..4")
    f = db.execute(select(FinancialYTD).where(FinancialYTD.company_id == cid, FinancialYTD.year == year, FinancialYTD.quarter == quarter)).scalar_one_or_none()
    if f is None:
        f = FinancialYTD(company_id=cid, year=year, quarter=quarter)
        db.add(f)
    for k in ("revenue", "gross_profit", "opex", "net_income", "eps", "source"):
        if k in data:
            setattr(f, k, data[k])
    f.fetched_at = _dt(data.get("fetched_at")) or datetime.now()
    db.commit()
    db.refresh(f)
    return f


def list_financials(db: Session, company_id: str) -> list[dict]:
    rows = db.execute(select(FinancialYTD).where(FinancialYTD.company_id == company_id.upper()).order_by(FinancialYTD.year.desc(), FinancialYTD.quarter.desc())).scalars()
    return [financial_dict(f) for f in rows]


def upsert_metric(db: Session, data: dict) -> MetricActual:
    cid = (data.get("company_id") or "").upper()
    if db.get(Company, cid) is None:
        raise LookupError(cid)
    metric = _check(data.get("metric"), METRICS, "metric")
    period = str(data.get("period") or "").strip()
    if not period:
        raise ValueError("period is required")
    m = db.execute(select(MetricActual).where(MetricActual.company_id == cid, MetricActual.metric == metric, MetricActual.period == period)).scalar_one_or_none()
    if m is None:
        m = MetricActual(company_id=cid, metric=metric, period=period)
        db.add(m)
    m.value = float(data["value"])
    if data.get("source") is not None:
        m.source = data["source"]
    if data.get("created_by"):
        m.created_by = data["created_by"]
    db.commit()
    db.refresh(m)
    return m


def list_metrics(db: Session, company_id: str, metric: str | None = None) -> list[dict]:
    stmt = select(MetricActual).where(MetricActual.company_id == company_id.upper())
    if metric:
        stmt = stmt.where(MetricActual.metric == metric)
    return [metric_dict(m) for m in db.execute(stmt.order_by(MetricActual.metric, MetricActual.period.desc())).scalars()]


# ------------------------------------------------------------------ for the engine itself
def for_stock(db: Session, code: str) -> dict | None:
    """What the summary page shows for a TW code: latest profile / highlights and the nearest
    supply-chain neighbours. None when the graph has never heard of the company."""
    cid = company_id_for(code)
    c = db.get(Company, cid)
    if c is None:
        return None
    edges = edges_for(db, cid)
    return {
        "company_id": cid, "sector": c.sector, "name_en": c.name_en,
        "briefs": latest_briefs(db, cid),
        "customers": [{"id": e["customer_id"], "name": e["customer_name"], "revenue_share": e["revenue_share"], "relation": e["relation"]} for e in edges["customers"]],
        "suppliers": [{"id": e["supplier_id"], "name": e["supplier_name"], "revenue_share": e["revenue_share"], "relation": e["relation"]} for e in edges["suppliers"]],
    }


def stats(db: Session) -> dict:
    return {
        "companies": db.execute(select(func.count()).select_from(Company)).scalar(),
        "edges": db.execute(select(func.count()).select_from(Edge)).scalar(),
        "edge_weights": db.execute(select(func.count()).select_from(EdgeWeight)).scalar(),
        "briefs": db.execute(select(func.count()).select_from(CompanyBrief)).scalar(),
        "financials": db.execute(select(func.count()).select_from(FinancialYTD)).scalar(),
        "metrics": db.execute(select(func.count()).select_from(MetricActual)).scalar(),
    }


# ------------------------------------------------------------------ one-time import from the CRM
def import_from_crm(db: Session, path: Path) -> dict:
    """Copy the CRM's former knowledge tables (companies, edges, company_briefs, financials_ytd,
    metrics kind=actual) into knowledge_*, keeping ids. Read-only on the source; idempotent."""
    if not Path(path).exists():
        raise FileNotFoundError(path)
    src = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    counts = {"companies": 0, "edges": 0, "briefs": 0, "financials": 0, "metrics": 0}

    def has(table: str) -> bool:
        return src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None

    try:
        if has("companies"):
            for r in src.execute("SELECT * FROM companies"):
                c = db.get(Company, r["id"]) or Company(id=r["id"], market=r["market"], ticker=r["ticker"], name=r["name"])
                c.name, c.name_en, c.sector, c.notes = r["name"], r["name_en"], r["sector"], r["notes"]
                c.created_by = "import:stockcrm"
                if r["created_at"] and _dt(r["created_at"]):
                    c.created_at = _dt(r["created_at"])
                db.add(c)
                counts["companies"] += 1
            db.flush()
        if has("edges"):
            for r in src.execute("SELECT * FROM edges"):
                e = db.get(Edge, r["id"]) or db.execute(select(Edge).where(Edge.customer_id == r["customer_id"], Edge.supplier_id == r["supplier_id"])).scalar_one_or_none()
                if e is None:
                    e = Edge(id=r["id"], customer_id=r["customer_id"], supplier_id=r["supplier_id"])
                    db.add(e)
                e.revenue_share, e.lag_days = r["revenue_share"], r["lag_days"]
                e.confidence = r["confidence"] if r["confidence"] in CONFIDENCES else "medium"
                e.relation = r["relation"] if r["relation"] in RELATIONS else "customer"
                e.source, e.notes, e.created_by = r["source"], r["notes"], r["created_by"] or "import:stockcrm"
                if _dt(r["created_at"]):
                    e.created_at = _dt(r["created_at"])
                counts["edges"] += 1
            db.flush()
        if has("company_briefs"):
            for r in src.execute("SELECT * FROM company_briefs"):
                if db.get(CompanyBrief, r["id"]) is not None:
                    continue
                try:
                    sources = json.loads(r["sources"] or "[]")
                except ValueError:
                    sources = []
                b = CompanyBrief(id=r["id"], company_id=r["company_id"], date=_date(r["date"]), kind=r["kind"], content=r["content"], sources=sources, created_by=r["created_by"] or "import:stockcrm")
                if _dt(r["created_at"]):
                    b.created_at = _dt(r["created_at"])
                db.add(b)
                counts["briefs"] += 1
        if has("financials_ytd"):
            for r in src.execute("SELECT * FROM financials_ytd"):
                f = db.execute(select(FinancialYTD).where(FinancialYTD.company_id == r["company_id"], FinancialYTD.year == r["year"], FinancialYTD.quarter == r["quarter"])).scalar_one_or_none()
                if f is None:
                    f = FinancialYTD(company_id=r["company_id"], year=r["year"], quarter=r["quarter"])
                    db.add(f)
                f.revenue, f.gross_profit, f.opex, f.net_income, f.eps, f.source = r["revenue"], r["gross_profit"], r["opex"], r["net_income"], r["eps"], r["source"]
                f.fetched_at = _dt(r["fetched_at"]) or datetime.now()
                counts["financials"] += 1
        if has("metrics"):
            for r in src.execute("SELECT * FROM metrics WHERE kind='actual'"):
                m = db.execute(select(MetricActual).where(MetricActual.company_id == r["company_id"], MetricActual.metric == r["metric"], MetricActual.period == r["period"])).scalar_one_or_none()
                if m is None:
                    m = MetricActual(company_id=r["company_id"], metric=r["metric"], period=r["period"])
                    db.add(m)
                m.value, m.source, m.created_by = r["value"], r["source"], r["created_by"] or "import:stockcrm"
                if _dt(r["created_at"]):
                    m.created_at = _dt(r["created_at"])
                counts["metrics"] += 1
        db.commit()
    finally:
        src.close()
    return counts


# ------------------------------------------------------------------ subgraphs for the graph page
def subgraph(db: Session, ids: list[str] | None, depth: int = 1, include_holding: bool = False, limit_nodes: int = 400) -> dict:
    """Nodes and edges around a set of companies. depth 0 = only edges among the given ids,
    depth 1 = plus their direct neighbours, depth 2 = neighbours of neighbours. ids=None = everything."""
    rel_ok = (lambda e: True) if include_holding else (lambda e: e.relation != "holding")
    all_edges = [e for e in db.execute(select(Edge)).scalars() if rel_ok(e)]
    if ids is None:
        keep_edges = all_edges
        node_ids = {e.customer_id for e in keep_edges} | {e.supplier_id for e in keep_edges}
        seeds: set[str] = set()
    else:
        seeds = {i.upper() for i in ids if i}
        frontier, node_ids = set(seeds), set(seeds)
        for _ in range(max(0, depth)):
            nxt = set()
            for e in all_edges:
                if e.customer_id in frontier:
                    nxt.add(e.supplier_id)
                if e.supplier_id in frontier:
                    nxt.add(e.customer_id)
            nxt -= node_ids
            node_ids |= nxt
            frontier = nxt
            if len(node_ids) > limit_nodes:
                break
        keep_edges = [e for e in all_edges if e.customer_id in node_ids and e.supplier_id in node_ids]
    comps = {c.id: c for c in db.execute(select(Company).where(Company.id.in_(node_ids))).scalars()} if node_ids else {}
    nodes = [{"id": c.id, "name": c.name, "market": c.market, "sector": c.sector, "seed": c.id in seeds} for c in comps.values()]
    nodes.sort(key=lambda n: (not n["seed"], n["market"], n["id"]))
    names = {c.id: c.name for c in comps.values()}
    return {"nodes": nodes, "edges": [edge_dict(e, names) for e in keep_edges], "seeds": sorted(seeds), "depth": depth, "include_holding": include_holding}
