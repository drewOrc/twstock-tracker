"""Official open-data parsing (offline fixtures), YTD differencing, tracked-company selection."""
import pytest

from app.db import init_db, session_scope
from app.models import Company, CompanyBrief, Edge, EdgeWeight, FinancialYTD, MetricActual
from app.services import knowledge as kn
from app.services import mops

MONTHLY = [
    {"出表日期": "1151017", "資料年月": "11509", "公司代號": "2330", "公司名稱": "台積電",
     "營業收入-當月營收": "511857399", "營業收入-上月營收": "514805337", "營業收入-去年當月營收": "330980920",
     "營業收入-去年同月增減(%)": "54.64861207105231", "備註": "因先進製程產品需求增加所致。"},
    {"出表日期": "1151017", "資料年月": "11509", "公司代號": "9999", "公司名稱": "別家",
     "營業收入-當月營收": "100", "營業收入-上月營收": "90", "營業收入-去年當月營收": "80", "備註": "-"},
    {"出表日期": "1151017", "資料年月": "", "公司代號": "", "公司名稱": "壞列"},
]
QUARTERLY_LISTED = {"出表日期": "1151030", "年度": "115", "季別": "2", "公司代號": "2330", "營業收入": "2404483690.00",
                    "營業毛利（毛損）淨額": "1611606116.00", "營業費用": "192987740.00",
                    "淨利（淨損）歸屬於母公司業主": "1279041690.00", "基本每股盈餘（元）": "49.33"}
QUARTERLY_OTC = {"Date": "1151030", "Year": "115", "Season": "1", "SecuritiesCompanyCode": "2330", "營業收入": "1000000000",
                 "營業毛利（毛損）淨額": "600000000", "營業費用": "90000000", "本期淨利（淨損）": "500000000",
                 "基本每股盈餘（元）": "20.00"}
SHARES = [{"出表日期": "1151029", "公司代號": "2330", "已發行普通股數或TDR原股發行股數": "25932370067"},
          {"出表日期": "1151029", "公司代號": "0000", "已發行普通股數或TDR原股發行股數": ""}]


@pytest.fixture
def db(admin_id):
    init_db()
    with session_scope() as s:
        for model in (EdgeWeight, Edge, CompanyBrief, FinancialYTD, MetricActual, Company):
            s.query(model).delete()
    with session_scope() as s:
        kn.upsert_company(s, {"id": "TW:2330", "name": "台積電"})
        kn.upsert_company(s, {"id": "TW:2382", "name": "廣達"})
        kn.upsert_company(s, {"id": "US:NVDA", "name": "輝達"})
        kn.upsert_company(s, {"id": "TW:00981A", "name": "主動統一台股增長", "sector": "ETF"})
        yield s


def test_tw_companies_skips_etfs_and_us(db):
    assert [c.ticker for c in mops.tw_companies(db)] == ["2330", "2382"]


def test_parse_monthly_rows_roc_dates_and_numbers():
    rows = mops.parse_monthly_rows(MONTHLY)
    assert len(rows) == 2
    r = rows[0]
    assert r["period"] == "2026-09" and r["revenue"] == 511857399 and r["revenue_last_year"] == 330980920
    assert r["remark"].startswith("因先進製程") and rows[1]["remark"] == ""


def test_apply_monthly_writes_three_months_for_tracked_only(db):
    res = mops.apply_monthly(db, mops.parse_monthly_rows(MONTHLY))
    assert [w["company_id"] for w in res["written"]] == ["TW:2330"] and res["missing"] == ["2382"]
    periods = {m["period"]: m["value"] for m in kn.list_metrics(db, "TW:2330", "revenue_m")}
    assert periods == {"2026-09": 511857399, "2026-08": 514805337, "2025-09": 330980920}
    assert all(m["created_by"] == "system:mops" for m in kn.list_metrics(db, "TW:2330"))
    assert kn.list_metrics(db, "TW:9999") == []


def test_quarterly_ytd_differencing(db):
    q2 = mops.parse_quarterly_rows([QUARTERLY_LISTED])[0]
    q1 = mops.parse_quarterly_rows([QUARTERLY_OTC])[0]
    assert q2["year"] == 2026 and q2["quarter"] == 2 and q1["quarter"] == 1
    res = mops.apply_quarterly(db, [q2])
    assert res["derived"] == [] and "need YTD for Q1" in res["skipped"][0]["reason"]
    res = mops.apply_quarterly(db, [q2, q1])  # order does not matter: applied sorted by period
    assert {d["period"] for d in res["derived"]} == {"2026Q1", "2026Q2"}
    got = {(m["metric"], m["period"]): m["value"] for m in kn.list_metrics(db, "TW:2330")}
    assert got[("revenue_q", "2026Q2")] == pytest.approx(2404483690 - 1000000000)
    assert got[("gross_margin", "2026Q2")] == pytest.approx((1611606116 - 600000000) / (2404483690 - 1000000000), abs=1e-4)
    assert got[("eps", "2026Q2")] == pytest.approx(29.33) and got[("eps", "2026Q1")] == pytest.approx(20.0)
    assert len(kn.list_financials(db, "TW:2330")) == 2


def test_shares_in_thousands(db):
    res = mops.apply_shares(db, mops.parse_shares_rows(SHARES))
    assert res["written"][0]["shares_thousands"] == pytest.approx(25932370.067)
    assert kn.list_metrics(db, "TW:2330", "shares")[0]["value"] == pytest.approx(25932370.067, abs=1e-3)
    assert mops.status(db)["shares"]["rows"] == 1


def test_jobs_skip_without_companies(admin_id):
    init_db()
    with session_scope() as s:
        for model in (EdgeWeight, Edge, CompanyBrief, FinancialYTD, MetricActual, Company):
            s.query(model).delete()
    with session_scope() as s:
        assert "skipped" in mops.run_monthly(s)
