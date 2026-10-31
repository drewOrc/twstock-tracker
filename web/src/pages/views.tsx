/* The three views + account + admin as containers (canvas board 27 step 1). Each hosts the existing pages
 * under hash tabs so nothing is lost while pages are rebuilt one by one in later steps. */
import { Navigate, useLocation, useParams } from "react-router-dom";
import { crm, useAsync } from "../api/client";
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
  if (c.startsWith("US:")) {
    return (
      <>
        <div className="page-head"><h1>{c}</h1><span className="muted">美股只有知識層，沒有行情</span></div>
        <section className="panel"><div className="empty">以 {c} 為中心的供應鏈在「結構」裡；個股頁的美股版本在第 5 步。</div></section>
      </>
    );
  }
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
