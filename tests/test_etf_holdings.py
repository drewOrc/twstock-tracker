"""ETF holdings -> holding edges: MoneyDJ parsing, code resolution, weight history, pruning."""
from datetime import date, datetime

import pytest

from app.db import init_db, session_scope
from app.models import Company, CompanyBrief, Edge, EdgeWeight, FinancialYTD, MetricActual, Stock
from app.services import etf_holdings as eh
from app.services import knowledge as kn

HTML = """
<div class="eTitle">元大台灣50-持股明細</div>
<div id="ctl00_ctl00_MainContent_MainContent_sdate3" align="right">資料日期：2026/09/30</div>
<table id="Repeater1" class="datalist">
<tr><th>股票名稱</th><th>持股(千股)</th><th>比例</th><th>增減</th></tr>
<tr><td class="col05">台積電</td><td class="col06">562,112.00</td><td class="col07">56.45</td><td class="col08"><span>-0.90%</span></td></tr>
<tr><td class="col05">聯發科</td><td class="col06">33,830.00</td><td class="col07">6.74</td><td class="col08"><span>+1.10%</span></td></tr>
<tr><td class="col05">國巨*</td><td class="col06">1,000.00</td><td class="col07">0.80</td><td class="col08"></td></tr>
</table>
"""


@pytest.fixture
def db(admin_id):
    init_db()
    with session_scope() as s:
        for model in (EdgeWeight, Edge, CompanyBrief, FinancialYTD, MetricActual, Company):
            s.query(model).delete()
        for code, name in (("0050", "元大台灣50"), ("2330", "台積電"), ("2454", "聯發科"), ("2327", "國巨")):
            if not s.get(Stock, code):
                s.add(Stock(code=code, name=name, market="TWSE", updated_at=datetime.now()))
    with session_scope() as s:
        yield s


def test_parse_moneydj():
    rows, d = eh.parse_moneydj(HTML)
    assert d == date(2026, 9, 30)
    assert [r["name"] for r in rows] == ["台積電", "聯發科", "國巨"]
    assert rows[0]["weight_pct"] == 56.45 and rows[0]["shares_k"] == 562112.0


def test_apply_holdings_creates_nodes_edges_and_prunes(db):
    rows, d = eh.parse_moneydj(HTML)
    r = eh.apply_holdings(db, "TW:0050", rows, d, "https://example/0050")
    assert r["constituents"] == 3 and r["unresolved"] == []
    fund = db.get(Company, "TW:0050")
    assert fund.sector == "ETF" and fund.name == "元大台灣50"
    assert db.get(Company, "TW:2330").name == "台積電"
    h = eh.holdings(db, "TW:0050")
    assert [x["company_id"] for x in h] == ["TW:2330", "TW:2454", "TW:2327"] and h[0]["weight_pct"] == 56.45
    e = db.query(Edge).filter_by(customer_id="TW:2330", supplier_id="TW:0050").one()
    assert e.relation == "holding" and kn.edge_weights(db, e.id)[0]["date"] == "2026-09-30"
    # next month: 國巨 drops out, 台積電 weight changes -> history keeps both dates, edge holds the latest
    r = eh.apply_holdings(db, "TW:0050", [{"name": "台積電", "weight_pct": 57.0}, {"name": "聯發科", "weight_pct": 6.0}], date(2026, 10, 31), "https://example/0050")
    assert r["removed"] == ["TW:2327"] and r["constituents"] == 2
    assert [w["revenue_share"] for w in kn.edge_weights(db, e.id)] == [0.5645, 0.57]
    assert db.get(Edge, e.id).revenue_share == 0.57
    assert eh.funds(db) == [{"id": "TW:0050", "name": "元大台灣50", "constituents": 2}]
    # a US fund from supplied rows: creates US nodes from the given names
    r = eh.apply_holdings(db, "US:VOO", [{"company_id": "US:NVDA", "name": "NVIDIA", "weight_pct": 8.39}, {"company_id": "US:AAPL", "name": "Apple", "weight_pct": 7.38}], date(2026, 9, 30), "https://example/voo", fund_name="Vanguard S&P 500 ETF")
    assert r["constituents"] == 2 and db.get(Company, "US:NVDA").name == "NVIDIA" and db.get(Company, "US:VOO").sector == "ETF"
    assert kn.for_stock(db, "2330")["suppliers"][0] == {"id": "TW:0050", "name": "元大台灣50", "revenue_share": 0.57, "relation": "holding"}
