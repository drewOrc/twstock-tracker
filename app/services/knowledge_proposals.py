"""Review queue for the shared knowledge layer.

Agents (LLM extractor, Claude sessions via the API, the CRM's MCP) and members propose; an admin
approves in the web UI and the payload is applied through services.knowledge, which keeps every write
path identical. Proposals carry source / confidence / evidence so the reviewer can judge quickly, and
a dedupe_key so the same suggestion is not queued twice while pending.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Edge, KnowledgeProposal, User
from . import knowledge as kn

KINDS = ("company", "edge", "edge_weight", "brief", "metric", "financial")


def _summary(kind: str, p: dict) -> str:
    if kind == "company":
        return f"公司 {p.get('id')} {p.get('name') or ''}".strip()
    if kind == "edge":
        share = p.get("revenue_share")
        rel = {"customer": "客戶", "partner": "夥伴", "holding": "持有"}.get(p.get("relation") or "customer", p.get("relation"))
        s = f"{rel}：{p.get('customer_id')} → {p.get('supplier_id')}"
        return s + (f"（{round(float(share) * 100, 1)}%）" if share is not None else "")
    if kind == "edge_weight":
        return f"權重 edge {p.get('edge_id')} {p.get('date')}：{round(float(p.get('revenue_share', 0)) * 100, 1)}%"
    if kind == "brief":
        return f"{'簡介' if p.get('kind') == 'profile' else '近期重點'} {p.get('company_id')}：{(p.get('content') or '')[:60]}"
    if kind == "metric":
        return f"{p.get('company_id')} {p.get('metric')} {p.get('period')} = {p.get('value')}"
    if kind == "financial":
        return f"{p.get('company_id')} {p.get('year')}Q{p.get('quarter')} YTD"
    return kind


def _dedupe_key(kind: str, p: dict) -> str | None:
    if kind == "company":
        return f"company:{str(p.get('id', '')).upper()}"
    if kind == "edge":
        return f"edge:{str(p.get('customer_id', '')).upper()}>{str(p.get('supplier_id', '')).upper()}"
    if kind == "edge_weight":
        return f"weight:{p.get('edge_id')}:{p.get('date')}"
    if kind == "brief":
        return f"brief:{str(p.get('company_id', '')).upper()}:{p.get('kind')}:{p.get('date') or ''}"
    if kind == "metric":
        return f"metric:{str(p.get('company_id', '')).upper()}:{p.get('metric')}:{p.get('period')}"
    if kind == "financial":
        return f"fin:{str(p.get('company_id', '')).upper()}:{p.get('year')}Q{p.get('quarter')}"
    return None


def _company_ids(kind: str, p: dict) -> list[str]:
    ids = []
    for k in ("id", "company_id", "customer_id", "supplier_id"):
        v = p.get(k)
        if v and ":" in str(v):
            ids.append(str(v).upper())
    for c in p.get("companies") or []:
        if isinstance(c, dict) and c.get("id"):
            ids.append(str(c["id"]).upper())
    return sorted(set(ids))


def to_dict(r: KnowledgeProposal) -> dict:
    return {
        "id": r.id, "kind": r.kind, "payload": r.payload, "summary": r.summary, "rationale": r.rationale,
        "evidence": r.evidence or [], "source": r.source, "confidence": r.confidence, "created_by": r.created_by,
        "user_id": r.user_id, "company_ids": r.company_ids or [], "status": r.status,
        "created_at": r.created_at.isoformat(timespec="seconds") if r.created_at else None,
        "decided_at": r.decided_at.isoformat(timespec="seconds") if r.decided_at else None,
        "decided_by": r.decided_by, "note": r.note, "applied_ref": r.applied_ref,
    }


def propose(db: Session, data: dict, user: User | None = None, commit: bool = True) -> KnowledgeProposal:
    kind = data.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    payload = dict(data.get("payload") or {})
    if not payload:
        raise ValueError("payload is required")
    if data.get("confidence") and data["confidence"] not in kn.CONFIDENCES:
        raise ValueError("confidence must be high, medium or low")
    key = _dedupe_key(kind, payload)
    row = None
    if key:
        row = db.execute(select(KnowledgeProposal).where(KnowledgeProposal.dedupe_key == key, KnowledgeProposal.status == "pending")).scalar_one_or_none()
    if row is None:
        row = KnowledgeProposal(kind=kind, dedupe_key=key, user_id=user.id if user else None)
        db.add(row)
        row.payload = payload
    else:  # a repeat of a pending suggestion refreshes it; keep fields the newer one did not send
        row.payload = {**(row.payload or {}), **payload}
    row.summary = (data.get("summary") or _summary(kind, payload))[:256]
    row.rationale = data.get("rationale")
    row.evidence = data.get("evidence") or []
    row.source = data.get("source") or payload.get("source")
    row.confidence = data.get("confidence") or payload.get("confidence") or "medium"
    row.created_by = data.get("created_by") or (f"user:{user.username}" if user else "agent")
    row.company_ids = _company_ids(kind, payload)
    if commit:
        db.commit()
        db.refresh(row)
    return row


def propose_many(db: Session, items: list[dict], user: User | None = None) -> list[KnowledgeProposal]:
    rows = [propose(db, it, user, commit=False) for it in items]
    db.commit()
    for r in rows:
        db.refresh(r)
    return rows


def list_proposals(db: Session, status: str | None = "pending", kind: str | None = None, company: str | None = None, limit: int = 200) -> list[dict]:
    stmt = select(KnowledgeProposal)
    if status and status != "all":
        stmt = stmt.where(KnowledgeProposal.status == status)
    if kind:
        stmt = stmt.where(KnowledgeProposal.kind == kind)
    rows = db.execute(stmt.order_by(KnowledgeProposal.created_at.desc(), KnowledgeProposal.id.desc()).limit(limit if not company else 5000)).scalars().all()
    if company:
        cid = company.upper()
        rows = [r for r in rows if cid in (r.company_ids or [])][:limit]
    return [to_dict(r) for r in rows]


def counts(db: Session) -> dict:
    rows = db.execute(select(KnowledgeProposal.status, func.count()).group_by(KnowledgeProposal.status)).all()
    return {s: n for s, n in rows}


def _apply(db: Session, r: KnowledgeProposal, by: str) -> str:
    p = dict(r.payload)
    p.setdefault("source", r.source)
    p.setdefault("confidence", r.confidence)
    p["created_by"] = r.created_by if r.created_by and not r.created_by.startswith("user:") else by
    # companies named inside an edge / brief proposal are created first so the reviewer approves one thing
    for c in p.pop("companies", None) or []:
        if isinstance(c, dict) and c.get("id"):
            kn.upsert_company(db, {**c, "created_by": p["created_by"], "source": c.get("source") or r.source})
    if r.kind == "company":
        return f"knowledge_companies:{kn.upsert_company(db, p).id}"
    if r.kind == "edge":
        return f"knowledge_edges:{kn.upsert_edge(db, p).id}"
    if r.kind == "edge_weight":
        w = kn.add_edge_weight(db, int(p["edge_id"]), p)
        return f"knowledge_edge_weights:{w.id}"
    if r.kind == "brief":
        return f"knowledge_company_briefs:{kn.add_brief(db, p).id}"
    if r.kind == "metric":
        return f"knowledge_metrics:{kn.upsert_metric(db, p).id}"
    if r.kind == "financial":
        return f"knowledge_financials_ytd:{kn.upsert_financial(db, p).id}"
    raise ValueError(r.kind)


def decide(db: Session, proposal_id: int, approve: bool, user: User, note: str | None = None) -> KnowledgeProposal:
    r = db.get(KnowledgeProposal, proposal_id)
    if r is None:
        raise LookupError(str(proposal_id))
    if r.status != "pending":
        raise ValueError(f"proposal {proposal_id} is already {r.status}")
    r.decided_at, r.decided_by, r.note = datetime.now(), user.id, note
    if not approve:
        r.status = "rejected"
        db.commit()
        return r
    try:
        r.applied_ref = _apply(db, r, f"user:{user.username}")
        r.status = "approved"
    except (ValueError, LookupError) as e:
        db.rollback()
        r = db.get(KnowledgeProposal, proposal_id)
        r.status, r.note, r.decided_at, r.decided_by = "failed", f"{type(e).__name__}: {e}", datetime.now(), user.id
    db.commit()
    db.refresh(r)
    return r


def decide_many(db: Session, ids: list[int], approve: bool, user: User, note: str | None = None) -> dict:
    out = {"approved": 0, "rejected": 0, "failed": 0, "skipped": 0, "errors": {}}
    for pid in ids:
        try:
            r = decide(db, pid, approve, user, note)
            out[r.status] += 1
            if r.status == "failed":
                out["errors"][pid] = r.note
        except (LookupError, ValueError) as e:
            out["skipped"] += 1
            out["errors"][pid] = str(e)
    return out


def pending_edge_pairs(db: Session) -> set[tuple[str, str]]:
    """Existing + pending edge pairs, so extractors do not re-propose known relations."""
    pairs = {(e.customer_id, e.supplier_id) for e in db.execute(select(Edge)).scalars()}
    for r in db.execute(select(KnowledgeProposal).where(KnowledgeProposal.kind == "edge", KnowledgeProposal.status == "pending")).scalars():
        pairs.add((str(r.payload.get("customer_id", "")).upper(), str(r.payload.get("supplier_id", "")).upper()))
    return pairs


def propose_seed(db: Session, spec: dict, user: User | None = None) -> dict:
    """Queue a curated seed file: companies, profile briefs and edges, as proposals. Edges carry the
    company rows they need so they can be approved in any order. Returns counts by kind."""
    by = spec.get("created_by") or (f"user:{user.username}" if user else "agent")
    default_source = spec.get("default_source")
    companies = {str(c["id"]).upper(): c for c in spec.get("companies") or [] if c.get("id")}
    items: list[dict] = []
    for c in companies.values():
        items.append({"kind": "company", "payload": {**c, "id": str(c["id"]).upper()}, "source": c.get("source") or default_source, "confidence": c.get("confidence") or "high", "created_by": by, "rationale": c.get("rationale") or "成分股 / 供應鏈節點"})
    today = date.today().isoformat()
    for p in spec.get("profiles") or []:
        items.append({"kind": "brief", "payload": {"company_id": str(p["company_id"]).upper(), "kind": "profile", "content": p["content"], "date": p.get("date") or today, "sources": p.get("sources") or ([{"title": default_source}] if default_source else [])},
                      "source": p.get("source") or default_source, "confidence": p.get("confidence") or "medium", "created_by": by, "rationale": p.get("rationale") or "公司簡介"})
    for e in spec.get("edges") or []:
        payload = {k: v for k, v in e.items() if k not in ("rationale", "evidence", "confidence", "source")}
        payload["customer_id"] = str(payload["customer_id"]).upper()
        payload["supplier_id"] = str(payload["supplier_id"]).upper()
        payload.setdefault("relation", "customer")
        payload["source"] = e.get("source") or default_source
        needed = [companies[cid] for cid in (payload["customer_id"], payload["supplier_id"]) if cid in companies]
        if needed:
            payload["companies"] = [{**c, "id": str(c["id"]).upper()} for c in needed]
        items.append({"kind": "edge", "payload": payload, "source": payload["source"], "confidence": e.get("confidence") or "medium", "created_by": by,
                      "rationale": e.get("rationale") or e.get("notes") or e.get("source") or "", "evidence": e.get("evidence") or []})
    rows = propose_many(db, items, user)
    out: dict[str, int] = {}
    for r in rows:
        out[r.kind] = out.get(r.kind, 0) + 1
    return out
