"""Official company facts from TWSE / TPEx open data (no API key): monthly revenue, quarterly income
statement (year-to-date), shares outstanding -> knowledge_metrics / knowledge_financials_ytd.

Ported from the Stock CRM's mops.py when the knowledge layer moved into the shared database: the
engine is the only writer of those tables, so it fetches them too. Pure parsers take raw JSON rows
and are tested offline; apply_* write with created_by='system:mops' and the source URL. Official
facts bypass proposals: there is nothing for a human to judge and they can always be re-fetched.

Units: revenue / costs in thousands of TWD; gross_margin 0..1; shares stored in thousands.
"""
from __future__ import annotations

import json
import ssl
import subprocess
import urllib.error
import urllib.request
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import Company, FinancialYTD
from . import knowledge as kn

CREATED_BY = "system:mops"
USER_AGENT = "twstock-tracker/0.5"

URLS = {
    "monthly_listed": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
    "monthly_otc": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O",
    "quarterly_listed": "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci",
    "quarterly_otc": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci",
    "shares_listed": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    "shares_otc": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
}


# ---------------------------------------------------------------- http
def get_json(url: str, timeout: int = 30) -> list[dict]:
    """GET JSON. Falls back to curl when the Python SSL store cannot verify the chain
    (seen on Windows Store Python behind inspection proxies)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (ssl.SSLError, urllib.error.URLError) as e:
        if "CERTIFICATE_VERIFY_FAILED" not in str(e):
            raise
    out = subprocess.run(["curl", "-s", "-m", str(timeout), "-A", USER_AGENT, url], capture_output=True, check=True)
    return json.loads(out.stdout.decode("utf-8"))


def _num(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _roc_year(v) -> int:
    return int(str(v).strip()) + 1911


# ---------------------------------------------------------------- which companies
def tw_companies(db: Session) -> list[Company]:
    """Every TW company in the knowledge graph except ETFs (no revenue, no income statement)."""
    stmt = select(Company).where(Company.market == "TW", or_(Company.sector.is_(None), Company.sector != "ETF")).order_by(Company.ticker)
    return list(db.execute(stmt).scalars())


def _wanted(db: Session, tickers: set[str] | None) -> set[str]:
    return tickers if tickers is not None else {c.ticker for c in tw_companies(db)}


# ---------------------------------------------------------------- monthly revenue
def parse_monthly_rows(rows: list[dict]) -> list[dict]:
    """Normalise TWSE/TPEx monthly revenue rows (same schema on both)."""
    out = []
    for r in rows:
        ym = str(r.get("資料年月", "")).strip()
        ticker = str(r.get("公司代號", "")).strip()
        if len(ym) < 5 or not ticker:
            continue
        year, month = _roc_year(ym[:-2]), int(ym[-2:])
        out.append({
            "ticker": ticker, "name": (r.get("公司名稱") or "").strip(),
            "year": year, "month": month, "period": f"{year}-{month:02d}",
            "revenue": _num(r.get("營業收入-當月營收")),
            "revenue_prev_month": _num(r.get("營業收入-上月營收")),
            "revenue_last_year": _num(r.get("營業收入-去年當月營收")),
            "yoy_pct": _num(r.get("營業收入-去年同月增減(%)")),
            "remark": (r.get("備註") or "").strip().strip("-"),
            "published": str(r.get("出表日期", "")).strip(),
            "source": r.get("_source"),
        })
    return out


def fetch_monthly() -> list[dict]:
    rows: list[dict] = []
    for key in ("monthly_listed", "monthly_otc"):
        rows += [dict(r, _source=URLS[key]) for r in get_json(URLS[key])]
    return parse_monthly_rows(rows)


def apply_monthly(db: Session, parsed: list[dict], tickers: set[str] | None = None) -> dict:
    """Write revenue_m actuals for tracked TW companies. The API ships last month and the same month
    a year ago too, so YoY works from the first run."""
    wanted = _wanted(db, tickers)
    written, periods = [], []
    for row in parsed:
        if row["ticker"] not in wanted or row["revenue"] is None:
            continue
        cid = kn.company_id_for(row["ticker"])
        src = row.get("source") or URLS["monthly_listed"]
        kn.upsert_metric(db, {"company_id": cid, "metric": "revenue_m", "period": row["period"], "value": row["revenue"], "source": src, "created_by": CREATED_BY})
        if row["revenue_last_year"] is not None:
            kn.upsert_metric(db, {"company_id": cid, "metric": "revenue_m", "period": f"{row['year'] - 1}-{row['month']:02d}", "value": row["revenue_last_year"], "source": src, "created_by": CREATED_BY})
        if row["revenue_prev_month"] is not None:
            py, pm = (row["year"], row["month"] - 1) if row["month"] > 1 else (row["year"] - 1, 12)
            kn.upsert_metric(db, {"company_id": cid, "metric": "revenue_m", "period": f"{py}-{pm:02d}", "value": row["revenue_prev_month"], "source": src, "created_by": CREATED_BY})
        written.append({"company_id": cid, "period": row["period"], "revenue": row["revenue"], "yoy_pct": row["yoy_pct"], "remark": row["remark"]})
        periods.append(row["period"])
    missing = sorted(wanted - {w["company_id"].split(":")[1] for w in written})
    return {"written": written, "missing": missing, "latest_period": max(periods) if periods else None}


# ---------------------------------------------------------------- quarterly income statement (YTD)
def parse_quarterly_rows(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        ticker = str(r.get("公司代號") or r.get("SecuritiesCompanyCode") or "").strip()
        year = r.get("年度") or r.get("Year")
        q = r.get("季別") or r.get("Season")
        if not ticker or not year or not q:
            continue
        gp = _num(r.get("營業毛利（毛損）淨額"))
        ni = _num(r.get("淨利（淨損）歸屬於母公司業主"))
        out.append({
            "ticker": ticker, "year": _roc_year(year), "quarter": int(str(q).strip()),
            "revenue": _num(r.get("營業收入")),
            "gross_profit": gp if gp is not None else _num(r.get("營業毛利（毛損）")),
            "opex": _num(r.get("營業費用")),
            "net_income": ni if ni is not None else _num(r.get("本期淨利（淨損）")),
            "eps": _num(r.get("基本每股盈餘（元）")),
            "published": str(r.get("出表日期") or r.get("Date") or "").strip(),
            "source": r.get("_source"),
        })
    return out


def fetch_quarterly() -> list[dict]:
    rows: list[dict] = []
    for key in ("quarterly_listed", "quarterly_otc"):
        rows += [dict(r, _source=URLS[key]) for r in get_json(URLS[key])]
    return parse_quarterly_rows(rows)


def derive_quarterly_metrics(db: Session, company_id: str, year: int, quarter: int, created_by: str = CREATED_BY) -> dict:
    """Turn YTD figures into single-quarter metrics: Q1 as is; Qn = YTD(Qn) - YTD(Qn-1) when stored."""

    def ytd(q: int) -> FinancialYTD | None:
        return db.execute(select(FinancialYTD).where(FinancialYTD.company_id == company_id, FinancialYTD.year == year, FinancialYTD.quarter == q)).scalar_one_or_none()

    cur = ytd(quarter)
    if cur is None:
        return {"written": [], "reason": "no ytd row"}
    if quarter == 1:
        prev_vals = {"revenue": 0.0, "gross_profit": 0.0, "opex": 0.0, "eps": 0.0}
    else:
        prev = ytd(quarter - 1)
        if prev is None:
            return {"written": [], "reason": f"need YTD for Q{quarter - 1} {year} to difference; stored YTD only"}
        prev_vals = {k: getattr(prev, k) for k in ("revenue", "gross_profit", "opex", "eps")}

    def diff(k: str) -> float | None:
        a, b = getattr(cur, k), prev_vals[k]
        return None if a is None or b is None else a - b

    period = f"{year}Q{quarter}"
    written: list[str] = []

    def put(metric: str, value: float) -> None:
        kn.upsert_metric(db, {"company_id": company_id, "metric": metric, "period": period, "value": value, "source": cur.source, "created_by": created_by})
        written.append(metric)

    rev, gp, opex, eps = diff("revenue"), diff("gross_profit"), diff("opex"), diff("eps")
    if rev:
        put("revenue_q", rev)
        if gp is not None:
            put("gross_margin", round(gp / rev, 4))
    if opex is not None:
        put("opex", opex)
    if eps is not None:
        put("eps", round(eps, 2))
    return {"written": written, "period": period}


def apply_quarterly(db: Session, parsed: list[dict], tickers: set[str] | None = None) -> dict:
    wanted = _wanted(db, tickers)
    stored, derived, skipped = [], [], []
    for row in sorted((r for r in parsed if r["ticker"] in wanted), key=lambda r: (r["ticker"], r["year"], r["quarter"])):
        cid = kn.company_id_for(row["ticker"])
        kn.upsert_financial(db, {"company_id": cid, "year": row["year"], "quarter": row["quarter"], "revenue": row["revenue"], "gross_profit": row["gross_profit"],
                                 "opex": row["opex"], "net_income": row["net_income"], "eps": row["eps"], "source": row.get("source") or URLS["quarterly_listed"]})
        stored.append({"company_id": cid, "year": row["year"], "quarter": row["quarter"]})
        res = derive_quarterly_metrics(db, cid, row["year"], row["quarter"])
        (derived if res["written"] else skipped).append({"company_id": cid, **res})
    return {"stored": stored, "derived": derived, "skipped": skipped}


# ---------------------------------------------------------------- shares outstanding
def parse_shares_rows(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        ticker = str(r.get("公司代號") or r.get("SecuritiesCompanyCode") or "").strip()
        shares = _num(r.get("已發行普通股數或TDR原股發行股數") or r.get("已發行普通股數"))
        if ticker and shares:
            out.append({"ticker": ticker, "shares_thousands": shares / 1000.0, "published": str(r.get("出表日期") or r.get("Date") or "").strip(), "source": r.get("_source")})
    return out


def fetch_shares() -> list[dict]:
    parsed: list[dict] = []
    for key in ("shares_listed", "shares_otc"):
        try:
            rows = get_json(URLS[key])
        except Exception as e:  # noqa: BLE001  the OTC basic-info feed is less stable
            parsed.append({"_error": f"{key}: {e}"})
            continue
        parsed += parse_shares_rows([dict(r, _source=URLS[key]) for r in rows])
    return parsed


def current_quarter_period(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"{now.year}Q{(now.month - 1) // 3 + 1}"


def apply_shares(db: Session, parsed: list[dict], tickers: set[str] | None = None) -> dict:
    wanted = _wanted(db, tickers)
    period = current_quarter_period()
    written, errors = [], [p["_error"] for p in parsed if "_error" in p]
    for row in parsed:
        if "_error" in row or row["ticker"] not in wanted:
            continue
        cid = kn.company_id_for(row["ticker"])
        kn.upsert_metric(db, {"company_id": cid, "metric": "shares", "period": period, "value": round(row["shares_thousands"], 3), "source": row.get("source") or URLS["shares_listed"], "created_by": CREATED_BY})
        written.append({"company_id": cid, "period": period, "shares_thousands": row["shares_thousands"]})
    return {"written": written, "errors": errors}


# ---------------------------------------------------------------- jobs (fetch + apply)
def _brief(res: dict) -> dict:
    """Compact summary for job_runs."""
    out = {}
    for k, v in res.items():
        out[k] = len(v) if isinstance(v, list) else v
    return out


def run_monthly(db: Session) -> dict:
    if not tw_companies(db):
        return {"skipped": "no TW companies in knowledge_companies"}
    res = apply_monthly(db, fetch_monthly())
    return _brief(res) | {"missing": res["missing"]}


def run_quarterly(db: Session) -> dict:
    if not tw_companies(db):
        return {"skipped": "no TW companies in knowledge_companies"}
    res = apply_quarterly(db, fetch_quarterly())
    return _brief(res) | {"derived_periods": sorted({d["period"] for d in res["derived"]})}


def run_shares(db: Session) -> dict:
    if not tw_companies(db):
        return {"skipped": "no TW companies in knowledge_companies"}
    res = apply_shares(db, fetch_shares())
    return _brief(res) | {"errors": res["errors"]}


def status(db: Session) -> dict:
    """Latest period per metric kind across the graph, for the data health page."""
    from ..models import MetricActual

    rows = db.execute(select(MetricActual.metric, func.max(MetricActual.period), func.count()).group_by(MetricActual.metric)).all()
    return {m: {"latest_period": p, "rows": n} for m, p, n in rows}
