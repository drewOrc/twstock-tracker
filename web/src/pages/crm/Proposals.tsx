import { useState } from "react";
import { crm, useAsync } from "../../api/client";
import { Md } from "../../components/CardDrawer";
import { useAction } from "../../components/Toast";
import { tpe } from "../../lib/format";
import { L } from "../../lib/labels";

export default function Proposals() {
  const act = useAction();
  const [history, setHistory] = useState(false);
  const list = useAsync<any[]>(() => crm(`/proposals?status=${history ? "all" : "pending"}`), [history], 60000);
  const decide = (id: number, approve: boolean) =>
    act(async () => { await crm(`/proposals/${id}/decide`, { method: "POST", body: { approve } }); list.reload(); }, approve ? "已套用" : undefined);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>提案</h2>
        <label className="muted small"><input type="checkbox" checked={history} onChange={(e) => setHistory(e.target.checked)} /> 顯示已處理</label>
      </div>
      {list.error && <div className="empty up">CRM 無法連線：{list.error}</div>}
      {list.data?.length === 0 && <div className="empty">沒有待審提案。agent 提出的新互動紀錄、供應鏈關係、驅動因子數值、檢查點結果或論點狀態變更會出現在這裡。</div>}
      {(list.data ?? []).map((p) => (
        <div className="proposal" key={p.id}>
          <div className="head">
            <span><span className="badge">{L.pkind[p.kind] || p.kind}</span> <span className="summary">{p.summary}</span></span>
            <span className={`status ${p.status}`}>{p.created_by} · {tpe(p.created_at)}{p.status !== "pending" ? " · " + (p.status === "approved" ? "已核准" : "已拒絕") : ""}</span>
          </div>
          <div className="rationale"><Md text={p.rationale} /></div>
          <details><summary>內容</summary><pre>{JSON.stringify(p.payload, null, 1)}</pre></details>
          {p.status === "pending" && (
            <div className="actions"><button className="primary tiny" onClick={() => decide(p.id, true)}>核准並套用</button><button className="ghost tiny" onClick={() => decide(p.id, false)}>拒絕</button></div>
          )}
        </div>
      ))}
    </section>
  );
}
