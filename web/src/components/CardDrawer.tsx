/* Stock CRM position card as a right-hand drawer, openable from any page via useCard().open(ref). */
import { createContext, useCallback, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { crm } from "../api/client";
import { cnum, pct0, spct, tpe } from "../lib/format";
import { L } from "../lib/labels";
import { useAction, useToast } from "./Toast";

interface CardCtx {
  open: (ref: string | number) => void;
  close: () => void;
  version: number; // bumped after any write done inside the drawer, so pages can refresh
}
const Ctx = createContext<CardCtx>({ open: () => {}, close: () => {}, version: 0 });
export const useCard = () => useContext(Ctx);

export function CardProvider({ children }: { children: ReactNode }) {
  const [ref, setRef] = useState<string | number | null>(null);
  const [version, setVersion] = useState(0);
  const open = useCallback((r: string | number) => setRef(r), []);
  const close = useCallback(() => setRef(null), []);
  return (
    <Ctx.Provider value={{ open, close, version }}>
      {children}
      {ref !== null && <Drawer refId={ref} onClose={close} onChanged={() => setVersion((v) => v + 1)} onOpen={open} />}
    </Ctx.Provider>
  );
}

/** Minimal Markdown: **bold** and line breaks. */
export function Md({ text }: { text: string | null | undefined }) {
  const lines = String(text ?? "").split("\n");
  return (
    <>
      {lines.map((line, i) => (
        <span key={i}>
          {line.split(/(\*\*.+?\*\*)/g).map((part, j) => (part.startsWith("**") && part.endsWith("**") ? <b key={j}>{part.slice(2, -2)}</b> : part))}
          {i < lines.length - 1 && <br />}
        </span>
      ))}
    </>
  );
}

const fd = (e: FormEvent<HTMLFormElement>) => Object.fromEntries(new FormData(e.currentTarget).entries()) as Record<string, string>;

function Drawer({ refId, onClose, onChanged, onOpen }: { refId: string | number; onClose: () => void; onChanged: () => void; onOpen: (r: string | number) => void }) {
  const toast = useToast();
  const act = useAction();
  const [p, setP] = useState<any | null>(null);
  const [tierMsg, setTierMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [exposure, setExposure] = useState<any | null>(null);
  const [templates, setTemplates] = useState<any[]>([]);
  const [openSeries, setOpenSeries] = useState<Record<number, boolean>>({});
  const [form, setForm] = useState<any>({});

  const load = useCallback(async () => {
    try {
      const card = await crm(`/positions/${encodeURIComponent(String(refId))}`);
      // Tolerate a CRM build that predates drivers / checkpoints / metrics (stockcrm main before its PR #1).
      card.drivers ??= [];
      card.checkpoints ??= [];
      card.reminders ??= [];
      card.interactions ??= [];
      card.customers ??= [];
      card.suppliers ??= [];
      card.concentration ??= {};
      card.metrics ??= { comparisons: [], run_rate: [], monthly: [], monthly_yoy: [], has_data: false };
      card.health ??= { status: "ok", issues: [], suggest_shaken: false };
      setP(card);
      setForm({
        stage: card.stage, tier: card.tier, position_pct: card.position_pct, target_price: card.target_price ?? "", stop_price: card.stop_price ?? "",
        target_basis: card.target_basis ?? "", model_url: card.model_url ?? "", thesis: card.thesis ?? "", invalidation: card.invalidation ?? "",
      });
    } catch (e: any) {
      toast(e.message, true);
      onClose();
    }
  }, [refId, toast, onClose]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (p && p.drivers.length === 0 && p.checkpoints.length === 0 && templates.length === 0) crm("/templates").then(setTemplates).catch(() => {});
  }, [p, templates.length]);

  const reload = () => { load(); onChanged(); };
  const write = (fn: () => Promise<unknown>, ok?: string) => act(async () => { await fn(); reload(); }, ok);

  if (!p) return <div className="backdrop show" onClick={onClose} />;
  const c = p.concentration;
  const health = p.health;
  const F = (k: string) => (e: any) => setForm({ ...form, [k]: e.target.value });

  const save = () =>
    write(() => crm("/positions", { method: "POST", body: {
      company_id: p.company_id, stage: form.stage, tier: form.tier, position_pct: +form.position_pct, thesis: form.thesis, invalidation: form.invalidation,
      target_price: form.target_price === "" ? null : +form.target_price, stop_price: form.stop_price === "" ? null : +form.stop_price,
      target_basis: form.target_basis, model_url: form.model_url,
    } }), "已儲存");

  const checkTier = async (v: string) => {
    setForm({ ...form, position_pct: v });
    try { const r = await crm(`/positions/${p.id}/tier_check?new_pct=${v || 0}`); setTierMsg({ ok: !r.exceeds_limit, text: r.message }); } catch { /* ignore */ }
  };

  const rel = (list: any[], key: string, nameKey: string, dir: string) =>
    list.length ? list.map((e) => (
      <div className="rel" key={e.id}>
        <span>{e.relation === "partner" ? "夥伴" : e.relation === "holding" ? (dir === "客戶" ? "持有它的 ETF" : "成分股") : dir} <a onClick={() => onOpen(e[key])}>{e[nameKey]}</a> <span className="kv">{e[key]}</span></span>
        <span className="kv">{pct0(e.revenue_share)} · {e.lag_days ?? "?"} 天 · 信心{L.conf[e.confidence]}</span>
      </div>
    )) : <div className="kv">無</div>;

  return (
    <>
      <div className="backdrop show" onClick={onClose} />
      <aside className="drawer open">
        <div className="drawer-inner">
          <button className="close" onClick={onClose}>×</button>
          <h2>{p.company.name} <span className="ticker">{p.company_id}</span> <span className={`badge ${p.tier}`}>{L.tier[p.tier]}</span></h2>
          <div className="kv">{p.company.sector || ""} · 想法來源：{p.idea_source || "未填"} · {p.days_since_update ?? "?"} 天未更新{p.tags?.length ? " · " + p.tags.join(", ") : ""}</div>

          <section>
            {health.issues.length ? (
              <div className="warn-box"><b>健康度警示</b>
                <ul className="issues">{health.issues.map((i: any) => <li key={i.ref} className={i.severity}>{i.message}</li>)}</ul>
                {health.suggest_shaken && <div className="kv">有高嚴重度問題而論點仍標成立。建議改為動搖，或處理上面的項目。</div>}
              </div>
            ) : <div className="ok-box">健康度正常：沒有逾期檢查點、落後的驅動因子或偏離的指標。</div>}
          </section>

          <section>
            <div className="row3">
              <label>階段<select value={form.stage} onChange={F("stage")}>{Object.entries(L.stage).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
              <label>分層<select value={form.tier} onChange={F("tier")}>{Object.entries(L.tier).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
              <label>部位 %<input type="number" step="0.5" min="0" value={form.position_pct} onChange={(e) => checkTier(e.target.value)} /></label>
            </div>
            {tierMsg && <div className={tierMsg.ok ? "ok-box" : "warn-box"}>{tierMsg.text}</div>}
            <div className="row3">
              <label>目標價<input type="number" step="any" value={form.target_price} onChange={F("target_price")} /></label>
              <label>停損價<input type="number" step="any" value={form.stop_price} onChange={F("stop_price")} /></label>
              <label>目標價依據<input placeholder="PE 30 × 2027E EPS" value={form.target_basis} onChange={F("target_basis")} /></label>
            </div>
            <label>估值模型檔案<input placeholder="試算表路徑或連結" value={form.model_url} onChange={F("model_url")} /></label>
          </section>

          <section>
            <h4>投資論點{" "}
              <span className="seg">
                {Object.entries(L.thesis).map(([k, v]) => (
                  <button key={k} className={k === p.thesis_status ? "on" : ""} onClick={() => write(() => crm(`/positions/${p.id}/thesis_status`, { method: "POST", body: { status: k } }), "論點狀態已更新")}>{v}</button>
                ))}
              </span>
            </h4>
            <textarea rows={3} value={form.thesis} onChange={F("thesis")} />
          </section>
          <section>
            <h4>失效條件</h4>
            <textarea rows={2} value={form.invalidation} onChange={F("invalidation")} />
            <div style={{ marginTop: 8, display: "flex", gap: 8, justifyContent: "flex-end" }}><button className="primary" onClick={save}>儲存卡片</button></div>
          </section>

          {/* drivers */}
          <section>
            <h4>驅動因子 <span className="kv">論點的量化假設，模型 vs 實際</span>
              {templates.length > 0 && p.drivers.length === 0 && p.checkpoints.length === 0 && (
                <select className="tiny-select" defaultValue="" onChange={(e) => e.target.value && write(() => crm(`/positions/${p.id}/template`, { method: "POST", body: { template: e.target.value } }), "模板已套用，請調整檢查點日期")}>
                  <option value="">套用模板…</option>
                  {templates.map((t) => <option key={t.key} value={t.key}>{t.label}：{t.drivers.join("、")}</option>)}
                </select>
              )}
            </h4>
            <table className="drivers">
              <tbody>
                <tr><th>驅動因子</th><th className="num">實際 / 模型</th><th>訊號</th><th></th></tr>
                {p.drivers.map((d: any) => {
                  const lc = d.latest_comparison, last = d.series.length ? d.series[d.series.length - 1] : null;
                  return (
                    <DriverRows key={d.id} d={d} lc={lc} last={last} open={!!openSeries[d.id]}
                      onToggle={() => setOpenSeries({ ...openSeries, [d.id]: !openSeries[d.id] })}
                      onDelete={() => confirm("刪除這個驅動因子與它的所有數值？") && write(() => crm(`/drivers/${d.id}`, { method: "DELETE" }))}
                      onValue={(e) => { e.preventDefault(); const f = fd(e); write(() => crm(`/drivers/${d.id}/values`, { method: "POST", body: { period: f.period, kind: f.kind, value: +f.value, source: f.source || null } }), "數值已儲存"); }} />
                  );
                })}
                {p.drivers.length === 0 && <tr><td colSpan={4} className="kv">還沒有驅動因子。★ 是關鍵因子，被削弱或落後模型會讓論點動搖。</td></tr>}
              </tbody>
            </table>
            <form className="row4" style={{ marginTop: 8 }} onSubmit={(e) => { e.preventDefault(); const f = fd(e); const el = e.currentTarget; write(() => crm(`/positions/${p.id}/drivers`, { method: "POST", body: { name: f.name, unit: f.unit || null, sensitivity: f.sensitivity || null, critical: f.critical ? 1 : 0 } })).then(() => el.reset()); }}>
              <input name="name" placeholder="名稱，例如 出貨台數" required /><input name="unit" placeholder="單位" />
              <input name="sensitivity" placeholder="敏感度，例如 每台 0.25 EPS" /><label className="inline"><input type="checkbox" name="critical" defaultChecked /> 關鍵</label>
              <button className="ghost tiny" style={{ gridColumn: "1/-1" }}>＋ 新增驅動因子</button>
            </form>
          </section>

          {/* checkpoints */}
          <section>
            <h4>檢查點 <span className="kv">到某日前該看到的證據</span></h4>
            {p.checkpoints.map((k: any) => (
              <div key={k.id} className={`cp ${k.status} ${k.overdue ? "overdue" : ""}`}>
                <div>
                  <span className={`pill-s ${k.overdue ? "bad" : k.status}`}>{k.overdue ? "逾期" : L.cstatus[k.status]}</span> <b>{k.title}</b>{" "}
                  <span className="kv">{k.expected_by}{k.status === "pending" ? (k.days_left >= 0 ? `，還有 ${k.days_left} 天` : `，逾期 ${-k.days_left} 天`) : ""}{k.driver_name ? " · " + k.driver_name : ""}</span>
                  {k.evidence_needed && <div className="kv">要看到：{k.evidence_needed}</div>}
                  {k.evidence && <div className="kv">證據：{k.evidence}</div>}
                </div>
                <div className="actions-cell">
                  {k.status === "pending" ? (
                    <>
                      <button className="ghost tiny" onClick={() => { const ev = prompt("看到了什麼證據？"); if (ev !== null) write(() => crm(`/checkpoints/${k.id}/resolve`, { method: "POST", body: { status: "confirmed", evidence: ev } })); }}>確認</button>{" "}
                      <button className="ghost tiny" onClick={() => { const ev = prompt("為什麼判定未達成？"); if (ev !== null) write(() => crm(`/checkpoints/${k.id}/resolve`, { method: "POST", body: { status: "missed", evidence: ev } })); }}>未達</button>
                    </>
                  ) : (
                    <button className="ghost tiny" onClick={() => write(() => crm(`/checkpoints/${k.id}/resolve`, { method: "POST", body: { status: "pending" } }))}>重開</button>
                  )}{" "}
                  <button className="ghost tiny" onClick={() => confirm("刪除這個檢查點？") && write(() => crm(`/checkpoints/${k.id}`, { method: "DELETE" }))}>×</button>
                </div>
              </div>
            ))}
            {p.checkpoints.length === 0 && <div className="kv">還沒有檢查點。「到某個日期前應該看到某個證據」，逾期沒證據就是警訊。</div>}
            <form className="row4" style={{ marginTop: 8 }} onSubmit={(e) => { e.preventDefault(); const f = fd(e); const el = e.currentTarget; write(() => crm(`/positions/${p.id}/checkpoints`, { method: "POST", body: { title: f.title, expected_by: f.expected_by, evidence_needed: f.evidence_needed || null, driver_id: f.driver_id ? +f.driver_id : null } })).then(() => el.reset()); }}>
              <input name="title" placeholder="標題，例如 首批出貨" required /><input name="expected_by" type="date" required />
              <input name="evidence_needed" placeholder="要看到什麼證據" />
              <select name="driver_id"><option value="">不綁驅動因子</option>{p.drivers.map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
              <button className="ghost tiny" style={{ gridColumn: "1/-1" }}>＋ 新增檢查點</button>
            </form>
          </section>

          {/* metrics */}
          <section>
            <h4>標準指標 <span className="kv">月營收、季報六個數，模型 vs 實際</span></h4>
            <Metrics m={p.metrics} />
            <form className="row4" style={{ marginTop: 8 }} onSubmit={(e) => { e.preventDefault(); const f = fd(e); let v = +f.value; if (f.metric === "gross_margin" && v > 1) v = v / 100; write(() => crm(`/metrics/${encodeURIComponent(p.company_id)}`, { method: "POST", body: { metric: f.metric, period: f.period, kind: f.kind, value: v } }), "指標已儲存"); }}>
              <select name="metric">{Object.entries(L.metric).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
              <input name="period" placeholder="2026Q2 / 2026-05" required />
              <select name="kind"><option value="model">模型</option><option value="actual">實際</option></select>
              <input name="value" type="number" step="any" placeholder="數值（千元 / 0..1 / 千股）" required />
              <button className="ghost tiny" style={{ gridColumn: "1/-1" }}>儲存指標</button>
            </form>
          </section>

          {/* relations */}
          <section>
            <h4>供應鏈關係</h4>
            <div style={{ marginBottom: 6 }}>
              {c.largest_customer ? <span className={`badge ${{ high: "hi", medium: "mid", low: "lo" }[c.flag as string]}`}>最大客戶 {c.largest_customer_name} {pct0(c.largest_customer_share)}</span> : <span className="kv">尚無客戶資料</span>}
            </div>
            {rel(p.customers, "customer_id", "customer_name", "客戶")}
            {rel(p.suppliers, "supplier_id", "supplier_name", "供應商")}
            <div style={{ marginTop: 8 }}>
              <button className="ghost tiny" onClick={() => act(async () => setExposure(await crm(`/exposure/${encodeURIComponent(p.company_id)}`)))}>看組合對 {p.company.name} 的間接曝險</button>
              {exposure && (exposure.exposures.length ? (
                <table>
                  <tbody>
                    <tr><th>持股</th><th className="num">部位%</th><th className="num">曝險%</th><th>路徑</th></tr>
                    {exposure.exposures.map((e: any) => <tr key={e.company_id}><td>{e.name}</td><td className="num">{e.position_pct}</td><td className="num">{e.exposure_pct}</td><td className="kv">{e.paths.map((pp: any) => pp.path.join(" → ")).join("；")}</td></tr>)}
                    <tr><td colSpan={2}><b>間接合計</b></td><td className="num"><b>{exposure.indirect_total_pct}</b></td><td></td></tr>
                  </tbody>
                </table>
              ) : <div className="kv" style={{ marginTop: 6 }}>沒有持股以這家公司為客戶。</div>)}
            </div>
          </section>

          {/* reminders */}
          <section>
            <h4>提醒</h4>
            {p.reminders.map((r: any) => <div className="rel" key={r.id}><span>{r.due_date} · {L.rkind[r.kind]} · {r.content}</span><button className="ghost tiny" onClick={() => write(() => crm(`/reminders/${r.id}/done`, { method: "POST" }))}>完成</button></div>)}
            {p.reminders.length === 0 && <div className="kv">無</div>}
            <form className="row3" style={{ marginTop: 8 }} onSubmit={(e) => { e.preventDefault(); const f = fd(e); const el = e.currentTarget; write(() => crm("/reminders", { method: "POST", body: { due_date: f.due_date, kind: f.kind, content: f.content, position_id: p.id } })).then(() => el.reset()); }}>
              <input name="due_date" type="date" required /><select name="kind">{Object.entries(L.rkind).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
              <input name="content" placeholder="提醒內容" required /><button className="ghost tiny" style={{ gridColumn: "1/-1" }}>＋ 新增提醒</button>
            </form>
          </section>

          {/* interactions */}
          <section>
            <h4>互動紀錄（{p.interactions.length}）</h4>
            <form onSubmit={(e) => {
              e.preventDefault(); const f = fd(e); const el = e.currentTarget;
              const body: any = { kind: f.kind, content: f.content, price: f.price ? +f.price : null, behavior_tags: f.behavior_tags.split(",").map((s) => s.trim()).filter(Boolean), effect: f.effect || null };
              if (f.link.startsWith("d:")) body.driver_id = +f.link.slice(2);
              if (f.link.startsWith("c:")) body.checkpoint_id = +f.link.slice(2);
              if (f.link && !body.effect) { toast("請選擇這筆紀錄對關聯項目的影響", true); return; }
              write(() => crm(`/positions/${p.id}/interactions`, { method: "POST", body }), "已記錄").then(() => el.reset());
            }}>
              <div className="row3">
                <select name="kind">{Object.entries(L.kind).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
                <input name="price" type="number" step="any" placeholder="當時價格" />
                <input name="behavior_tags" placeholder="行為標籤：chasing, fomo" />
              </div>
              <div className="row" style={{ marginTop: 8 }}>
                <select name="link">
                  <option value="">不關聯</option>
                  {p.drivers.map((d: any) => <option key={`d${d.id}`} value={`d:${d.id}`}>驅動：{d.name}</option>)}
                  {p.checkpoints.filter((k: any) => k.status === "pending").map((k: any) => <option key={`c${k.id}`} value={`c:${k.id}`}>檢查點：{k.title}</option>)}
                </select>
                <select name="effect"><option value="">對它的影響…</option>{Object.entries(L.effect).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
              </div>
              <textarea name="content" rows={2} placeholder="發生了什麼？為什麼？" required style={{ marginTop: 8 }} />
              <div style={{ marginTop: 6, display: "flex", justifyContent: "flex-end" }}><button className="primary">記一筆</button></div>
            </form>
            <ul className="timeline" style={{ marginTop: 10 }}>
              {p.interactions.map((i: any) => (
                <li key={i.id} className={i.kind}>
                  <div className="when">{tpe(i.ts)}{i.price != null ? " · " + i.price : ""}<span className="by">{i.created_by}</span></div>
                  <span className="kind">{L.kind[i.kind]}</span>{i.effect && <span className={`pill-s ${i.effect}`}>{L.effect[i.effect]}</span>}<Md text={i.content} />
                  {i.behavior_tags?.length ? <div className="kv">標籤：{i.behavior_tags.join(", ")}</div> : null}
                  {i.source_url && <div className="kv"><a href={i.source_url} target="_blank" rel="noopener noreferrer">來源</a></div>}
                </li>
              ))}
            </ul>
          </section>
        </div>
      </aside>
    </>
  );
}

function DriverRows({ d, lc, last, open, onToggle, onDelete, onValue }: { d: any; lc: any; last: any; open: boolean; onToggle: () => void; onDelete: () => void; onValue: (e: FormEvent<HTMLFormElement>) => void }) {
  return (
    <>
      <tr>
        <td>{d.critical ? "★ " : ""}{d.name} <span className="kv">{d.unit || ""}</span>{d.sensitivity && <div className="kv">{d.sensitivity}</div>}</td>
        <td className="num">{lc ? <>{cnum(lc.actual)} / {cnum(lc.model)}<div className="kv">{lc.period} {spct(lc.gap_pct)}</div></> : last ? <>{last.actual != null ? cnum(last.actual) : "–"} / {last.model != null ? cnum(last.model) : "–"}<div className="kv">{last.period}</div></> : "–"}</td>
        <td><span className={`sig ${d.signal}`}>{L.signal[d.signal]}</span>{d.latest_effect && <div className="kv">最近證據：{L.effect[d.latest_effect]}</div>}</td>
        <td className="actions-cell"><button className="ghost tiny" onClick={onToggle} title="填數值">＋值</button> <button className="ghost tiny" onClick={onDelete} title="刪除">×</button></td>
      </tr>
      {open && (
        <tr className="series-row">
          <td colSpan={4}>
            <table className="inner">
              <tbody>
                <tr><th>期間</th><th className="num">模型</th><th className="num">實際</th><th className="num">差距</th><th>來源</th></tr>
                {d.series.map((s: any) => <tr key={s.period}><td>{s.period}</td><td className="num">{s.model != null ? cnum(s.model) : "–"}</td><td className="num">{s.actual != null ? cnum(s.actual) : "–"}</td><td className="num">{spct(s.gap_pct)}</td><td className="kv">{s.source || ""}</td></tr>)}
                {d.series.length === 0 && <tr><td colSpan={5} className="kv">還沒有數值</td></tr>}
              </tbody>
            </table>
            <form className="row4" onSubmit={onValue}>
              <input name="period" placeholder="2026 / 2026Q2 / 2026-05" required /><select name="kind"><option value="model">模型</option><option value="actual">實際</option></select>
              <input name="value" type="number" step="any" placeholder="數值" required /><input name="source" placeholder="來源" />
              <button className="ghost tiny" style={{ gridColumn: "1/-1" }}>儲存數值</button>
            </form>
            {d.evidence.length > 0 && <div className="kv" style={{ marginTop: 6 }}>證據：{d.evidence.map((e: any) => `${tpe(e.ts).slice(0, 10)} ${e.effect ? "［" + L.effect[e.effect] + "］" : ""}${e.content}`).join(" / ")}</div>}
          </td>
        </tr>
      )}
    </>
  );
}

function Metrics({ m }: { m: any }) {
  const rr = m.run_rate.map((r: any) => (
    <tr key={"rr" + r.period} className={r.flag ? "flag" : ""}><td>{r.period} run-rate</td><td className="num">{cnum(r.model)}</td><td className="num">{cnum(r.projected)}<div className="kv">{r.months_available} 個月{r.final ? "，已完整" : "，推估"}</div></td><td className="num">{spct(r.gap_pct)}</td></tr>
  ));
  const cmp = m.comparisons.filter((t: any) => t.metric !== "revenue_m").map((t: any) => (
    <tr key={t.metric + t.period} className={t.flag ? "flag" : ""}><td>{t.label} {t.period}</td><td className="num">{t.metric === "gross_margin" ? pct0(t.model) : cnum(t.model)}</td><td className="num">{t.metric === "gross_margin" ? pct0(t.actual) : cnum(t.actual)}</td><td className="num">{t.gap == null ? "" : t.metric === "gross_margin" ? (t.gap * 100).toFixed(1) + " pp" : spct(t.gap)}</td></tr>
  ));
  return (
    <>
      <table><tbody>
        <tr><th>指標</th><th className="num">模型</th><th className="num">實際</th><th className="num">差距</th></tr>
        {rr}{cmp}
        {!rr.length && !cmp.length && <tr><td colSpan={4} className="kv">還沒有可對照的指標。填入模型季營收與實際月營收，就會算 run-rate。</td></tr>}
      </tbody></table>
      {m.monthly.length > 0 && (
        <div className="kv" style={{ marginTop: 6 }}>月營收：{m.monthly.map((x: any) => `${x.period} ${cnum(x.value)}`).join("、")}
          {m.monthly_yoy.length > 0 && <><br />年增率：{m.monthly_yoy.map((x: any) => `${x.period} ${spct(x.yoy)}`).join("、")}</>}
        </div>
      )}
    </>
  );
}
