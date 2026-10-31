import { NavLink, Outlet } from "react-router-dom";
import { crm, engine, publicApi, useAsync } from "../api/client";
import { time } from "../lib/format";
import { useMe } from "./Auth";

const ENGINE_TABS = [
  ["/watchlist", "追蹤池"],
  ["/market", "盤面分化"],
  ["/screener", "選股掃描"],
  ["/alerts", "警示"],
  ["/jobs", "系統"],
];
const CRM_TABS = [
  ["/board", "看板"],
  ["/graph", "關係圖"],
  ["/morning", "早晨"],
  ["/proposals", "提案"],
];

export default function Layout() {
  const { me, logout } = useMe();
  const health = useAsync(() => publicApi("/health"), [], 30000);
  const jobs = useAsync(() => engine("/jobs"), [], 30000);
  const pending = useAsync(() => crm("/proposals").catch(() => []), [], 60000);
  const h = health.data;
  const rt = jobs.data?.realtime;
  const live = h?.trading_hours && h?.scheduler?.running && !rt?.error;
  const crmOk = h?.crm?.reachable;

  return (
    <>
      <header className="topbar">
        <div className="brand">
          台股追蹤引擎 <span className="sub">TW Stock Tracker + Stock CRM</span>
        </div>
        <nav>
          <span className="nav-group">引擎</span>
          {ENGINE_TABS.map(([to, label]) => (
            <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "active" : "")}>
              {label}
            </NavLink>
          ))}
          <span className="nav-group">CRM</span>
          {CRM_TABS.map(([to, label]) => (
            <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "active" : "")}>
              {label}
              {to === "/proposals" && pending.data?.length ? <span className="pill">{pending.data.length}</span> : null}
            </NavLink>
          ))}
        </nav>
        <div className="status" title="每 30 秒更新">
          {health.error ? (
            <span className="up">引擎離線：{health.error}</span>
          ) : h ? (
            <>
              <span className={`dot ${live ? "live" : ""}`} />
              {h.trading_hours ? "盤中" : "非交易時段"} · 排程 {h.scheduler.running ? "運行中" : "停止"} · 即時{" "}
              {rt?.last_success ? time(rt.last_success) : "尚未"} ·{" "}
              <span className={crmOk ? "" : "up"} title={h.crm?.url}>
                CRM {crmOk ? "已連線" : "離線"}
              </span>
            </>
          ) : (
            "連線中…"
          )}
        </div>
        <div className="user-menu">
          <NavLink to="/users" className={({ isActive }) => (isActive ? "active" : "")} title={me?.role === "admin" ? "帳號管理" : "我的帳號"}>
            {me?.display_name || me?.username}{me?.role === "admin" ? <span className="badge" style={{ marginLeft: 4 }}>管理員</span> : null}
          </NavLink>
          <button className="ghost tiny" onClick={logout}>登出</button>
        </div>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </>
  );
}
