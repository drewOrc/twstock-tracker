"""Industry value chains from TPEx 產業價值鏈資訊平台 (ic.tpex.org.tw).

The platform splits ~47 industries into upstream / midstream / downstream segments, many with
sub-segments, and lists the listed / OTC / emerging / foreign companies in each. That is official,
company-maintained classification, so the engine fetches it and writes it directly
(knowledge_chains / knowledge_chain_segments / knowledge_chain_members, created_by system:tpex-ic).

These are segment memberships, not company-to-company edges: "who sits next to whom" and
"which stage of which chain". The graph's customer -> supplier edges stay curated.
"""
from __future__ import annotations

import html as htmllib
import logging
import re
import time
from datetime import datetime

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import ChainMember, ChainSegment, Company, IndustryChain, Stock

log = logging.getLogger(__name__)
CREATED_BY = "system:tpex-ic"
BASE = "https://ic.tpex.org.tw/"
INDEX_URL = BASE + "introduce.php?ic=D000"
CHAIN_URL = BASE + "introduce.php?ic={ic}"
UA = {"User-Agent": "Mozilla/5.0 (twstock-tracker)"}
STAGES = ("上游", "中游", "下游")

_OPTION = re.compile(r"<option value='([A-Z0-9]{4})'\s*[^>]*>([^<]+)</option>")
_TITLE = re.compile(r"<h3>(.+?)產業鏈簡介</h3>")
_STAGE = re.compile(r'<div class="chain-title-panel">\s*([^<]+?)\s*</div>')
_LINK = re.compile(r'<div id="ic_link_([A-Z0-9]{4})"[^>]*>(.*?)</div>', re.S)
_LIST = re.compile(r'<div id="companyList_([A-Z0-9]{4})" title="([^"]*)"')
_SUBLINK = re.compile(r'<div id="sc_link_([A-Z0-9]{4})"[^>]*>.*?&nbsp;(.+?)&nbsp;\(\d+家\)</div>', re.S)
_SUBTABLE = re.compile(r'<table id="sc_company_([A-Z0-9]{4})"')
_TOKEN = re.compile(r"<b>([^<(]+?)\s*\(\d+家\)</b>|<a href=\"([^\"]+)\"[^>]*title=\"([^\"]*)\"")
_CODE = re.compile(r"stk_code=([0-9A-Z]+)")


