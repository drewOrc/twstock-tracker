"""ETF constituents -> `holding` edges in the knowledge graph.

An ETF is a company node with sector "ETF"; each constituent is an edge
customer = constituent, supplier = fund, relation = holding, revenue_share = portfolio weight (0..1),
with the weight history kept in knowledge_edge_weights. Holdings are published facts, so they are
written directly (created_by system:etf) with the page they came from as source.

TW funds are read from MoneyDJ's full holdings page (names + weights; codes resolved through the
exchange master list). Any fund can also be loaded from rows you supply (apply_holdings), which is
how US funds such as VOO get in.
"""
from __future__ import annotations

import logging
import re
from datetime import date

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Company, Edge, Stock
from . import knowledge as kn
from . import knowledge_jobs

log = logging.getLogger(__name__)
CREATED_BY = "system:etf"
MONEYDJ_URL = "https://www.moneydj.com/etf/x/basic/basic0007a.xdjhtm?etfid={etfid}"

_ROW = re.compile(
    r'<td class="col05">(?P<name>[^<]+)</td>\s*<td class="col06">(?P<shares>[^<]*)</td>\s*<td class="col07">(?P<weight>[^<]*)</td>',
    re.S,
)
_DATE = re.compile(r"sdate3[^>]*>資料日期：(\d{4})/(\d{2})/(\d{2})")


def parse_moneydj(html: str) -> tuple[list[dict], date | None]:
    """Rows of {name, shares_k, weight_pct} and the holdings data date from the full-holdings page."""
    rows = []
    for m in _ROW.finditer(html):
        name = m.group("name").strip().rstrip("*").strip()
        try:
            weight = float(m.group("weight").replace(",", ""))
        except ValueError:
            continue
        shares = m.group("shares").replace(",", "").strip()
        rows.append({"name": name, "weight_pct": weight, "shares_k": float(shares) if shares else None})
    dm = _DATE.search(html)
    d = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3))) if dm else None
    return rows, d


def fetch_moneydj(etfid: str) -> tuple[list[dict], date | None, str]:
    url = MONEYDJ_URL.format(etfid=f"{etfid.lower()}.tw" if not etfid.lower().endswith(".tw") else etfid.lower())
    r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 (twstock-tracker)"}, timeout=30, follow_redirects=True)
    r.raise_for_status()
    rows, d = parse_moneydj(r.text)
    return rows, d, url


def resolve_tw_codes(db: Session, names: list[str]) -> dict[str, str]:
    """Exchange-list name -> code. Names on the ETF page match the master list exactly in practice."""
    clean = {n.rstrip("*").strip() for n in names}
    # the master list itself may carry a trailing "*" (e.g. 國巨* after a stock split notice)
    found = {s.name.rstrip("*").strip(): s.code for s in db.execute(select(Stock).where(or_(Stock.name.in_(clean), Stock.name.in_({c + "*" for c in clean})))).scalars()}
    return {n: found[n.rstrip("*").strip()] for n in names if n.rstrip("*").strip() in found}


