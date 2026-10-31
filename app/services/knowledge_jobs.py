"""Jobs that grow the knowledge layer without a human:

- sync_companies: every TW stock anyone tracks (watchlists, CRM cards, screener picks) gets a graph
  node, named and sectored from the exchange master list. Official data -> written directly.
- revenue_highlights: after the monthly-revenue fetch, one dated "近期重點" per company built from the
  numbers and the company's own remark on the filing. Derived from official data -> written directly,
  created_by system:mops, never more than one per company per month.
- todo: what still needs a human or an LLM (missing profile, stale highlights, isolated nodes, edges
  without a source). The extractor and agent sessions work off this list.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import Company, CompanyBrief, Edge, MetricActual, Stock, WatchlistItem
from . import knowledge as kn
from .industries import is_common_stock, sector_name

SYSTEM = "system:engine"


# ---------------------------------------------------------------- nodes
def sync_companies(db: Session, codes: set[str] | None = None) -> dict:
    """Ensure a knowledge_companies row for each tracked TW code (or the given codes)."""
    if codes is None:
        codes = set(db.execute(select(WatchlistItem.code).distinct()).scalars())
        codes |= {c.ticker for c in db.execute(select(Company).where(Company.market == "TW")).scalars()}
    created, updated = [], []
    for code in sorted(codes):
        stock = db.get(Stock, code)
        if stock is None:
            continue
        cid = kn.company_id_for(code)
        existing = db.get(Company, cid)
        sector = "ETF" if not is_common_stock(code) else sector_name(code, stock.industry)
        data = {"id": cid, "name": stock.name or code, "source": "TWSE/TPEx company list", "created_by": SYSTEM}
        if getattr(stock, "name_en", None):
            data["name_en"] = stock.name_en
        if existing is None:
            data["sector"] = sector
            kn.upsert_company(db, data)
            created.append(cid)
        else:
            changed = False
            if not existing.sector and sector:
                existing.sector = sector
                changed = True
            if existing.name_en is None and data.get("name_en"):
                existing.name_en = data["name_en"]
                changed = True
            if changed:
                db.commit()
                updated.append(cid)
    return {"created": created, "updated": updated, "checked": len(codes)}


# ---------------------------------------------------------------- highlights from official numbers
def _fmt_amount(thousands: float) -> str:
    yi = thousands / 100_000  # 千元 -> 億元
    return f"{yi:,.1f} 億" if yi >= 1 else f"{thousands / 1000:,.0f} 百萬"


def revenue_highlights(db: Session, period: str | None = None) -> dict:
    """One highlights brief per TW company for the latest monthly-revenue period."""
    if period is None:
        period = db.execute(select(func.max(MetricActual.period)).where(MetricActual.metric == "revenue_m")).scalar()
    if not period:
        return {"skipped": "no monthly revenue yet"}
    y, m = int(period[:4]), int(period[5:7])
    prev_m = f"{y}-{m - 1:02d}" if m > 1 else f"{y - 1}-12"
    last_y = f"{y - 1}-{m:02d}"
    brief_date = date(y, m, 1) + timedelta(days=31)
    brief_date = brief_date.replace(day=1) - timedelta(days=1)  # month end
    written, skipped = [], []
    rows = db.execute(select(MetricActual).where(MetricActual.metric == "revenue_m", MetricActual.period == period)).scalars().all()
    for cur in rows:
        exists = db.execute(
            select(CompanyBrief).where(CompanyBrief.company_id == cur.company_id, CompanyBrief.kind == "highlights", CompanyBrief.date == brief_date, CompanyBrief.created_by == "system:mops")
        ).scalar_one_or_none()
        if exists:
            skipped.append(cur.company_id)
            continue
        vals = {r.period: r.value for r in db.execute(select(MetricActual).where(MetricActual.company_id == cur.company_id, MetricActual.metric == "revenue_m", MetricActual.period.in_([prev_m, last_y]))).scalars()}
        parts = [f"{y} 年 {m} 月營收 {_fmt_amount(cur.value)}"]
        if vals.get(last_y):
            parts.append(f"年增 {((cur.value / vals[last_y]) - 1) * 100:+.1f}%")
        if vals.get(prev_m):
            parts.append(f"月增 {((cur.value / vals[prev_m]) - 1) * 100:+.1f}%")
        # the latest 12 months on file, to say whether this is a record
        hist = db.execute(select(MetricActual.value).where(MetricActual.company_id == cur.company_id, MetricActual.metric == "revenue_m", MetricActual.period < period).order_by(MetricActual.period.desc()).limit(12)).scalars().all()
        if len(hist) >= 6 and cur.value > max(hist):
            parts.append("為近一年新高")
        text = "，".join(parts) + "。（證交所 / 櫃買月營收公告）"
        kn.add_brief(db, {"company_id": cur.company_id, "kind": "highlights", "date": brief_date, "content": text,
                          "sources": [{"title": "月營收公告", "url": cur.source, "date": brief_date.isoformat()}], "created_by": "system:mops"})
        written.append(cur.company_id)
    return {"period": period, "written": written, "skipped_existing": len(skipped)}


# ---------------------------------------------------------------- what still needs a brain
def todo(db: Session, stale_days: int = 45, limit: int = 100) -> dict:
    now = datetime.now()
    companies = db.execute(select(Company).order_by(Company.market, Company.ticker)).scalars().all()
    profile_ids = set(db.execute(select(CompanyBrief.company_id).where(CompanyBrief.kind == "profile").distinct()).scalars())
    latest_hl = dict(db.execute(select(CompanyBrief.company_id, func.max(CompanyBrief.date)).where(CompanyBrief.kind == "highlights").group_by(CompanyBrief.company_id)).all())
    edge_ids = set(db.execute(select(Edge.customer_id)).scalars()) | set(db.execute(select(Edge.supplier_id)).scalars())
    missing_profile = [{"id": c.id, "name": c.name} for c in companies if c.id not in profile_ids]
    stale = []
    for c in companies:
        d = latest_hl.get(c.id)
        if d is None or (now.date() - d).days > stale_days:
            stale.append({"id": c.id, "name": c.name, "latest": d.isoformat() if d else None})
    isolated = [{"id": c.id, "name": c.name} for c in companies if c.id not in edge_ids and c.sector != "ETF"]
    unsourced = [kn.edge_dict(e) for e in db.execute(select(Edge).where(or_(Edge.source.is_(None), Edge.source == ""))).scalars()]
    return {
        "companies": len(companies),
        "missing_profile": missing_profile[:limit],
        "stale_highlights": stale[:limit],
        "isolated_companies": isolated[:limit],
        "edges_without_source": unsourced[:limit],
        "total": len(missing_profile) + len(stale) + len(isolated) + len(unsourced),
    }