def _text(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", htmllib.unescape(s)).strip()


def _listing(header: str) -> str:
    h = header.strip()
    for key, out in (("知名外國", "外國企業"), ("外國上市", "外國上市"), ("外國上櫃", "外國上櫃"), ("上市", "上市"), ("上櫃", "上櫃"), ("興櫃", "興櫃"), ("創櫃", "創櫃"), ("創新", "創新板")):
        if key in h:
            return out
    return h[:16]


def parse_index(page: str) -> list[tuple[str, str]]:
    """(ic, name) for every industry in the selector."""
    sel = page[page.find("ic_option"):]
    sel = sel[: sel.find("</select>")]
    seen, out = set(), []
    for ic, name in _OPTION.findall(sel):
        if ic not in seen:
            seen.add(ic)
            out.append((ic, _text(name)))
    return out


def _members(chunk: str) -> list[dict]:
    out, listing = [], None
    for m in _TOKEN.finditer(chunk):
        if m.group(1):
            listing = _listing(m.group(1))
            continue
        href, name = m.group(2), _text(m.group(3))
        if not name:
            continue
        code = _CODE.search(href)
        if code and "company_basic" in href:
            out.append({"code": code.group(1), "name": name, "listing": listing or "上市", "url": None})
        elif href.startswith("http"):
            out.append({"code": None, "name": name, "listing": listing or "外國企業", "url": href})
    return out


def parse_chain(ic: str, page: str) -> dict:
    """{id, name, intro, segments[{id, parent_id, name, stage, sort, members[]}]}."""
    t = _TITLE.search(page)
    name = _text(t.group(1)) if t else ic
    intro = ""
    i = page.find('id="intro-content"')
    if i >= 0:
        j = page.find(">", i)
        k = page.find("</div>", j)
        intro = _text(page[j + 1 : k])[:4000]
    # stage of each top-level segment: the chain-title-panel that precedes its ic_link
    panel_start = page.find('id="main_ic_panel"')
    panel_end = page.find('id="companyList_', panel_start) if panel_start >= 0 else -1
    panel = page[panel_start:panel_end] if panel_start >= 0 else ""
    stage_marks = [(m.start(), _text(m.group(1))) for m in _STAGE.finditer(panel)]
    seg_stage, seg_name, order = {}, {}, []
    for m in _LINK.finditer(panel):
        sid = m.group(1)
        st = None
        for pos, label in stage_marks:
            if pos < m.start():
                st = label
        seg_stage[sid] = st if st in STAGES else (st or None)
        seg_name.setdefault(sid, _text(m.group(2)))
        if sid not in order:
            order.append(sid)
    # company lists, one block per top-level segment
    blocks = list(_LIST.finditer(page))
    segments: list[dict] = []
    seen_blocks: set[str] = set()
    for n, m in enumerate(blocks):
        sid, title = m.group(1), _text(m.group(2))
        if sid in seen_blocks:  # some pages render the lists twice
            continue
        seen_blocks.add(sid)
        end = blocks[n + 1].start() if n + 1 < len(blocks) else len(page)
        chunk = page[m.end() : end]
        top = {"id": sid, "parent_id": None, "name": title or seg_name.get(sid, sid), "stage": seg_stage.get(sid),
               "sort": order.index(sid) if sid in order else 100 + n, "members": []}
        segments.append(top)
        subs = {s.group(1): _text(s.group(2)) for s in _SUBLINK.finditer(chunk)}
        tables = list(_SUBTABLE.finditer(chunk))
        if tables:
            for k, tm in enumerate(tables):
                sub_id = tm.group(1)
                t_end = tables[k + 1].start() if k + 1 < len(tables) else len(chunk)
                segments.append({"id": sub_id, "parent_id": sid, "name": subs.get(sub_id, sub_id), "stage": top["stage"],
                                 "sort": k, "members": _members(chunk[tm.start() : t_end])})
        else:
            top["members"] = _members(chunk)
    return {"id": ic, "name": name, "intro": intro, "segments": segments}


def _get(url: str) -> str:
    r = httpx.get(url, headers=UA, timeout=40, follow_redirects=True)
    r.raise_for_status()
    return r.text


def apply_chain(db: Session, chain: dict, source_url: str | None = None) -> dict:
    """Replace one chain's segments and members with what was parsed."""
    cid = chain["id"]
    known = {r[0] for r in db.execute(select(Stock.code)).all()}
    c = db.get(IndustryChain, cid) or IndustryChain(id=cid)
    c.name, c.intro, c.source_url, c.fetched_at = chain["name"], chain.get("intro") or None, source_url or CHAIN_URL.format(ic=cid), datetime.now()
    db.add(c)
    db.execute(delete(ChainMember).where(ChainMember.chain_id == cid))
    db.execute(delete(ChainSegment).where(ChainSegment.chain_id == cid))
    db.flush()
    n_members, tw = 0, set()
    for s in chain["segments"]:
        db.add(ChainSegment(chain_id=cid, code=s["id"], parent_code=s["parent_id"], name=s["name"][:128], stage=s["stage"], sort=s["sort"]))
        seen = set()
        for m in s["members"]:
            key = m["code"] or m["name"]
            if key in seen:
                continue
            seen.add(key)
            company_id = f"TW:{m['code']}" if m["code"] else None
            db.add(ChainMember(chain_id=cid, segment_code=s["id"], company_id=company_id, name=m["name"][:128], listing=m["listing"], url=(m["url"] or None) and m["url"][:256],
                               listed=bool(m["code"] and m["code"] in known)))
            n_members += 1
            if m["code"]:
                tw.add(m["code"])
    db.commit()
    return {"chain": cid, "name": chain["name"], "segments": len(chain["segments"]), "members": n_members, "tw_companies": len(tw)}


def refresh(db: Session, ics: list[str] | None = None, pause: float = 1.0) -> dict:
    """Job: fetch the industry list, then every chain page (polite, one request per second)."""
    index = parse_index(_get(INDEX_URL))
    if ics:
        wanted = {i.upper() for i in ics}
        index = [(ic, n) for ic, n in index if ic in wanted]
    out, errors = [], {}
    for k, (ic, _name) in enumerate(index):
        if k:
            time.sleep(pause)
        try:
            out.append(apply_chain(db, parse_chain(ic, _get(CHAIN_URL.format(ic=ic)))))
        except Exception as e:  # noqa: BLE001  one page failing must not stop the rest
            db.rollback()
            log.warning("industry chain %s: %s", ic, e)
            errors[ic] = f"{type(e).__name__}: {e}"
    return {"chains": len(out), "members": sum(o["members"] for o in out), "errors": errors}


# ------------------------------------------------------------------ reads
def chains(db: Session) -> list[dict]:
    counts = dict(db.execute(select(ChainMember.chain_id, func.count(func.distinct(ChainMember.company_id))).group_by(ChainMember.chain_id)).all())
    return [{"id": c.id, "name": c.name, "companies": counts.get(c.id, 0), "fetched_at": c.fetched_at.isoformat(timespec="seconds") if c.fetched_at else None}
            for c in db.execute(select(IndustryChain).order_by(IndustryChain.id)).scalars()]


def chain_detail(db: Session, chain_id: str) -> dict | None:
    c = db.get(IndustryChain, chain_id.upper())
    if c is None:
        return None
    segs = db.execute(select(ChainSegment).where(ChainSegment.chain_id == c.id).order_by(ChainSegment.id)).scalars().all()
    members = db.execute(select(ChainMember).where(ChainMember.chain_id == c.id).order_by(ChainMember.id)).scalars().all()
    in_graph = _in_graph(db, {m.company_id for m in members if m.company_id})
    by_seg: dict[str, list[dict]] = {}
    for m in members:
        by_seg.setdefault(m.segment_code, []).append(_member(m, in_graph))
    tree = []
    tops = [s for s in segs if not s.parent_code]
    tops.sort(key=lambda s: (STAGES.index(s.stage) if s.stage in STAGES else 9, s.sort))
    for s in tops:
        children = sorted([x for x in segs if x.parent_code == s.code], key=lambda x: x.sort)
        tree.append({"code": s.code, "name": s.name, "stage": s.stage, "members": by_seg.get(s.code, []),
                     "children": [{"code": x.code, "name": x.name, "members": by_seg.get(x.code, [])} for x in children]})
    return {"id": c.id, "name": c.name, "intro": c.intro, "source_url": c.source_url,
            "fetched_at": c.fetched_at.isoformat(timespec="seconds") if c.fetched_at else None, "segments": tree}


def _in_graph(db: Session, ids: set[str]) -> set[str]:
    if not ids:
        return set()
    return {r[0] for r in db.execute(select(Company.id).where(Company.id.in_(ids))).all()}


def _member(m: ChainMember, in_graph: set[str]) -> dict:
    return {"company_id": m.company_id, "code": m.company_id.split(":", 1)[1] if m.company_id else None, "name": m.name,
            "listing": m.listing, "url": m.url, "in_graph": m.company_id in in_graph if m.company_id else False}


def for_company(db: Session, company_id: str, peers_limit: int = 30) -> list[dict]:
    """Where a company sits: every (chain, segment) it is listed in, with the other companies there."""
    cid = company_id.upper()
    rows = db.execute(select(ChainMember).where(ChainMember.company_id == cid)).scalars().all()
    if not rows:
        return []
    chain_names = {c.id: c.name for c in db.execute(select(IndustryChain).where(IndustryChain.id.in_({r.chain_id for r in rows}))).scalars()}
    segs = {(s.chain_id, s.code): s for s in db.execute(select(ChainSegment).where(ChainSegment.chain_id.in_({r.chain_id for r in rows}))).scalars()}
    out = []
    for r in rows:
        s = segs.get((r.chain_id, r.segment_code))
        parent = segs.get((r.chain_id, s.parent_code)) if s and s.parent_code else None
        peers = db.execute(select(ChainMember).where(ChainMember.chain_id == r.chain_id, ChainMember.segment_code == r.segment_code,
                                                     ChainMember.id != r.id).order_by(ChainMember.id)).scalars().all()
        in_graph = _in_graph(db, {p.company_id for p in peers if p.company_id})
        # TW peers first, then foreign names
        peers.sort(key=lambda p: (p.company_id is None, p.id))
        out.append({"chain_id": r.chain_id, "chain": chain_names.get(r.chain_id, r.chain_id), "stage": s.stage if s else None,
                    "segment_code": r.segment_code, "segment": s.name if s else r.segment_code, "parent": parent.name if parent else None,
                    "peers_total": len(peers), "peers": [_member(p, in_graph) for p in peers[:peers_limit]]})
    out.sort(key=lambda x: (x["chain_id"], x["segment_code"]))
    return out


def stats(db: Session) -> dict:
    return {"chains": db.scalar(select(func.count()).select_from(IndustryChain)) or 0,
            "segments": db.scalar(select(func.count()).select_from(ChainSegment)) or 0,
            "members": db.scalar(select(func.count()).select_from(ChainMember)) or 0,
            "tw_companies": db.scalar(select(func.count(func.distinct(ChainMember.company_id))).where(ChainMember.company_id.is_not(None))) or 0,
            "fetched_at": (lambda d: d.isoformat(timespec="seconds") if d else None)(db.scalar(select(func.max(IndustryChain.fetched_at))))}
