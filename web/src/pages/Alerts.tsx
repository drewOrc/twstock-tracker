import { useState } from "react";
import { engine, useAsync } from "../api/client";
import { useAction, useToast } from "../components/Toast";
import { time } from "../lib/format";
import { CodeAlerts } from "./Watchlist";

/** Every alert rule across the watchlist, the event log, and a per-code editor. */
export default function Alerts() {
  const toast = useToast();
  const act = useAction();
  const types = useAsync<any[]>(() => engine("/alerts/rule-types"), []);
  const rules = useAsync<any[]>(() => engine("/alerts"), [], 30000);
  const events = useAsync<any[]>(() => engine("/alerts/events?limit=100"), [], 30000);
  const watch = useAsync<any[]>(() => engine("/watchlist"), []);
  const [code, setCode] = useState("");
  const label = (t: string) => types.data?.find((x) => x.type === t)?.label ?? t;
  const nameOf = (c: string) => watch.data?.find((w) => w.code === c)?.name ?? "";

  const evaluate = () =>
    act(async () => {
      const r = await engine("/alerts/evaluate", { method: "POST" });
      toast(`評估完成，觸發 ${r.alerts.length} 個警示`);
      events.reload();
      rules.reload();
    });

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h2>警示規則（{rules.data?.length ?? 0}）</h2>
          <label className="muted small">
            編輯股票{" "}
            <select value={code} onChange={(e) => setCode(e.target.value)}>
              <option value="">選擇…</option>
              {(watch.data ?? []).map((w) => <option key={w.code} value={w.code}>{w.code} {w.name}</option>)}
            </select>
          </label>
          <button className="ghost" onClick={() => act(async () => { const r = await engine("/alerts/sync-crm", { method: "POST" }); toast(r.skipped ? `略過：${r.skipped}` : `CRM 同步：新增 ${r.created}、更新 ${r.updated}、刪除 ${r.deleted}`); rules.reload(); })} title="把 CRM 卡片的目標價 / 停損價同步成警示規則">同步 CRM 目標價</button>
          <button className="ghost" onClick={evaluate} title="立刻用最新日線/籌碼資料評估所有規則">立即評估</button>
        </div>
        {code ? (
          <CodeAlerts code={code} />
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>股票</th><th>規則</th><th>參數</th><th>狀態</th><th>上次觸發</th><th></th></tr></thead>
              <tbody>
                {(rules.data ?? []).map((r) => (
                  <tr key={r.id}>
                    <td><b>{r.code}</b> {nameOf(r.code)}</td>
                    <td>{label(r.rule_type)}{r.source ? <span className="badge" title="由 CRM 卡片的目標價 / 停損價同步，改價請回卡片改"> CRM {r.source === "crm_target" ? "目標價" : "停損價"}</span> : null}{r.note && !r.source ? <span className="muted"> {r.note}</span> : null}</td>
                    <td className="muted">{Object.entries(r.params).map(([k, v]) => `${k}=${v}`).join(", ")}</td>
                    <td>{r.enabled ? <span className="badge live">啟用</span> : <span className="badge">停用</span>}{r.one_shot ? <span className="badge"> 單次</span> : null} <span className="muted">{r.cooldown_minutes}m</span></td>
                    <td className="muted">{time(r.last_triggered_at)}</td>
                    <td>
                      <button className="ghost" onClick={() => act(async () => { await engine(`/alerts/${r.id}`, { method: "PATCH", body: { enabled: !r.enabled } }); rules.reload(); })}>{r.enabled ? "停用" : "啟用"}</button>{" "}
                      <button className="danger" onClick={() => act(async () => { await engine(`/alerts/${r.id}`, { method: "DELETE" }); rules.reload(); })}>✕</button>
                    </td>
                  </tr>
                ))}
                {rules.data?.length === 0 && <tr><td colSpan={6} className="muted">尚無警示規則。在追蹤池選一檔股票的「警示」分頁或上方下拉選單新增。</td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-head"><h2>警示紀錄</h2></div>
        {events.data?.length === 0 && <div className="empty">尚無警示紀錄。</div>}
        <ul className="events-list">
          {(events.data ?? []).map((ev) => (
            <li key={ev.id}>
              <time>{time(ev.triggered_at)}</time>{ev.message}
              <span className="delivery">{ev.delivery ? Object.entries(ev.delivery).map(([k, v]) => `${k}:${v === "ok" ? "✓" : "✗"}`).join(" ") : ""}</span>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
