import { engine, useAsync } from "../api/client";
import { useAction, useToast } from "../components/Toast";
import { time } from "../lib/format";

const JOB_LABELS: Record<string, string> = {
  full_daily: "每日全部（日線 + 全市場 + 法人 + 融資券 + 警示 + 掃描）",
  daily_prices: "日線 + 全市場",
  institutional: "三大法人 + 選股掃描",
  margin: "融資融券",
  market_daily: "全市場（盤面分化）",
  market_backfill: "回補 20 日全市場",
  flows_backfill: "回補 20 日法人 / 融資券",
  screener: "選股掃描（四個預設）",
  alerts_daily: "評估日線型警示",
  stock_list: "更新公司清單",
  realtime: "即時報價一次",
};

export default function Jobs() {
  const toast = useToast();
  const act = useAction();
  const health = useAsync(() => engine("/health"), [], 30000);
  const jobs = useAsync(() => engine("/jobs"), [], 30000);
  const runs = useAsync<any[]>(() => engine("/jobs/runs?limit=30"), [], 20000);
  const h = health.data;

  const run = (name: string) =>
    act(async () => {
      await engine(`/jobs/${name}/run`, { method: "POST" });
      toast(`${JOB_LABELS[name] ?? name} 已在背景開始`);
      setTimeout(runs.reload, 8000);
    });
  const notifyTest = () =>
    act(async () => {
      const r = await engine("/notify/test", { method: "POST", body: { message: "測試通知 from 台股追蹤引擎" } });
      toast("通知結果：" + Object.entries(r.result).map(([k, v]) => `${k}=${v}`).join("; "));
    });

  return (
    <>
      <section className="panel">
        <div className="panel-head"><h2>系統狀態</h2><button className="ghost" onClick={notifyTest}>測試通知</button></div>
        {h && (
          <div className="tiles">
            <div className="tile"><div className="k">引擎</div><div className="v">{h.status}</div><div className="s">{h.time}</div></div>
            <div className="tile"><div className="k">排程器</div><div className="v">{h.scheduler.running ? "運行中" : "停止"}</div><div className="s">{h.trading_hours ? "盤中" : "非交易時段"}</div></div>
            <div className="tile"><div className="k">Stock CRM</div><div className={`v ${h.crm?.reachable ? "" : "up"}`}>{h.crm?.reachable ? "已連線" : "離線"}</div><div className="s">{h.crm?.url}</div></div>
            <div className="tile"><div className="k">通知管道</div><div className="v">{Object.entries(h.channels).filter(([, on]) => on).map(([k]) => k).join(", ") || "無"}</div><div className="s">LINE / Email 在 .env 設定</div></div>
            <div className="tile"><div className="k">即時輪詢</div><div className="v">{jobs.data?.realtime?.quotes ?? 0} 檔</div><div className="s">{jobs.data?.realtime?.skipped ?? (jobs.data?.realtime?.last_success ? time(jobs.data.realtime.last_success) : "尚未")}{jobs.data?.realtime?.error ? ` · ${jobs.data.realtime.error}` : ""}</div></div>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-head"><h2>手動執行</h2></div>
        <div className="job-buttons">
          {Object.entries(JOB_LABELS).map(([k, label]) => (
            <button key={k} className="ghost" onClick={() => run(k)}>{label}</button>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-head"><h2>排程</h2></div>
        <div className="jobs-grid">
          {(jobs.data?.scheduled ?? []).map((s: any) => (
            <div className="job-card" key={s.id}><b>{s.name}</b><span className="next">下次：{time(s.next_run)}</span></div>
          ))}
          {jobs.data && jobs.data.scheduled.length === 0 && <div className="muted">排程未啟用（SCHEDULER_ENABLED=false）</div>}
        </div>
      </section>

      <section className="panel">
        <div className="panel-head"><h2>工作紀錄</h2></div>
        <ul className="runs">
          {(runs.data ?? []).map((r) => (
            <li key={r.id}><time>{time(r.started_at)}</time><span className={r.ok ? "ok" : "fail"}>{r.ok ? "OK " : "ERR"}</span> {r.job} {r.detail}</li>
          ))}
        </ul>
      </section>
    </>
  );
}
