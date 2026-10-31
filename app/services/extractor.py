"""LLM extractor: turns the knowledge layer's todo list into proposals.

For each company that lacks a profile or has stale highlights, it reads the engine's own context
(exchange profile, latest numbers, recent headlines) and asks Claude for a short profile, dated
highlights and any customer / supplier relations the material supports. Everything it produces goes
into knowledge_proposals with confidence and evidence; nothing is written to knowledge_* until an
admin approves. Runs only when the Anthropic SDK is installed and credentials are configured
(ANTHROPIC_API_KEY or an `ant auth login` profile); otherwise the job reports "skipped".
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Company
from . import knowledge as kn
from . import knowledge_jobs, stock_summary
from . import knowledge_proposals as kp

log = logging.getLogger(__name__)
CREATED_BY = "agent:claude-extractor"

SYSTEM = """你是台股供應鏈研究助理，為一個共用的「知識層」資料庫產生可審核的提案。只根據提供的材料與你確知的公開事實作答，不確定就降低信心度或省略。
輸出 JSON（不要加任何說明文字）：
{
  "profile": "公司在做什麼、主要產品與客戶，80 字內；若材料不足回 null",
  "highlights": "近期重點：最近營收、重大新聞、產能或客戶變化，120 字內，帶日期；若材料不足回 null",
  "edges": [
    {"customer_id": "US:NVDA", "supplier_id": "TW:2330", "relation": "customer|partner", "revenue_share": 0.15 或 null,
     "confidence": "high|medium|low", "evidence": "一句話說明依據（引用材料中的標題或事實）"}
  ]
}
公司 id 格式為 市場:代號，台股用 TW:代號、美股用 US:代號；只提出與目前這家公司直接相關的關係；revenue_share 是客戶佔供應商營收的比重（0..1），沒有依據就填 null。"""


def available() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(settings.anthropic_api_key) or True  # the SDK also resolves `ant auth login` profiles


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=settings.anthropic_api_key or None)


def _material(db: Session, c: Company) -> dict:
    """What the model gets to read: exchange profile, numbers, graph neighbours, headlines."""
    code = c.ticker if c.market == "TW" else None
    out: dict = {"company": kn.company_dict(c), "known_edges": kn.edges_for(db, c.id), "briefs": kn.latest_briefs(db, c.id)}
    if code:
        try:
            s = stock_summary.stock_summary(db, code, with_news=True)
            out["profile"] = s.get("profile")
            out["price"] = {k: s["price"].get(k) for k in ("as_of", "close", "returns", "relative") if s.get("price", {}).get("available")}
            out["news"] = (s.get("news") or {}).get("items", [])[:10]
        except Exception as e:  # noqa: BLE001
            out["summary_error"] = str(e)
    out["metrics"] = kn.list_metrics(db, c.id)[:12]
    return out


def _parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in model output")
    return json.loads(m.group(0))


def extract_company(db: Session, c: Company, client=None) -> dict:
    client = client or _client()
    material = _material(db, c)
    resp = client.messages.create(
        model=settings.extractor_model,
        max_tokens=4096,
        system=SYSTEM,
        messages=[{"role": "user", "content": f"目標公司：{c.id} {c.name}\n今天：{date.today().isoformat()}\n材料（JSON）：\n{json.dumps(material, ensure_ascii=False, default=str)[:60000]}"}],
    )
    if resp.stop_reason == "refusal":
        return {"company": c.id, "skipped": "refusal"}
    text = "".join(b.text for b in resp.content if b.type == "text")
    data = _parse_json(text)
    items: list[dict] = []
    src = f"LLM 抽取（{settings.extractor_model}）自引擎材料：公司基本資料、月營收、Google News 標題"
    evidence = [{"title": n.get("title"), "url": n.get("link"), "date": n.get("published")} for n in material.get("news", [])[:5]]
    if data.get("profile"):
        items.append({"kind": "brief", "payload": {"company_id": c.id, "kind": "profile", "content": data["profile"], "date": date.today().isoformat(), "sources": evidence}, "source": src, "confidence": "medium", "created_by": CREATED_BY, "rationale": "沒有公司簡介", "evidence": evidence})
    if data.get("highlights"):
        items.append({"kind": "brief", "payload": {"company_id": c.id, "kind": "highlights", "content": data["highlights"], "date": date.today().isoformat(), "sources": evidence}, "source": src, "confidence": "medium", "created_by": CREATED_BY, "rationale": "近期重點過期", "evidence": evidence})
    known = kp.pending_edge_pairs(db)
    for e in data.get("edges") or []:
        try:
            cust, supp = str(e["customer_id"]).upper(), str(e["supplier_id"]).upper()
        except (KeyError, TypeError):
            continue
        if (cust, supp) in known or cust == supp:
            continue
        payload = {"customer_id": cust, "supplier_id": supp, "relation": e.get("relation") or "customer", "revenue_share": e.get("revenue_share"), "source": src}
        items.append({"kind": "edge", "payload": payload, "source": src, "confidence": e.get("confidence") if e.get("confidence") in kn.CONFIDENCES else "low", "created_by": CREATED_BY,
                      "rationale": e.get("evidence") or "", "evidence": evidence})
    rows = kp.propose_many(db, items) if items else []
    return {"company": c.id, "proposals": len(rows), "usage": {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens}}


def run(db: Session, limit: int | None = None) -> dict:
    """Job: work through the todo list (missing profile first, then stale highlights)."""
    if not available():
        return {"skipped": "anthropic SDK not installed"}
    if not settings.extractor_enabled:
        return {"skipped": "EXTRACTOR_ENABLED is false"}
    todo = knowledge_jobs.todo(db, limit=10000)
    ids: list[str] = []
    for r in todo["missing_profile"] + todo["stale_highlights"]:
        if r["id"] not in ids:
            ids.append(r["id"])
    ids = ids[: limit or settings.extractor_batch]
    if not ids:
        return {"done": 0, "note": "nothing to do"}
    client = _client()
    results, errors = [], {}
    for cid in ids:
        c = db.get(Company, cid)
        if c is None or c.sector == "ETF":
            continue
        try:
            results.append(extract_company(db, c, client))
        except Exception as e:  # noqa: BLE001  one company must not stop the batch
            log.warning("extractor %s: %s", cid, e)
            errors[cid] = f"{type(e).__name__}: {e}"
    return {"done": len(results), "proposals": sum(r.get("proposals", 0) for r in results), "errors": errors,
            "tokens": {"in": sum(r.get("usage", {}).get("in", 0) for r in results), "out": sum(r.get("usage", {}).get("out", 0) for r in results)}}


def companies_without_profile(db: Session) -> list[Company]:
    ids = {r["id"] for r in knowledge_jobs.todo(db, limit=10000)["missing_profile"]}
    return [c for c in db.execute(select(Company).where(Company.id.in_(ids))).scalars()]
