"""Knowledge company ids: TW / US / KR accepted, anything else rejected."""
import pytest

from app.db import init_db, session_scope
from app.models import Company, Edge
from app.services import knowledge as kn


def test_kr_company_and_edge(admin_id):
    init_db()
    with session_scope() as s:
        s.query(Edge).filter(Edge.supplier_id == "KR:000660").delete()
        kn.upsert_company(s, {"id": "kr:000660", "name": "SK hynix"})
        kn.upsert_company(s, {"id": "US:NVDA", "name": "NVIDIA"})
        c = s.get(Company, "KR:000660")
        assert c.market == "KR" and c.ticker == "000660"
        e = kn.upsert_edge(s, {"customer_id": "US:NVDA", "supplier_id": "KR:000660", "revenue_share": 0.3})
        assert e.revenue_share == 0.3
        g = kn.subgraph(s, ["KR:000660"], depth=1)
        assert {n["id"] for n in g["nodes"]} >= {"KR:000660", "US:NVDA"}
        assert next(n for n in g["nodes"] if n["id"] == "KR:000660")["market"] == "KR"
        with pytest.raises(ValueError):
            kn.upsert_company(s, {"id": "JP:8035", "name": "Tokyo Electron"})
