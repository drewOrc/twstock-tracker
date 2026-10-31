import { admin, engine, publicApi, useAsync } from "../api/client";
import { useMe } from "../components/Auth";
import { useAction, useToast } from "../components/Toast";
import { time } from "../lib/format";

/** Which job feeds which table, so the health table can show when it last succeeded. */
const TABLE_JOBS: Record<string, string[]> = {
  daily_prices: ["daily_prices", "full_daily", "market_daily"],
  market_stats: ["market_daily", "daily_prices", "full_daily", "market_backfill"],
  index_daily: ["market_daily", "daily_prices", "full_daily", "market_backfill"],
  institutional_flows: ["institutional", "full_daily", "flows_backfill"],
  margin_balances: ["margin", "full_daily", "flows_backfill"],
  screener_results: ["screener", "institutional", "full_daily"],
  stocks: ["stock_list"],
};
function lastOkFor(lastOk: Record<string, string>, table: string): string {
  const cands = (TABLE_JOBS[table] ?? []).map((j) => [j, lastOk[j]] as const).filter(([, t]) => t);
  if (!cands.length) return "–";
  cands.sort((a, b) => (a[1] < b[1] ? 1 : -1));
  return `${cands[0][0]} · ${time(cands[0][1])}`;
}

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

const STATUS_L: Record<string, string> = { ok: "正常", warn: "落後 1 日", bad: "過期", missing: "無資料", idle: "待機" };

export default function Jobs() {
  const toast = useToast();
  const act = useAction();
  const { me } = useMe();
  const isAdmin = me?.role === "admin";
  const health = useAsync(() => publicApi("/health"), [], 30000);
  const data = useAsync(() => engine("/health/data"), [], 60000);
  const jobs = useAsync(() => engine("/jobs"), [], 30000);
  const runs = useAsync<any[]>(() => engine("/jobs/runs?limit=30"), [], 20000);
  const h = health.data;
  const dh = data.data;

  const run = (name: string) =>
    act(async () => {
      await admin(`/jobs/${name}/run`, { method: "POST" });
      toast(`${JOB_LABELS[name] ?? name} 已在背景開始`);
      setTimeout(runs.reload, 8000);
    });
  const notifyTest = () =>
    act(async () => {
      const r = await admin("/notify/test", { method: "POST", body: { message: "測試通知 from 台股追蹤引擎" } });
      toast("通知結果：" + Object.entries(r.result).map(([k, v]) => `${k}=${v}`).join("; "));
    });

  return (
    <>
      <section className="panel">
        <div className="panel-head"><h2>系統狀態</h2>{isAdmin && <button className="ghost" onClick={notifyTest}>測試通知</button>}</div>
        {h && (
          <div className="tiles">
            <div className="tile"><div className="k">引擎</div><div className="v">{h.status}</div><div className="s">{h.time}</div></div>
            <div className="tile"><div className="k">排程器</div><div className="v">{h.scheduler.running ? "運行中" : "停止"}</div><div className="s">{h.trading_hours ? "盤中" : "非交易時段"}</div></div>
            <div className="tile"><div className="k">對外網址</div><div className={`v ${h.public_url ? "" : "muted"}`} style={{ fontSize: 14, wordBreak: "break-all" }}>{h.public_url ? <a href={h.public_url.url} target="_blank" rel="noopener noreferrer">{h.public_url.url.replace(/^https:\/\//, "")}</a> : "未開放"}</div><div className="s">{h.public_url ? (h.public_url.kind === "temporary" ? `臨時隧道，重啟會變（${h.public_url.since ?? ""}）` : "固定網址") : "scripts\tunnel_quick_install.ps1 -Start"}</div></div>
            <div className="tile"><div className="k">Stock CRM</div><div className={`v ${h.crm?.reachable ? "" : "up"}`}>{h.crm?.reachable ? "已連線" : "離線"}</div><div className="s">{h.crm?.url}</div></div>
            <div className="tile"><div className="k">通知管道</div><div className="v">{Object.entries(h.channels).filter(([, on]) => on).map(([k]) => k).join(", ") || "無"}</div><div className="s">LINE / Email 在 .env 設定</div></div>
            <div className="tile"><div className="k">即時輪詢</div><div className="v">{jobs.data?.realtime?.quotes ?? 0} 檔</div><div className="s">{jobs.data?.realtime?.skipped ?? (jobs.data?.realtime?.last_success ? time(jobs.data.realtime.last_success) : "尚未")}{jobs.data?.realtime?.error ? ` · ${jobs.data.realtime.error}` : ""}</div></div>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>資料健康 {dh && <span className={`pill-st ${dh.overall}`}>{STATUS_L[dh.overall] ?? dh.overall}</span>}</h2>
          <span className="muted small">{dh ? `檢查時間 ${time(dh.checked_at)} · 追蹤 ${dh.counts.watched_codes} 檔 · 啟用警示 ${dh.counts.alert_rules} 條 · 24h 觸發 ${dh.counts.alert_events_24h}` : "載入中…"}</span>
          <button className="ghost tiny" onClick={() => data.reload()}>重新檢查</button>
        </div>
        {dh && (
          <>
            <div className="table-wrap">
              <table>
                <thead><tr><th>資料表</th><th className="num">筆數</th><th>最新</th><th>應有</th><th>狀態</th><th>最近一次成功的工作</th></tr></thead>
                <tbody>
                  {dh.tables.map((t: any) => (
                    <tr key={t.table}>
                      <td>{t.label} <span className="muted">{t.table}</span></td>
                      <td className="num">{t.rows.toLocaleString("zh-TW")}</td>
                      <td>{t.latest ?? "–"}</td>
                      <td className="muted">{t.expected}{t.publish_hour ? `（${t.publish_hour}:00 後）` : ""}</td>
                      <td><span className={`pill-st ${t.status}`}>{STATUS_L[t.status] ?? t.status}</span></td>
                      <td className="muted">{lastOkFor(dh.jobs.last_ok, t.table)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="health-foot">
              <span>資料庫 {dh.storage.db_mb ?? "–"} MB（WAL {dh.storage.wal_mb} MB）</span>
              <span>24 小時內工作 {dh.jobs.runs_24h} 次，失敗 {dh.jobs.failed_24h.length} 次</span>
              {dh.storage.log && <span>日誌 {dh.storage.log}</span>}
            </div>
            {dh.jobs.failed_24h.length > 0 && (
              <ul className="events-list">
                {dh.jobs.failed_24h.map((f: any, i: number) => <li key={i}><time>{time(f.at)}</time><span className="up">{f.job}</span> {f.detail}</li>)}
              </ul>
            )}
          </>
        )}
      </section>

      {isAdmin && <section className="panel">
        <div className="panel-head"><h2>手動執行 <span className="muted small">（管理員）</span></h2></div>
        <div className="job-buttons">
          {Object.entries(JOB_LABELS).map(([k, label]) => (
            <button key={k} className="ghost" onClick={() => run(k)}>{label}</button>
          ))}
        </div>
      </section>}

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
