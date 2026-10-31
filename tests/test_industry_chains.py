"""TPEx industry value chain parser, storage and reads."""
import pytest

from app.db import init_db, session_scope
from app.models import ChainMember, ChainSegment, IndustryChain
from app.services import industry_chains as ic

INDEX = """<select id="ic_option"><option value='D000' selected>半導體</option><option value='L000' >印刷電路板</option></select>"""

PAGE = """
<div class="page-header text-start"><h3>半導體產業鏈簡介</h3></div>
<div id="main_ic_panel" class="chain-panel">
 <div class="chain"><div class="chain-title-panel">上游</div>
  <div id="ic_link_DC00" class="company-chain-panel">IP設計<br/>/IC設計<br/>代工服務</div>
  <div id="ic_link_D100" class="company-chain-panel">IC設計</div></div>
 <div class="chain"><div class="chain-title-panel">中游</div>
  <div id="ic_link_D300" class="company-chain-panel">IC/晶圓製造</div></div>
</div>
<div id="intro-content">半導體產業鏈上游為 IC 設計 &amp; IP。</div>
<div id="companyList_DC00" title="IP設計/IC設計代工服務" class="x-hidden"><table>
 <tr><td colspan='5'><b>本國上市公司(2家)</b></td></tr>
 <tr><td><a href="company_basic.php?stk_code=3443" class="company-text-over" title="創意">創意</a></td>
 <td><a href="company_basic.php?stk_code=3035" class="company-text-over" title="智原">智原</a></td></tr>
 <tr><td colspan='5'><b>知名外國企業(1家)</b></td></tr>
 <tr><td><a href="https://www.synopsys.com/" class="company-text-over" title="新思科技" target="_blank">新思科技</a></td></tr>
</table></div><span class="company-number">共3家</span></div>
<div id="companyList_D100" title="IC設計" class="x-hidden"><div class="subchain-company-list"><div id="sc_industry_D100">
 <div id="sc_link_D150" class="subchain-hover"><span>&#9658;</span>&nbsp;記憶體IC&nbsp;(2家)</div>
 <div id="sc_link_D1A0" class="subchain"><span>&#9658;</span>&nbsp;網路通訊IC&nbsp;(1家)</div></div>
 <table id="sc_company_D150"><tr><td colspan='4'><b>本國上市公司(2家)</b></td></tr>
  <tr><td><a href="company_basic.php?stk_code=2344" class="company-text-over" title="華邦電">華邦電</a></td>
  <td><a href="company_basic.php?stk_code=2408" class="company-text-over" title="南亞科">南亞科</a></td></tr></table>
 <table id="sc_company_D1A0"><tr><td colspan='4'><b>本國上櫃公司(1家)</b></td></tr>
  <tr><td><a href="company_basic.php?stk_code=2454" class="company-text-over" title="聯發科">聯發科</a></td></tr></table>
</div></div>
<div id="companyList_D300" title="IC/晶圓製造" class="x-hidden"><table>
 <tr><td colspan='5'><b>本國上市公司(2家)</b></td></tr>
 <tr><td><a href="company_basic.php?stk_code=2330" class="company-text-over" title="台積電">台積電</a></td>
 <td><a href="company_basic.php?stk_code=2408" class="company-text-over" title="南亞科">南亞科</a></td></tr></table></div>
<div id="companyList_D300" title="IC/晶圓製造" class="x-hidden"><table><tr><td><a href="company_basic.php?stk_code=9999" title="重複">重複</a></td></tr></table></div>
"""


def test_parse():
    assert ic.parse_index(INDEX) == [("D000", "半導體"), ("L000", "印刷電路板")]
    c = ic.parse_chain("D000", PAGE)
    assert c["name"] == "半導體" and "IC 設計 & IP" in c["intro"]
    segs = {s["id"]: s for s in c["segments"]}
    assert set(segs) == {"DC00", "D100", "D150", "D1A0", "D300"}  # repeated D300 block ignored
    assert segs["DC00"]["stage"] == "上游" and segs["D300"]["stage"] == "中游" and segs["D150"]["stage"] == "上游"
    assert segs["DC00"]["name"] == "IP設計/IC設計代工服務"
    assert segs["D150"]["parent_id"] == "D100" and segs["D150"]["name"] == "記憶體IC"
    assert [m["code"] for m in segs["D150"]["members"]] == ["2344", "2408"]
    assert segs["D1A0"]["members"][0]["listing"] == "上櫃"
    foreign = [m for m in segs["DC00"]["members"] if m["code"] is None]
    assert foreign[0]["name"] == "新思科技" and foreign[0]["listing"] == "外國企業" and foreign[0]["url"].startswith("https://")
    assert segs["D100"]["members"] == []


@pytest.fixture
def db(admin_id):
    init_db()
    with session_scope() as s:
        for m in (ChainMember, ChainSegment, IndustryChain):
            s.query(m).delete()
        s.commit()
        yield s


def test_apply_and_reads(db, client):
    out = ic.apply_chain(db, ic.parse_chain("D000", PAGE))
    assert out["segments"] == 5 and out["members"] == 8 and out["tw_companies"] == 6
    again = ic.apply_chain(db, ic.parse_chain("D000", PAGE))  # replace, not append
    assert again["members"] == 8 and ic.stats(db)["members"] == 8
    where = ic.for_company(db, "tw:2408")
    assert {(w["segment"], w["stage"]) for w in where} == {("記憶體IC", "上游"), ("IC/晶圓製造", "中游")}
    mem = next(w for w in where if w["segment"] == "記憶體IC")
    assert mem["parent"] == "IC設計" and [p["name"] for p in mem["peers"]] == ["華邦電"]
    d = ic.chain_detail(db, "D000")
    assert [s["stage"] for s in d["segments"]] == ["上游", "上游", "中游"]
    assert [c["name"] for c in d["segments"][1]["children"]] == ["記憶體IC", "網路通訊IC"]
    r = client.get("/api/market/knowledge/chains")
    assert r.status_code == 200 and r.json()["chains"][0]["companies"] == 6
    assert client.get("/api/market/knowledge/chains/D000").json()["name"] == "半導體"
    assert client.get("/api/market/knowledge/chains/ZZZZ").status_code == 404
    assert len(client.get("/api/market/knowledge/companies/TW:2408/chains").json()) == 2
