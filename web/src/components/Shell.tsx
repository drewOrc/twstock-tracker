/* App shell (canvas board 25): header = logo · three views · search · inbox · avatar; bottom nav on phones;
 * global banners for engine / CRM reachability. Everything else is reached from these four pieces. */
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { crm, engine, publicApi, useAsync } from "../api/client";
import { useMe } from "./Auth";
import { FreshTag, MineTag, StockRow, type StockRowData } from "./ui";

export const VIEWS: [string, string][] = [
  ["/market", "市場"],
  ["/me", "我的"],
  ["/structure", "結構"],
];

export default function Shell() {
  const { me } = useMe();
  const health = useAsync(() => publicApi("/health"), [], 30000);
  // Personal-scope proposals waiting for me = the "需要你" inbox count. CRM offline -> 0, never an error here.
  const pending = useAsync<any[]>(() => crm("/proposals").catch(() => []), [], 60000);
  const h = health.data;
  const crmDown = !!h && h.crm && h.crm.reachable === false;
  const inboxCount = (pending.data ?? []).filter((p) => !p.status || p.status === "pending").length;

  return (
    <div className="shell">
      <header className="shell-head">
        <Link to="/" className="brand-mark" title="回到此刻的預設頁"><span className="logo" />台股追蹤</Link>
        <nav className="view-nav" aria-label="視角">
          {VIEWS.map(([to, label]) => (
            <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "active" : "")}>{label}</NavLink>
          ))}
        </nav>
        <SearchBox />
        <div className="head-right">
          <SessionTag h={h} error={health.error} />
          <Link to="/me#today" className={`inbox ${inboxCount ? "has" : ""}`} title="需要你處理的事">
            {inboxCount || 0}<span className="txt"> 件待辦</span>
          </Link>
          <AvatarMenu />
        </div>
      </header>

      {health.error && (
        <div className="banner bad">系統連不上（/api/health 無回應）。顯示的數字可能不是現在的。<button className="ghost tiny" onClick={health.reload}>重試</button></div>
      )}
      {crmDown && (
        <div className="banner warn">卡片與論點暫時讀不到（Stock CRM 離線）。清單、警示與市場資料照常。<button className="ghost tiny" onClick={health.reload}>重試</button></div>
      )}

      <main className="page">
        <Outlet />
      </main>

      <nav className="bottom-nav" aria-label="視角">
        {VIEWS.map(([to, label]) => (
          <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "active" : "")}>
            <ViewIcon view={to} />
            {label}
          </NavLink>
        ))}
      </nav>
      {me ? null : null}
    </div>
  );
}

/** 盤中 / 盤後 one-word session marker from /api/health. Per-section data times live in the sections themselves. */
function SessionTag({ h, error }: { h: any; error: string | null }) {
  if (error) return <FreshTag kind="stale">離線</FreshTag>;
  if (!h) return <FreshTag kind="off">連線中</FreshTag>;
  if (h.trading_hours) return <FreshTag kind="live" title="交易時段，即時報價每 10 秒">盤中</FreshTag>;
  return <FreshTag kind="close" title="非交易時段，顯示上一個收盤">盤後</FreshTag>;
}

function ViewIcon({ view }: { view: string }) {
  const common = { width: 20, height: 20, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, "aria-hidden": true };
  if (view === "/market") return <svg {...common}><path d="M3 17l6-6 4 4 8-8" /></svg>;
  if (view === "/me") return <svg {...common}><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 4-6 8-6s8 2 8 6" /></svg>;
  return <svg {...common}><circle cx="5" cy="12" r="2" /><circle cx="19" cy="6" r="2" /><circle cx="19" cy="18" r="2" /><path d="M7 11l10-4M7 13l10 4" /></svg>;
}

/* ---------- search (⌘K): one box, stocks from the engine; more groups come with later steps ---------- */
function SearchBox() {
  const nav = useNavigate();
  const loc = useLocation();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<StockRowData[]>([]);
  const [busy, setBusy] = useState(false);
  const [idx, setIdx] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => { setOpen(false); setQ(""); }, [loc.pathname]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); input.current?.focus(); setOpen(true); }
    };
    const onClick = (e: MouseEvent) => { if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("mousedown", onClick); };
  }, []);
  useEffect(() => {
    const s = q.trim();
    if (!s) { setRows([]); return; }
    setBusy(true);
    const t = setTimeout(async () => {
      try {
        const r: any[] = await engine(`/stocks/search?q=${encodeURIComponent(s)}&limit=8`);
        setRows(r.map((x) => ({ code: x.code ?? x.stock_code, name: x.name, sector: x.sector ?? x.industry ?? null, market: x.market ?? null })));
        setIdx(0);
      } catch { setRows([]); } finally { setBusy(false); }
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  const go = (code: string) => { setOpen(false); setQ(""); nav(`/stock/${code}`); };
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, rows.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter") { const r = rows[idx]; if (r) go(r.code); else if (/^\d{4,6}[A-Z]?$/i.test(q.trim())) go(q.trim().toUpperCase()); }
    else if (e.key === "Escape") { setOpen(false); input.current?.blur(); }
  };

  return (
    <div className="search-box" ref={wrap}>
      <label className="field" htmlFor="shell-search">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
        <input id="shell-search" ref={input} value={q} placeholder="搜尋代號或名稱" autoComplete="off"
          onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onKeyDown={onKeyDown} />
        <span className="kbd">⌘K</span>
      </label>
      {open && q.trim() && (
        <div className="search-pop" role="listbox">
          <div className="grp">個股</div>
          {rows.map((r, i) => <StockRow key={r.code} s={r} active={i === idx} onClick={() => go(r.code)} marks={r.market ? <MineTag variant="sys">{r.market}</MineTag> : undefined} />)}
          {!rows.length && <div className="empty">{busy ? "搜尋中…" : `沒有符合「${q}」的個股`}</div>}
        </div>
      )}
    </div>
  );
}

/* ---------- avatar menu: 我的帳號 · 管理（管理員）· 登出 ---------- */
function AvatarMenu() {
  const { me, logout } = useMe();
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname, loc.hash]);
  useEffect(() => {
    const onClick = (e: MouseEvent) => { if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, []);
  if (!me) return null;
  const isAdmin = me.role === "admin";
  return (
    <div className="avatar-wrap" ref={wrap}>
      <button className="avatar-btn" onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}>
        <span className="av" />{me.display_name || me.username} ▾
      </button>
      {open && (
        <div className="avatar-menu" role="menu">
          <div className="who"><span className="av" /><div><div style={{ fontWeight: 700 }}>{me.display_name || me.username}</div><div className="muted">{isAdmin ? "管理員" : "成員"} · {me.username}</div></div></div>
          <div className="sep" />
          <Link to="/account" role="menuitem">我的帳號<span className="r">通知 · 密碼</span></Link>
          {isAdmin && <Link to="/admin" role="menuitem">管理<span className="r">系統 · 帳號 · 金鑰</span></Link>}
          {isAdmin && <Link to="/structure#knowledge" role="menuitem">知識層審核</Link>}
          <div className="sep" />
          <button className="item danger" role="menuitem" onClick={logout}>登出</button>
        </div>
      )}
    </div>
  );
}
