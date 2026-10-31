import { useEffect, useRef, type FormEvent } from "react";
import { crm, engine, useAsync } from "../../api/client";
import { useCard } from "../../components/CardDrawer";
import { useAction } from "../../components/Toast";
import { cls, num, pctS, signed, toCode } from "../../lib/format";
import { L } from "../../lib/labels";

/** Column header extra for 持有: total market value and today's P&L when shares are filled in. */
function HoldTotals({ cards, mktBy }: { cards: any[]; mktBy: Record<string, any> }) {
  let mv = 0, day = 0, cost = 0, n = 0;
  for (const p of cards) {
    const code = toCode(p.company_id);
    const m = code ? mktBy[code] : null;
    if (!p.shares || !m || m.price == null) continue;
    n++;
    mv += p.shares * m.price;
    if (m.change != null) day += p.shares * m.change;
    if (p.avg_cost) cost += p.shares * p.avg_cost;
  }
  if (!n) return null;
  return (
    <span className="muted" style={{ marginLeft: 8, textTransform: "none", letterSpacing: 0 }}>
      市值 {num(mv / 1e4, 0)} 萬 · 今日 <b className={cls(day)}>{signed(day / 1e4, 1)} 萬</b>{cost ? <> · 未實現 <b className={cls(mv - cost)}>{pctS(((mv / cost) - 1) * 100, 1)}</b></> : null}
    </span>
  );
}

export default function Board() {
  const card = useCard();
  const act = useAction();
  const list = useAsync<any[]>(() => crm("/positions"), [card.version]);
  // engine snapshot for TW cards (price / today % / foreign flow); CRM 持有/觀察 lists keep these codes subscribed
  const mkt = useAsync<any[]>(() => engine("/watchlist").catch(() => []), [card.version], 30000);
  const mktBy: Record<string, any> = Object.fromEntries((mkt.data ?? []).map((r) => [r.code, r]));
  const templates = useAsync<any[]>(() => crm("/templates"), []);
  const dlg = useRef<HTMLDialogElement>(null);
  const rows = list.data ?? [];
  const cols: Record<string, any[]> = { hold: [], watch: [], exited: [] };
  rows.forEach((p) => cols[p.stage]?.push(p));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && dlg.current?.close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget).entries());
    const el = e.currentTarget;
    await act(async () => {
      await crm("/positions", { method: "POST", body: f });
      dlg.current?.close();
      el.reset();
      list.reload();
    }, "卡片已建立");
  }

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h2>看板</h2>
          <span className="muted small">依階段分欄，左側色條是分層，顯示論點狀態與幾天沒更新。</span>
          <button className="primary" onClick={() => dlg.current?.showModal()}>＋ 新卡片</button>
        </div>
        {list.error && <div className="empty up">CRM 無法連線：{list.error}（請確認 stockcrm 在 8765 執行）</div>}
        <div className="board">
          {(["hold", "watch", "exited"] as const).map((s) => (
            <div className="col" key={s}>
              <h3><span>{L.stage[s]}</span><span>{cols[s].length}{s === "hold" ? " · " + cols[s].reduce((a, p) => a + p.position_pct, 0).toFixed(1) + "%" : ""}{s === "hold" && <HoldTotals cards={cols[s]} mktBy={mktBy} />}</span></h3>
              {cols[s].map((p) => {
                const stale = p.stage === "hold" && p.days_since_update >= 30;
                const m = toCode(p.company_id) ? mktBy[toCode(p.company_id)!] : null;
                return (
                  <div className={`card ${p.tier}`} key={p.id} onClick={() => card.open(p.id)}>
                    <div className="top">
                      <span><span className="name">{p.name}</span> <span className="ticker">{p.company_id}</span></span>
                      <span>{p.health_issues ? <span className="badge hi" title="健康度警示">⚠ {p.health_issues}</span> : null} <span className={`badge ${p.tier}`}>{L.tier[p.tier]}</span></span>
                    </div>
                    <div className="meta">
                      <span><i className={`dot ${p.thesis_status}`} />論點{L.thesis[p.thesis_status]}</span>
                      {p.stage === "hold" && <span>部位 {p.position_pct}%</span>}
                      <span className={stale ? "stale" : ""}>{p.days_since_update == null ? "" : p.days_since_update + " 天未更新"}</span>
                      <span>{p.interaction_count} 筆紀錄</span>
                    </div>
                    {m && m.price != null && (
                      <div className="mkt-line">
                        <span className={cls(m.change)}>{num(m.price)} {pctS(m.change_pct)}</span>
                        {p.shares ? <span className="muted">市值 {num((p.shares * m.price) / 1e4, 0)} 萬{p.avg_cost ? <> · <b className={cls(m.price - p.avg_cost)}>{pctS(((m.price / p.avg_cost) - 1) * 100, 1)}</b></> : null}</span> : null}
                        {m.foreign_net_lots != null && <span className="muted">外資 <b className={cls(m.foreign_net_lots)}>{signed(m.foreign_net_lots)}</b> 張</span>}
                        {p.target_price && <span className="muted">目標 {pctS(((p.target_price / m.price) - 1) * 100, 0)}</span>}
                      </div>
                    )}
                    {p.latest_brief?.text && <div className="brief-line" title={p.latest_brief.text}>{p.latest_brief.date} · {p.latest_brief.text}</div>}
                  </div>
                );
              })}
              {cols[s].length === 0 && <div className="empty">沒有卡片</div>}
            </div>
          ))}
        </div>
      </section>

      <dialog ref={dlg}>
        <form onSubmit={create}>
          <h3>新卡片</h3>
          <div className="row">
            <label>市場<select name="market"><option>TW</option><option>US</option></select></label>
            <label>代號<input name="ticker" required placeholder="2330" /></label>
          </div>
          <label>名稱<input name="name" required placeholder="台積電" /></label>
          <div className="row">
            <label>階段<select name="stage"><option value="watch">觀察</option><option value="hold">持有</option><option value="exited">已出場</option></select></label>
            <label>分層<select name="tier"><option value="watch">觀察</option><option value="satellite">衛星</option><option value="core">核心</option><option value="blacklist">黑名單</option></select></label>
          </div>
          <label>投資論點<textarea name="thesis" rows={3} /></label>
          <label>失效條件<textarea name="invalidation" rows={2} /></label>
          <label>想法來源<input name="idea_source" placeholder="self / 朋友 / 券商報告" /></label>
          <label>論點模板（預填驅動因子與檢查點，可之後再改）
            <select name="template"><option value="">不套用</option>{(templates.data ?? []).map((t) => <option key={t.key} value={t.key}>{t.label}（{t.description}）</option>)}</select>
          </label>
          <menu><button type="button" className="ghost" onClick={() => dlg.current?.close()}>取消</button><button className="primary">建立</button></menu>
        </form>
      </dialog>
    </>
  );
}
