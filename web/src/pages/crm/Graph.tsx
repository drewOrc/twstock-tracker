import { useMemo, useRef, useState, type FormEvent } from "react";
import { crm, useAsync } from "../../api/client";
import { useCard } from "../../components/CardDrawer";
import { useAction, useToast } from "../../components/Toast";
import { pct0 } from "../../lib/format";
import { L } from "../../lib/labels";

/** Supply-chain graph: layered left-to-right by supply depth (end customers left, suppliers right). */
export default function Graph() {
  const card = useCard();
  const toast = useToast();
  const act = useAction();
  const g = useAsync(() => crm("/graph"), [card.version]);
  const ov = useAsync<any[]>(() => crm("/overlap"), [card.version]);
  const [hover, setHover] = useState<string | null>(null);
  const dlg = useRef<HTMLDialogElement>(null);

  const layout = useMemo(() => {
    if (!g.data) return null;
    const byId: Record<string, any> = Object.fromEntries(g.data.nodes.map((n: any) => [n.id, n]));
    const suppliersOf: Record<string, any[]> = {}, customersOf: Record<string, any[]> = {};
    g.data.edges.forEach((e: any) => { (suppliersOf[e.customer_id] ??= []).push(e); (customersOf[e.supplier_id] ??= []).push(e); });
    const depth: Record<string, number> = {};
    const dep = (id: string, seen = new Set<string>()): number => {
      if (depth[id] != null) return depth[id];
      if (seen.has(id)) return 0;
      seen.add(id);
      const ups = customersOf[id] || [];
      depth[id] = ups.length ? 1 + Math.max(...ups.map((e) => dep(e.customer_id, seen))) : 0;
      return depth[id];
    };
    const nodes = g.data.nodes.filter((n: any) => suppliersOf[n.id] || customersOf[n.id] || n.stage);
    nodes.forEach((n: any) => dep(n.id));
    const layers: Record<number, any[]> = {};
    nodes.forEach((n: any) => (layers[depth[n.id]] ??= []).push(n));
    const L_W = 230, ROW = 64, PAD = 40;
    const maxRows = Math.max(1, ...Object.values(layers).map((l) => l.length));
    const W = PAD * 2 + Object.keys(layers).length * L_W, H = PAD * 2 + maxRows * ROW;
    const pos: Record<string, { x: number; y: number }> = {};
    Object.entries(layers).forEach(([d, list]) => {
      list.sort((a, b) => (b.position_pct || 0) - (a.position_pct || 0) || a.id.localeCompare(b.id));
      const offset = (H - list.length * ROW) / 2;
      list.forEach((n, i) => (pos[n.id] = { x: PAD + Number(d) * L_W + 60, y: offset + i * ROW + ROW / 2 }));
    });
    return { byId, nodes, layers, pos, W, H, L_W, PAD, edges: g.data.edges.filter((e: any) => pos[e.customer_id] && pos[e.supplier_id]) };
  }, [g.data]);

  async function addEdge(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget).entries()) as Record<string, string>;
    await act(async () => {
      await crm("/edges", { method: "POST", body: {
        customer_id: f.customer_id, supplier_id: f.supplier_id, revenue_share: f.revenue_share === "" ? null : +f.revenue_share / 100,
        lag_days: f.lag_days === "" ? null : +f.lag_days, confidence: f.confidence, source: f.source || null, relation: f.relation,
      } });
      dlg.current?.close();
      g.reload(); ov.reload();
    }, "關係已新增");
  }

  const top = ov.data?.[0]?.combined_pct || 1;
  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h2>關係圖</h2>
          <span className="legend-crm"><i className="sw core" />核心 <i className="sw satellite" />衛星 <i className="sw watch" />觀察 <i className="sw blacklist" />黑名單 <i className="sw none" />無卡片</span>
          <span className="muted small">線寬 = 客戶佔供應商營收比重；橘線 = 夥伴，綠線 = 成分股（ETF 持有權重）。點節點看卡片；台股節點沒有卡片也能看公司概況並一鍵建卡。</span>
          <button className="ghost" onClick={() => dlg.current?.showModal()}>＋ 新增關係</button>
        </div>
        {g.error && <div className="empty up">CRM 無法連線：{g.error}</div>}
        {layout && (
          <div className="graph">
            <svg viewBox={`0 0 ${layout.W} ${layout.H}`} width={layout.W} height={layout.H}>
              {Object.keys(layout.layers).map((d) => (
                <text key={d} className="layer-label" x={layout.PAD + Number(d) * layout.L_W + 60} y={18}>{Number(d) === 0 ? "終端客戶 / 夥伴 / ETF" : `第 ${d} 層供應商 / 成分股`}</text>
              ))}
              {layout.edges.map((e: any) => {
                const a = layout.pos[e.customer_id], b = layout.pos[e.supplier_id], mx = (a.x + b.x) / 2;
                const w = e.revenue_share == null ? 1 : 1 + e.revenue_share * 14;
                const on = hover === e.customer_id || hover === e.supplier_id;
                return (
                  <path key={e.id} className={`edge ${e.relation} ${hover ? (on ? "hi" : "dim") : ""}`} strokeWidth={w} strokeDasharray={e.revenue_share == null ? "4 4" : undefined}
                    d={`M${a.x},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x},${b.y}`}>
                    <title>{`${layout.byId[e.customer_id].name} → ${layout.byId[e.supplier_id].name}（${L.relation[e.relation]}）：${pct0(e.revenue_share)}，${e.lag_days ?? "?"} 天，信心${L.conf[e.confidence]}${e.source ? "，" + e.source : ""}`}</title>
                  </path>
                );
              })}
              {layout.nodes.map((n: any) => {
                const p = layout.pos[n.id], r = n.stage === "hold" ? 10 + Math.sqrt(n.position_pct || 0) * 3 : 8;
                return (
                  <g key={n.id} className="node" transform={`translate(${p.x},${p.y})`} onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}
                    onClick={() => (n.stage || n.id.startsWith("TW:") ? card.open(n.id) : toast(n.id + " 還沒有卡片，而且不是台股，用「＋ 新卡片」建立"))}>
                    <circle r={r} fill={n.tier ? `var(--${n.tier})` : "var(--none)"} />
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
        <table>
          <tbody>
            <tr><th>客戶</th><th className="num">直接%</th><th className="num">間接%</th><th className="num">合計%</th><th>經由</th><th style={{ width: "30%" }}></th></tr>
            {(ov.data ?? []).map((o) => (
              <tr key={o.customer_id}>
                <td>{o.customer_name} <span className="kv">{o.customer_id}</span></td><td className="num">{o.directly_held_pct}</td><td className="num">{o.indirect_total_pct}</td><td className="num"><b>{o.combined_pct}</b></td>
                <td className="kv">{o.via.map((v: any) => `${v.name} ${v.exposure_pct}%`).join("、")}</td>
                <td><div className="bar" style={{ width: `${Math.min(100, (o.combined_pct / top) * 100)}%` }} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <dialog ref={dlg}>
        <form onSubmit={addEdge}>
          <h3>新增關係</h3>
          <label>關係類型<select name="relation"><option value="customer">客戶 → 供應商（客戶向供應商採購）</option><option value="partner">夥伴 → 我方（產能或授權夥伴）</option><option value="holding">ETF → 成分股（持有權重）</option></select></label>
          <label>客戶 / 夥伴<select name="customer_id">{(g.data?.nodes ?? []).map((n: any) => <option key={n.id} value={n.id}>{n.name} ({n.id})</option>)}</select></label>
          <label>供應商 / 我方<select name="supplier_id">{(g.data?.nodes ?? []).map((n: any) => <option key={n.id} value={n.id}>{n.name} ({n.id})</option>)}</select></label>
          <div className="row">
            <label>佔供應商營收 %<input name="revenue_share" type="number" min="0" max="100" step="1" placeholder="25" /></label>
            <label>時間差（天）<input name="lag_days" type="number" min="0" placeholder="60" /></label>
          </div>
          <div className="row">
            <label>信心<select name="confidence" defaultValue="medium"><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></label>
            <label>來源<input name="source" placeholder="年報 / 法說 / 估計" /></label>
          </div>
          <menu><button type="button" className="ghost" onClick={() => dlg.current?.close()}>取消</button><button className="primary">新增</button></menu>
        </form>
      </dialog>
    </>
  );
}
