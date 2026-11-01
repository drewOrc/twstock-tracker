/* The three views + account + admin as containers (canvas board 27 step 1). Each hosts the existing pages
 * under hash tabs so nothing is lost while pages are rebuilt one by one in later steps. */
import { Link, Navigate, useLocation, useParams } from "react-router-dom";
import { crm, engine, useAsync } from "../api/client";
import { useMe } from "../components/Auth";
import { useCard } from "../components/CardDrawer";
import { StockSummary } from "../components/StockSummary";
import { SubTabs } from "../components/SubTabs";
import Alerts from "./Alerts";
import Jobs from "./Jobs";
import Knowledge from "./Knowledge";
import Market from "./Market";
import Screener from "./Screener";
import Users from "./Users";
import Watchlist from "./Watchlist";
import Board from "./crm/Board";
import Graph from "./crm/Graph";
import Morning from "./crm/Morning";
import Proposals from "./crm/Proposals";

const LEGACY = "舊頁先掛在新殼層下，之後逐頁重做";

export function MarketView() {
  return (
    <>
      <div className="page-head"><h1>市場</h1><span className="muted">全市場 · 每個人看到的一樣</span></div>
      <SubTabs fallback="breadth" note={LEGACY} tabs={[
        { key: "breadth", label: "盤面", element: <Market /> },
        { key: "screener", label: "選股掃描", element: <Screener /> },
      ]} />
    </>
  );
}

export function MeView() {
  const pending = useAsync<any[]>(() => crm("/proposals").catch(() => []), [], 60000);
  const n = (pending.data ?? []).filter((p) => !p.status || p.status === "pending").length;
  return (
    <>
      <div className="page-head"><h1>我的</h1><span className="muted">清單、警示、卡片、今天該處理的事</span></div>
      <SubTabs fallback="lists" note={LEGACY} tabs={[
        { key: "today", label: "今天", element: <Morning /> },
        { key: "lists", label: "清單", element: <Watchlist /> },
        { key: "cards", label: "卡片", element: <Board /> },
        { key: "alerts", label: "警示", element: <Alerts /> },
        { key: "proposals", label: "待確認", count: n, element: <Proposals /> },
      ]} />
    </>
  );
}

export function StructureView() {
  return (
    <>
      <div className="page-head"><h1>結構</h1><span className="muted">供應鏈、ETF、知識層</span></div>
      <SubTabs fallback="chain" note={LEGACY} tabs={[
        { key: "chain", label: "供應鏈", element: <Graph /> },
        { key: "knowledge", label: "知識層", element: <Knowledge /> },
      ]} />
    </>
  );
}

export function AdminView() {
  const { me } = useMe();
  if (me?.role !== "admin") return <NotFound />;
  return (
    <>
      <div className="page-head"><h1>管理</h1><span className="muted">只有管理員看得到這一頁</span></div>
      <SubTabs fallback="system" note={LEGACY} tabs={[
        { key: "system", label: "系統", element: <Jobs /> },
        { key: "users", label: "帳號與金鑰", element: <Users /> },
      ]} />
    </>
  );
}

export function AccountView() {
  return (
    <>
      <div className="page-head"><h1>我的帳號</h1><span className="muted">密碼、通知、裝置</span></div>
      <Users />
    </>
  );
}

/** /stock/:code — the hub page. Step 1 only gives it an address and the summary; step 2 builds the full page. */
export function StockPage() {
  const { code = "" } = useParams();
  const card = useCard();
  const c = code.toUpperCase();
  if (c.startsWith("TW:")) return <Navigate to={`/stock/${c.slice(3)}`} replace />;
  // any other MARKET:TICKER id (US:NVDA, KR:005930, ...) is a knowledge-only company: no quotes
  if (/^[A-Z]{2}:/.test(c)) return <KnowledgeCompanyPage id={c} />;
  return (
    <>
      <div className="page-head">
        <h1>{c}</h1>
        <span className="muted">個股頁 · 第 2 步會補 K 線、法人、結構與「我的」欄</span>
        <button className="ghost tiny" style={{ marginLeft: "auto" }} onClick={() => card.open(c)}>打開卡片</button>
      </div>
      <section className="panel summary-wrap"><StockSummary code={c} /></section>
    </>
  );
}

const MARKET_LABEL: Record<string, string> = { US: "美股", KR: "韓股" };

