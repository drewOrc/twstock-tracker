"""Stock summary (基本介紹 + 最近狀況) on synthetic data, and the news RSS parser."""
from datetime import date, datetime, timedelta

import pytest

from app.db import init_db, session_scope
from app.models import DailyPrice, IndexDaily, InstitutionalFlow, MarginBalance, Stock
from app.services import stock_summary as ss
from app.services.industries import MAIN_INDEX

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>台積電法說會釋出樂觀展望 - 經濟日報</title><link>https://example.com/a</link><pubDate>Fri, 31 Oct 2026 01:00:00 GMT</pubDate><source url="https://money.udn.com">經濟日報</source></item>
<item><title>外資連買台積電</title><link>https://example.com/b</link><pubDate>Thu, 30 Oct 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_parse_rss_strips_source_suffix():
    items = ss.parse_rss(RSS)
    assert items[0] == {"title": "台積電法說會釋出樂觀展望", "link": "https://example.com/a", "published": "Fri, 31 Oct 2026 01:00:00 GMT", "source": "經濟日報"}
    assert items[1]["title"] == "外資連買台積電" and items[1]["source"] == ""


@pytest.fixture
def seeded(monkeypatch):
    init_db()
    monkeypatch.setattr(ss, "fetch_news", lambda name, limit=10: ([{"title": f"{name} 新聞", "link": "x", "published": "", "source": "t"}], None))
    days = [date(2026, 9, 1) + timedelta(days=i) for i in range(45)]
    days = [d for d in days if d.weekday() < 5]  # 33 trading days
    with session_scope() as s:
        for code in ("9901", "9902", "9903"):
            s.query(DailyPrice).filter_by(code=code).delete()
            s.query(InstitutionalFlow).filter_by(code=code).delete()
            s.query(MarginBalance).filter_by(code=code).delete()
        s.query(IndexDaily).filter(IndexDaily.name == MAIN_INDEX, IndexDaily.date.in_(days)).delete(synchronize_session=False)
        s.merge(Stock(code="9901", name="測試甲", market="TWSE", industry="24", full_name="測試甲股份有限公司", chairman="王大明", listed_date="2000-01-01", capital=1e9, shares_issued=100_000_000, website="https://a.test", updated_at=datetime.now()))
        s.merge(Stock(code="9902", name="測試乙", market="TWSE", industry="24", updated_at=datetime.now()))
        s.merge(Stock(code="9903", name="測試丙", market="TPEX", industry="24", updated_at=datetime.now()))
        for i, d in enumerate(days):
            # 9901 rises 1%/day, 9902 flat, 9903 falls; index rises 0.2%/day
            for code, px in (("9901", 100 * 1.01**i), ("9902", 50.0), ("9903", 80 * 0.995**i)):
                s.add(DailyPrice(code=code, date=d, open=px, high=px * 1.01, low=px * 0.99, close=px, volume=1_000_000, turnover=px * 1_000_000, change=0.0))
            s.add(IndexDaily(name=MAIN_INDEX, date=d, close=20000 * 1.002**i, change_pct=0.2))
            s.add(InstitutionalFlow(code="9901", date=d, foreign_net=2_000_000, trust_net=-500_000, dealer_net=0, total_net=1_500_000))
            s.add(MarginBalance(code="9901", date=d, margin_balance=10_000 + i * 10, margin_prev=10_000 + (i - 1) * 10, short_balance=100))
    yield


def test_summary_blocks(seeded):
    with session_scope() as db:
        out = ss.stock_summary(db, "9901")
    p, pr, ch, ctx = out["profile"], out["price"], out["chips"], out["context"]
    assert p["name"] == "測試甲" and p["sector"] == "半導體" and p["capital_yi"] == 10.0 and p["chairman"] == "王大明"
    assert pr["available"] and pr["history_days"] == 33
    assert pr["returns"]["20d"] == pytest.approx((1.01**20 - 1) * 100, abs=0.05)
    assert pr["index_returns"]["20d"] == pytest.approx((1.002**20 - 1) * 100, abs=0.05)
    assert pr["relative"]["20d"] > 15
    assert pr["returns"]["250d"] is None  # not enough history
    assert pr["sector"]["peers"] == 3 and pr["sector"]["rank_20d"] == 1
    assert pr["range"]["from_high_pct"] == pytest.approx(-0.99, abs=0.05)  # close vs today's high
    assert pr["alignment"] == "多頭排列"
    assert ch["foreign_5d"] == 10_000 and ch["foreign_20d"] == 40_000 and ch["foreign_streak"] >= 20
    assert ch["margin_change_20d"] == 200
    assert ctx["screener"] == [] and ctx["alert_rules"] == 0
    assert out["news"]["items"][0]["title"] == "測試甲 新聞"


def test_summary_endpoint_and_unknown_code(seeded, client, monkeypatch):
    from app.services import market_data as md

    monkeypatch.setattr(md, "refresh_stock_list", lambda db: 0)
    monkeypatch.setattr(md.mis, "fetch_quotes", lambda items: [])
    r = client.get("/api/market/stocks/9903/summary?news=false")
    assert r.status_code == 200
    body = r.json()
    assert body["profile"]["market_label"] == "上櫃" and "news" not in body
    assert body["price"]["sector"]["rank_20d"] == 3
    assert client.get("/api/market/stocks/ZZZZ/summary?news=false").status_code == 404
