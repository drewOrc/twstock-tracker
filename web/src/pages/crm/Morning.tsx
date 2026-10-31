import { crm, useAsync } from "../../api/client";
import { useCard } from "../../components/CardDrawer";
import { useAction, useToast } from "../../components/Toast";
import { pct0, tpe } from "../../lib/format";
import { JOB_L, L, Q_L } from "../../lib/labels";

export default function Morning() {
  const card = useCard();
  const toast = useToast();
  const act = useAction();
  const m = useAsync(() => crm("/morning"), [card.version]);
  // Newer CRM builds expose /maintenance; older ones 404 -> the panel simply hides.
  const maint = useAsync(() => crm("/maintenance").catch(() => null), [card.version]);
  if (m.error) return <section className="panel"><div className="empty up">CRM 無法連線：{m.error}</div></section>;
  if (!m.data) return <section className="panel"><div className="empty">載入中…</div></section>;
  // Older CRM builds lack attention / upcoming_checkpoints; render the rest regardless.
  const d = { attention: [], upcoming_checkpoints: [], shaken_or_broken: [], stale_holdings: [], due_reminders: [], holdings: [], counterparties_to_check: [], ...m.data };

  const cps: any[] = d.counterparties_to_check;
  const prompt = `請用 stockcrm 的 get_morning_context 拿今天的持股、對手方清單與 attention 列表，然後：
1. 先看 attention：逾期檢查點、落後的驅動因子、偏離的指標。對每一項找最新資訊，能確認或推翻的用 propose_checkpoint_resolution / propose_driver_value 提案。
2. 查 counterparties_to_check 裡每家公司過去 24 小時的重大新聞或財報（特別是 ${cps.filter((c) => c.market === "US").map((c) => c.name).join("、")}）。
3. 對每則會影響我持股論點的消息，用 propose_interaction 提案，掛到相關的 driver_id 或 checkpoint_id，effect 填 supports / weakens / confirms，rationale 要說明它和哪個驅動因子或失效條件有關。
4. 如果某檔持股的失效條件看起來被觸發，用 propose_thesis_status 提案改成 shaken 或 broken。
5. 最後用繁體中文給我一頁早晨簡報：先講會影響論點的事，再講其他。${d.tw_monthly_revenue_window ? "\n6. 現在是台股月營收公布期間（每月 1 到 10 號），查我台股持股的最新月營收，用 propose_metric（metric=revenue_m）提案。" : ""}`;

  const applyFlags = () => act(async () => { const r = await crm("/checks/apply", { method: "POST" }); toast(`已將 ${r.length} 張卡片標為動搖`); m.reload(); });
  const runJob = (job: string) => act(async () => { const r = await crm("/maintenance/run", { method: "POST", body: { job } }); toast(r.summary); maint.reload(); });
  const A = ({ id, children }: { id: string; children: React.ReactNode }) => <a className="link" onClick={() => card.open(id)}>{children}</a>;

  return (
    <>
      <section className="panel">
        <h3>需要注意（{d.attention.length}）<span className="kv" style={{ marginLeft: 8 }}>逾期檢查點、落後的驅動因子、偏離模型的指標</span>
          {d.attention.some((a: any) => a.suggest_shaken) && <button className="ghost tiny" style={{ float: "right" }} onClick={applyFlags}>把建議的卡片標為動搖</button>}
        </h3>
        {d.attention.length ? d.attention.map((a: any) => (
          <div className="att" key={a.position_id}>
            <b><A id={a.company_id}>{a.name}</A></b> <span className="kv">{a.company_id} · 論點{L.thesis[a.thesis_status]}{a.suggest_shaken ? " · 建議標為動搖" : ""}</span>
            <ul className="issues">{a.issues.map((i: any) => <li key={i.ref} className={i.severity}>{i.message}</li>)}</ul>
          </div>
        )) : <div className="ok-box">沒有需要注意的卡片。</div>}
        {d.upcoming_checkpoints.length > 0 && <div className="kv" style={{ marginTop: 10 }}><b>14 天內到期的檢查點</b>：{d.upcoming_checkpoints.map((c: any) => `${c.company_name}／${c.title}（${c.expected_by}）`).join("、")}</div>}
      </section>

      <div className="grid2">
        <section className="panel">
          <h3>持股狀態</h3>
          <table><tbody>
            <tr><th>持股</th><th>分層</th><th className="num">部位%</th><th>論點</th><th className="num">未更新</th></tr>
            {d.holdings.map((h: any) => (
              <tr key={h.company_id}>
                <td><A id={h.company_id}>{h.name}</A> <span className="kv">{h.company_id}</span></td><td><span className={`badge ${h.tier}`}>{L.tier[h.tier]}</span></td><td className="num">{h.position_pct}</td>
                <td><i className={`dot ${h.thesis_status}`} />{L.thesis[h.thesis_status]}</td><td className={`num ${h.days_since_update >= 30 ? "stale" : ""}`}>{h.days_since_update} 天</td>
              </tr>
            ))}
          </tbody></table>
          {d.shaken_or_broken.length > 0 && <div className="warn-box" style={{ marginTop: 10 }}>論點動搖或失效：{d.shaken_or_broken.map((s: any) => s.name).join("、")}</div>}
          {d.stale_holdings.length > 0 && <div className="kv" style={{ marginTop: 8 }}>超過 30 天沒更新：{d.stale_holdings.map((s: any) => `${s.name} ${s.days} 天`).join("、")}</div>}
        </section>

        <section className="panel">
          <h3>今天該檢查的對手方（{cps.length}）</h3>
          <div className="kv" style={{ marginBottom: 6 }}>這些公司是你持股的客戶、供應商或夥伴。美股昨晚的消息會先反映在這裡。</div>
          {["US", "TW"].map((mk) => (
            <div key={mk}>
              <div className="kv" style={{ marginTop: 6 }}><b>{mk}</b></div>
              {cps.filter((c) => c.market === mk).map((c) => (
                <div className="rel" key={c.company_id}>
                  <span>{c.name} <span className="kv">{c.company_id}</span></span>
                  <span className="kv">{c.role_to_holdings.map((r: any) => `${r.role === "customer" ? "是" : "供應"} ${r.holding_name} ${r.role === "customer" ? "的客戶" : ""} ${r.revenue_share != null ? pct0(r.revenue_share) : ""}`).join("；")}</span>
                </div>
              ))}
            </div>
          ))}
        </section>

        <section className="panel">
          <h3>7 天內提醒</h3>
          {d.due_reminders.length ? d.due_reminders.map((r: any) => <div className="rel" key={r.id}><span>{r.due_date} · {L.rkind[r.kind]} · {r.content}</span><span className="kv">{r.company_name || ""}</span></div>) : <div className="kv">無</div>}
          <div className="kv" style={{ marginTop: 10 }}>{d.tw_monthly_revenue_window ? "現在是台股月營收公布期間（1 到 10 號）。" : "台股月營收公布期間是每月 1 到 10 號。"} 待審提案 {d.pending_proposals} 件。</div>
        </section>

        <section className="panel">
          <h3>交給 agent 的早晨任務</h3>
          <div className="kv" style={{ marginBottom: 6 }}>在 Claude Code 裡貼上這段，它會透過 stockcrm 的 MCP 工具讀資料並提案：</div>
          <pre className="prompt">{prompt}</pre>
          <button className="ghost tiny" onClick={() => navigator.clipboard.writeText(prompt).then(() => toast("已複製"))}>複製</button>
        </section>

        {maint.data && (
          <section className="panel">
            <h3>維護狀態 <span className="kv">腳本直接寫入官方事實（system:mops），其餘走提案</span></h3>
            {Object.entries(maint.data.last ?? {}).map(([j, r]: [string, any]) => (
              <div className="rel" key={j}><span>{JOB_L[j] || j}</span><span className="kv">{r ? <><span className={`status ${r.status === "ok" ? "approved" : r.status === "error" ? "rejected" : ""}`}>{r.status}</span> {tpe(r.ts)} · {r.summary}</> : "還沒跑過"}</span></div>
            ))}
            <div style={{ margin: "10px 0 6px", display: "flex", gap: 6, flexWrap: "wrap" }}>
              {[["fetch-monthly", "抓月營收"], ["fetch-quarterly", "抓季報"], ["fetch-shares", "抓股數"], ["backup", "備份"], ["quality", "品質檢查"]].map(([job, label]) => (
                <button key={job} className="ghost tiny" onClick={() => runJob(job)}>{label}</button>
              ))}
            </div>
            <div><b>資料品質（{maint.data.quality?.total ?? 0}）</b>
              {Object.entries(Q_L).filter(([k]) => (maint.data.quality?.[k] || []).length).map(([k, label]) => (
                <details key={k}><summary>{label}（{maint.data.quality[k].length}）</summary>
                  <ul className="issues">{maint.data.quality[k].map((it: any, i: number) => <li key={i} className="low">{Object.entries(it).filter(([, v]) => v != null).map(([kk, v]) => `${kk}=${v}`).join("，")}</li>)}</ul>
                </details>
              ))}
            </div>
          </section>
        )}
      </div>
    </>
  );
}