/** Companies outside Taiwan live only in the knowledge layer: profile, highlights and relations. */
function KnowledgeCompanyPage({ id }: { id: string }) {
  const q = useAsync<any>(() => engine(`/knowledge/companies/${encodeURIComponent(id)}`), [id]);
  const market = id.split(":", 1)[0];
  const d = q.data;
  const chip = (cid: string, name: string | null, label: string, share: number | null, title: string) => (
    <Link key={`${label}${cid}`} to={`/stock/${encodeURIComponent(cid)}`} className="chip" title={title}>
      {label} {name ?? cid}{share != null ? ` ${Math.round(share * 100)}%` : ""}
    </Link>
  );
  return (
    <>
      <div className="page-head">
        <h1>{d?.name ?? id}</h1>
        <span className="muted">{id}{d?.name_en ? ` · ${d.name_en}` : ""}{d?.sector ? ` · ${d.sector}` : ""} · {MARKET_LABEL[market] ?? market}只有知識層，沒有行情</span>
      </div>
      <section className="panel">
        {q.error && <div className="empty">知識層沒有 {id}：{q.error}</div>}
        {!q.error && !d && <div className="kv">載入中…</div>}
        {d && (
          <>
            {d.briefs?.profile ? <p className="brief">{d.briefs.profile.content}</p> : <div className="kv">還沒有公司簡介。</div>}
            {d.briefs?.highlights && <p className="brief"><span className="k">近期重點 {d.briefs.highlights.date}</span>{d.briefs.highlights.content}</p>}
            <h4>客戶 <span className="kv">向 {d.name} 採購；百分比為佔 {d.name} 營收比重</span></h4>
            <div className="ctx-line">
              {(d.edges?.customers ?? []).filter((e: any) => e.relation !== "holding").map((e: any) => chip(e.customer_id, e.customer_name, e.relation === "partner" ? "夥伴" : "客戶", e.revenue_share, e.source ?? ""))}
              {!(d.edges?.customers ?? []).some((e: any) => e.relation !== "holding") && <span className="kv">沒有記錄。</span>}
            </div>
            <h4>供應商 <span className="kv">{d.name} 向他們採購；百分比為佔對方營收比重</span></h4>
            <div className="ctx-line">
              {(d.edges?.suppliers ?? []).filter((e: any) => e.relation !== "holding").map((e: any) => chip(e.supplier_id, e.supplier_name, e.relation === "partner" ? "夥伴" : "供應商", e.revenue_share, e.source ?? ""))}
              {!(d.edges?.suppliers ?? []).some((e: any) => e.relation !== "holding") && <span className="kv">沒有記錄。</span>}
            </div>
            {(d.edges?.suppliers ?? []).some((e: any) => e.relation === "holding") && (
              <>
                <h4>所屬 ETF</h4>
                <div className="ctx-line">
                  {(d.edges.suppliers as any[]).filter((e) => e.relation === "holding").map((e) => chip(e.supplier_id, e.supplier_name, "持有於", e.revenue_share, "成分股權重"))}
                </div>
              </>
            )}
            {(d.edges?.customers ?? []).some((e: any) => e.relation === "holding") && (
              <>
                <h4>成分股 <span className="kv">權重</span></h4>
                <div className="ctx-line">
                  {(d.edges.customers as any[]).filter((e) => e.relation === "holding").map((e) => chip(e.customer_id, e.customer_name, "", e.revenue_share, "成分股權重"))}
                </div>
              </>
            )}
            <p className="hint">完整的關係圖在「結構」，可以把 {id} 加進自選範圍。</p>
          </>
        )}
      </section>
    </>
  );
}

/** "/" lands on the page this moment asks for (board 25): morning → today, trading hours → my lists,
 *  afternoon → breadth, evening/night → screener, weekend → cards. Taipei time. */
export function Home() {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Taipei", hour12: false, weekday: "short", hour: "2-digit", minute: "2-digit" }).formatToParts(new Date());
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const weekend = ["Sat", "Sun"].includes(get("weekday"));
  const hm = Number(get("hour")) * 100 + Number(get("minute"));
  let to = "/market#screener";
  if (weekend) to = "/me#cards";
  else if (hm >= 600 && hm < 900) to = "/me#today";
  else if (hm >= 900 && hm <= 1335) to = "/me#lists";
  else if (hm > 1335 && hm <= 1640) to = "/market#breadth";
  return <Navigate to={to} replace />;
}

export function NotFound() {
  const loc = useLocation();
  return (
    <div className="notfound">
      <h1>找不到這一頁</h1>
      <p className="muted">{loc.pathname} 不存在，或你沒有權限看它。試試上面的搜尋，或回到<a href="/"> 首頁</a>。</p>
    </div>
  );
}