def apply_holdings(db: Session, fund_id: str, rows: list[dict], as_of: date, source: str, fund_name: str | None = None, prune: bool = True) -> dict:
    """rows: {company_id | code | name, name?, weight_pct}. Creates missing nodes, upserts holding
    edges with the weight dated as_of, drops holding edges for constituents no longer listed."""
    fund_id = fund_id.upper()
    fund = db.get(Company, fund_id)
    if fund is None:
        market, ticker = fund_id.split(":", 1)
        name = fund_name or (db.get(Stock, ticker).name if market == "TW" and db.get(Stock, ticker) else ticker)
        kn.upsert_company(db, {"id": fund_id, "name": name, "sector": "ETF", "source": source, "created_by": CREATED_BY})
    elif fund.sector != "ETF":
        fund.sector = "ETF"
        db.commit()
    # resolve constituents
    tw_names = [r["name"] for r in rows if not r.get("company_id") and not r.get("code") and fund_id.startswith("TW:")]
    name_to_code = resolve_tw_codes(db, tw_names) if tw_names else {}
    resolved, unresolved = [], []
    for r in rows:
        cid = r.get("company_id")
        if not cid and r.get("code"):
            cid = kn.company_id_for(r["code"])
        if not cid and r.get("name") in name_to_code:
            cid = kn.company_id_for(name_to_code[r["name"]])
        if not cid:
            unresolved.append(r.get("name") or r.get("code"))
            continue
        resolved.append((cid.upper(), r))
    # nodes
    tw_codes = {cid.split(":", 1)[1] for cid, _ in resolved if cid.startswith("TW:")}
    if tw_codes:
        knowledge_jobs.sync_companies(db, tw_codes)
    for cid, r in resolved:
        if db.get(Company, cid) is None:
            kn.upsert_company(db, {"id": cid, "name": r.get("name") or cid.split(":", 1)[1], "name_en": r.get("name_en"), "sector": r.get("sector"), "source": source, "created_by": CREATED_BY})
    # edges
    kept = set()
    for cid, r in resolved:
        if cid == fund_id:
            continue
        share = round(float(r["weight_pct"]) / 100, 6)
        e = kn.upsert_edge(db, {"customer_id": cid, "supplier_id": fund_id, "relation": "holding", "revenue_share": share, "date": as_of,
                                "confidence": "high", "source": source, "created_by": CREATED_BY, "notes": f"{fund_id} 成分股權重 {r['weight_pct']}%（{as_of}）"})
        kept.add(e.id)
    removed = []
    if prune:
        for e in db.execute(select(Edge).where(Edge.supplier_id == fund_id, Edge.relation == "holding")).scalars().all():
            if e.id not in kept:
                removed.append(e.customer_id)
                db.delete(e)
        db.commit()
    return {"fund": fund_id, "as_of": as_of.isoformat(), "constituents": len(kept), "unresolved": unresolved, "removed": removed}


def refresh_tw_funds(db: Session, fund_ids: list[str] | None = None) -> dict:
    """Job: re-read every TW ETF node's holdings from MoneyDJ."""
    if fund_ids is None:
        fund_ids = [c.id for c in db.execute(select(Company).where(Company.market == "TW", Company.sector == "ETF")).scalars()]
    out = {}
    for fid in fund_ids:
        try:
            rows, d, url = fetch_moneydj(fid.split(":", 1)[1])
            if not rows or d is None:
                out[fid] = {"error": "no holdings table"}
                continue
            out[fid] = apply_holdings(db, fid, rows, d, url)
        except Exception as e:  # noqa: BLE001  one fund failing must not stop the others
            log.warning("etf holdings %s: %s", fid, e)
            out[fid] = {"error": f"{type(e).__name__}: {e}"}
    return out


def holdings(db: Session, fund_id: str) -> list[dict]:
    rows = db.execute(select(Edge).where(Edge.supplier_id == fund_id.upper(), Edge.relation == "holding").order_by(Edge.revenue_share.desc())).scalars().all()
    names = {c.id: c for c in db.execute(select(Company).where(Company.id.in_([e.customer_id for e in rows]))).scalars()}
    return [{"company_id": e.customer_id, "name": names[e.customer_id].name if e.customer_id in names else None, "sector": names[e.customer_id].sector if e.customer_id in names else None,
             "weight_pct": round((e.revenue_share or 0) * 100, 2), "updated_at": e.updated_at.isoformat(timespec="seconds") if e.updated_at else None} for e in rows]


def funds(db: Session) -> list[dict]:
    out = []
    for c in db.execute(select(Company).where(Company.sector == "ETF").order_by(Company.market, Company.ticker)).scalars():
        n = db.execute(select(Edge).where(Edge.supplier_id == c.id, Edge.relation == "holding")).scalars().all()
        out.append({"id": c.id, "name": c.name, "constituents": len(n)})
    return out
