import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { crm, engine, useAsync } from "../../api/client";
import { useCard } from "../../components/CardDrawer";
import { useAction, useToast } from "../../components/Toast";
import { pct0 } from "../../lib/format";
import { L } from "../../lib/labels";

/** Supply-chain graph from the shared knowledge layer, layered left-to-right by supply depth
 *  (end customers left, suppliers right). Scope: my holdings, my watchlists, companies I pick, or everything. */
type Scope = "holdings" | "watchlist" | "custom" | "all";
const SCOPE_LABEL: Record<Scope, string> = { holdings: "目前持倉", watchlist: "我的追蹤池", custom: "自選股票", all: "全部" };

export default function Graph() {
  const card = useCard();
  const toast = useToast();
  const act = useAction();
  const [scope, setScope] = useState<Scope>(() => { try { return (localStorage.getItem("graph.scope") as Scope) || "holdings"; } catch { return "holdings"; } });
  const [depth, setDepth] = useState(1);
  const [showHolding, setShowHolding] = useState(false);
  const [picked, setPicked] = useState<{ id: string; name: string }[]>(() => { try { return JSON.parse(localStorage.getItem("graph.picked") || "[]"); } catch { return []; } });
  const [query, setQuery] = useState("");
  const [hover, setHover] = useState<string | null>(null);
  const dlg = useRef<HTMLDialogElement>(null);
  useEffect(() => { try { localStorage.setItem("graph.scope", scope); localStorage.setItem("graph.picked", JSON.stringify(picked)); } catch { /* per-viewer convenience only */ } }, [scope, picked]);

  // who I am holding / watching (personal layer) -> seeds for the shared graph
  const positions = useAsync<any[]>(() => crm("/positions").catch(() => []), [card.version]);
  const watch = useAsync<any[]>(() => engine("/watchlist").catch(() => []), []);
  const seeds = useMemo(() => {
    if (scope === "holdings") return (positions.data ?? []).filter((p) => p.stage === "hold").map((p) => p.company_id as string);
    if (scope === "watchlist") return (watch.data ?? []).map((r) => `TW:${r.code}`);
    if (scope === "custom") return picked.map((p) => p.id);
    return null;
  }, [scope, positions.data, watch.data, picked]);
  const seedKey = seeds ? seeds.join(",") : "*";
  const g = useAsync<any>(
    () => (seeds && seeds.length === 0 ? Promise.resolve({ nodes: [], edges: [], seeds: [] }) : engine(`/knowledge/graph?${seeds ? `ids=${encodeURIComponent(seeds.join(","))}&` : ""}depth=${depth}&holding=${showHolding}`)),
    [seedKey, depth, showHolding, card.version],
  );
  const ov = useAsync<any[]>(() => crm("/overlap").catch(() => []), [card.version]);
  const search = useAsync<any[]>(() => (query.trim().length >= 1 ? engine(`/knowledge/companies?q=${encodeURIComponent(query.trim())}&limit=12`) : Promise.resolve([])), [query]);
  const posById = useMemo(() => Object.fromEntries((positions.data ?? []).map((p) => [p.company_id, p])), [positions.data]);

  const layout = useMemo(() => {
    if (!g.data) return null;
    const byId: Record<string, any> = Object.fromEntries(g.data.nodes.map((n: any) => [n.id, { ...n, ...(posById[n.id] ? { stage: posById[n.id].stage, tier: posById[n.id].tier, position_pct: posById[n.id].position_pct } : {}) }]));
    const edges: any[] = g.data.edges;
    const suppliersOf: Record<string, any[]> = {}, customersOf: Record<string, any[]> = {};
    edges.forEach((e: any) => { (suppliersOf[e.customer_id] ??= []).push(e); (customersOf[e.supplier_id] ??= []).push(e); });
    const depthOf: Record<string, number> = {};
    const dep = (id: string, seen = new Set<string>()): number => {
      if (depthOf[id] != null) return depthOf[id];
      if (seen.has(id)) return 0;
      seen.add(id);
      const ups = customersOf[id] || [];
      depthOf[id] = ups.length ? 1 + Math.max(...ups.map((e) => dep(e.customer_id, seen))) : 0;
      return depthOf[id];
    };
    const nodes = Object.values(byId);
    nodes.forEach((n: any) => dep(n.id));
    const layers: Record<number, any[]> = {};
    nodes.forEach((n: any) => (layers[depthOf[n.id]] ??= []).push(n));
    const L_W = 230, ROW = 64, PAD = 40;
    const maxRows = Math.max(1, ...Object.values(layers).map((l) => l.length));
    const W = PAD * 2 + Math.max(1, Object.keys(layers).length) * L_W, H = PAD * 2 + maxRows * ROW;
    const pos: Record<string, { x: number; y: number }> = {};
    Object.entries(layers).forEach(([d, list]) => {
      list.sort((a, b) => Number(!!b.seed) - Number(!!a.seed) || (b.position_pct || 0) - (a.position_pct || 0) || a.id.localeCompare(b.id));
      const offset = (H - list.length * ROW) / 2;
      list.forEach((n, i) => (pos[n.id] = { x: PAD + Number(d) * L_W + 60, y: offset + i * ROW + ROW / 2 }));
    });
    return { byId, nodes, layers, pos, W, H, L_W, PAD, edges: edges.filter((e: any) => pos[e.customer_id] && pos[e.supplier_id]) };
  }, [g.data, posById]);

  async function addEdge(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget).entries()) as Record<string, string>;
    await act(async () => {
      await engine("/knowledge/proposals", { method: "POST", body: {
        kind: "edge",
        payload: { customer_id: f.customer_id, supplier_id: f.supplier_id, revenue_share: f.revenue_share === "" ? null : +f.revenue_share / 100, lag_days: f.lag_days === "" ? null : +f.lag_days, relation: f.relation, source: f.source || null },
        confidence: f.confidence, source: f.source || null, rationale: f.rationale || "手動新增",
      } });
      dlg.current?.close();
    }, "已送出提案，管理員在「知識層」核准後生效");
  }

  const addPick = (c: any) => { if (!picked.some((p) => p.id === c.id)) setPicked([...picked, { id: c.id, name: c.name }]); setQuery(""); };
  const emptyText = scope === "holdings" ? "沒有持有中的卡片。在看板把卡片階段設為「持有」，或切到其他範圍。" : scope === "watchlist" ? "追蹤池是空的。" : "搜尋並加入至少一檔股票。";

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h2>關係圖</h2>
          <span className="legend-crm"><i className="sw core" />核心 <i className="sw satellite" />衛星 <i className="sw watch" />觀察 <i className="sw blacklist" />黑名單 <i className="sw none" />無卡片</span>
          <span className="muted small">線寬 = 客戶佔供應商營收比重；虛線 = 比重不明；橘線 = 夥伴，綠線 = ETF 成分股。粗框 = 範圍內的股票。點節點看卡片或概況。</span>
          <button className="ghost" onClick={() => dlg.current?.showModal()}>＋ 提議關係</button>
        </div>
        <div className="row toolbar">
          <div className="tabs">
            {(Object.keys(SCOPE_LABEL) as Scope[]).map((k) => <button key={k} className={scope === k ? "active" : ""} onClick={() => setScope(k)}>{SCOPE_LABEL[k]}{k === "holdings" && positions.data ? `（${positions.data.filter((p) => p.stage === "hold").length}）` : k === "custom" && picked.length ? `（${picked.length}）` : ""}</button>)}
          </div>
          {scope !== "all" && (
            <label className="small">範圍 <select value={depth} onChange={(e) => setDepth(Number(e.target.value))}><option value={0}>只看彼此</option><option value={1}>直接上下游</option><option value={2}>兩層</option></select></label>
          )}
          <label className="muted small"><input type="checkbox" checked={showHolding} onChange={(e) => setShowHolding(e.target.checked)} /> 顯示 ETF 成分股邊</label>
          {g.data && <span className="muted small">{g.data.nodes.length} 家 · {g.data.edges.length} 條</span>}
        </div>
        {scope === "custom" && (
          <div className="row toolbar" style={{ alignItems: "center" }}>
            <div style={{ position: "relative" }}>
              <input placeholder="搜尋代號或名稱，例如 2330、輝達、NVDA" value={query} onChange={(e) => setQuery(e.target.value)} style={{ width: "18em" }} />
              {query && (search.data?.length ?? 0) > 0 && (
                <div className="dropdown">
                  {(search.data ?? []).map((c) => <div key={c.id} className="item" onClick={() => addPick(c)}>{c.name} <span className="kv">{c.id}{c.sector ? ` · ${c.sector}` : ""}</span></div>)}
                </div>
              )}
            </div>
            {picked.map((p) => <span key={p.id} className="chip">{p.name} <span className="kv">{p.id}</span> <a className="link" onClick={() => setPicked(picked.filter((x) => x.id !== p.id))}>✕</a></span>)}
            {picked.length > 0 && <a className="link small" onClick={() => setPicked([])}>清空</a>}
            {scope === "custom" && positions.data && positions.data.length > 0 && <a className="link small" onClick={() => setPicked([...picked, ...positions.data!.filter((p) => !picked.some((x) => x.id === p.company_id)).map((p) => ({ id: p.company_id, name: p.company_name ?? p.company_id }))])}>＋ 加入所有卡片</a>}
          </div>
        )}
        {g.error && <div className="empty up">{g.error}</div>}
        {layout && layout.nodes.length === 0 && <div className="empty">{emptyText}</div>}
        {layout && layout.nodes.length > 0 && (
          <div className="graph">
            <svg viewBox={`0 0 ${layout.W} ${layout.H}`} width={layout.W} height={layout.H}>
              {Object.keys(layout.layers).map((d) => (
                <text key={d} className="layer-label" x={layout.PAD + Number(d) * layout.L_W + 60} y={18}>{Number(d) === 0 ? "終端客戶 / 夥伴" : `第 ${d} 層供應商`}</text>
              ))}
              {layout.edges.map((e: any) => {
                const a = layout.pos[e.customer_id], b = layout.pos[e.supplier_id], mx = (a.x + b.x) / 2;
                const w = e.revenue_share == null ? 1 : 1 + e.revenue_share * 14;
                const on = hover === e.customer_id || hover === e.supplier_id;
                return (
                  <path key={e.id} className={`edge ${e.relation} ${hover ? (on ? "hi" : "dim") : ""}`} strokeWidth={w} strokeDasharray={e.revenue_share == null ? "4 4" : undefined}
                    d={`M${a.x},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x},${b.y}`}>
                    <title>{`${layout.byId[e.customer_id].name} → ${layout.byId[e.supplier_id].name}（${L.relation[e.relation] ?? e.relation}）：${pct0(e.revenue_share)}，${e.lag_days ?? "?"} 天，信心${L.conf[e.confidence] ?? e.confidence}${e.source ? "，" + e.source : ""}`}</title>
                  </path>
                );
              })}
              {layout.nodes.map((n: any) => {
                const p = layout.pos[n.id], r = n.stage === "hold" ? 10 + Math.sqrt(n.position_pct || 0) * 3 : 8;
                return (
                  <g key={n.id} className={`node ${n.seed ? "seed" : ""}`} transform={`translate(${p.x},${p.y})`} onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}
                    onClick={() => (n.stage || n.id.startsWith("TW:") ? card.open(n.id) : toast(n.id + " 不是台股也沒有卡片，用看板的「＋ 新卡片」建立"))}>
                    <circle r={r} fill={n.tier ? `var(--${n.tier})` : "var(--none)"} stroke={n.seed ? "var(--fg)" : "none"} strokeWidth={n.seed ? 2.5 : 0} />
                    <text x={r + 6} y={-2}>{n.name}</text>
                    <text x={r + 6} y={12} className="sub">{n.id}{n.stage === "hold" ? " · " + n.position_pct + "%" : ""}</text>
                  </g>
                );
              })}
            </svg>
          </div>
        )}
      </section>

      <section className="panel">
        <h3>組合對終端客戶的合計曝險</h3>
        <div className="kv" style={{ marginBottom: 8 }}>直接持有 + 沿供應鏈的間接曝險（部位% × 營收比重）。幾檔看似分散的持股，可能其實押在同一個客戶上。</div>
        {(ov.data?.length ?? 0) === 0 && <div className="kv">還沒有持有中的卡片，或 CRM 離線。</div>}
        {(ov.data?.length ?? 0) > 0 && (
          <table>
            <tbody>
              <tr><th>客戶</th><th className="num">直接%</th><th className="num">間接%</th><th className="num">合計%</th><th>經由</th><th style={{ width: "30%" }}></th></tr>
              {(ov.data ?? []).map((o) => (
                <tr key={o.customer_id}>
                  <td>{o.customer_name} <span className="kv">{o.customer_id}</span></td><td className="num">{o.directly_held_pct}</td><td className="num">{o.indirect_total_pct}</td><td className="num"><b>{o.combined_pct}</b></td>
                  <td className="kv">{o.via.map((v: any) => `${v.name} ${v.exposure_pct}%`).join("、")}</td>
                  <td><div className="bar" style={{ width: `${Math.min(100, (o.combined_pct / (ov.data?.[0]?.combined_pct || 1)) * 100)}%` }} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <dialog ref={dlg}>
        <form onSubmit={addEdge}>
          <h3>提議供應鏈關係</h3>
          <div className="kv">會進知識層的提案佇列，管理員核准後所有人都看得到。</div>
          <label>關係類型<select name="relation"><option value="customer">客戶 → 供應商（客戶向供應商採購）</option><option value="partner">夥伴 → 我方（產能或授權夥伴）</option><option value="holding">成分股 → ETF（持有權重）</option></select></label>
          <label>客戶 / 夥伴 / 成分股（公司 id）<input name="customer_id" placeholder="US:NVDA" required /></label>
          <label>供應商 / 我方 / ETF（公司 id）<input name="supplier_id" placeholder="TW:2330" required /></label>
          <div className="row">
            <label>佔供應商營收 %<input name="revenue_share" type="number" min="0" max="100" step="1" placeholder="25" /></label>
            <label>時間差（天）<input name="lag_days" type="number" min="0" placeholder="60" /></label>
          </div>
          <div className="row">
            <label>信心<select name="confidence" defaultValue="medium"><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></label>
            <label>來源<input name="source" placeholder="年報 / 法說 / 估計" /></label>
          </div>
          <label>理由<input name="rationale" placeholder="為什麼這條關係成立" /></label>
          <menu><button type="button" className="ghost" onClick={() => dlg.current?.close()}>取消</button><button className="primary">送出提案</button></menu>
        </form>
      </dialog>
    </>
  );
}
