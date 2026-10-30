import { useState } from "react";
import { engine, useAsync } from "../api/client";
import { useAction, useToast } from "../components/Toast";
import { cls, num, pctS, signed, yi } from "../lib/format";

const tagClass = (t: string) => (/外資|投信|融資/.test(t) ? "chip" : /新高|量能|逆勢/.test(t) ? "hot" : "");
const Ratio = ({ v }: { v: number | null }) => (v == null ? <>–</> : <span className={cls(v)}>{signed(v * 100, 1)}%</span>);

export default function Screener() {
  const toast = useToast();
  const act = useAction();
  const meta = useAsync(() => engine("/screener/presets"), []);
  const [preset, setPreset] = useState("balanced");
  const dates = useAsync<string[]>(() => engine(`/screener/dates?preset=${preset}`), [preset]);
  const [date, setDate] = useState<string | null>(null);
  const d = date && dates.data?.includes(date) ? date : dates.data?.[0] ?? null;
  const res = useAsync(() => (d ? engine(`/screener?preset=${preset}&date=${d}&limit=50`) : Promise.resolve(null)), [preset, d]);
  const watch = useAsync<any[]>(() => engine("/watchlist"), []);
  const [turnover, setTurnover] = useState("0.5");
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const watched = new Set((watch.data ?? []).map((w) => w.code));

  async function run(notify: boolean) {
    setBusy(true);
    await act(async () => {
      const r = await engine("/screener/run", { method: "POST", body: { preset, min_turnover: Number(turnover) * 1e8, top: 50, notify } });
      toast(`掃描完成：${r.date}，母體 ${r.universe} 檔${r.delivery ? "，通知 " + Object.entries(r.delivery).map(([k, v]) => `${k}=${v}`).join(" ") : ""}`);
      setDate(r.date);
      await dates.reload();
      res.reload();
    });
    setBusy(false);
  }
  const addWatch = (code: string) =>
    act(async () => {
      const r = await engine("/watchlist", { method: "POST", body: { code, note: `選股掃描 ${d}` } });
      toast(`已加入 ${r.code} ${r.name}，背景補歷史中`);
      watch.reload();
    });

  const rows: any[] = res.data?.results ?? [];
  const factors: Record<string, string> = meta.data?.factors ?? {};

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>選股掃描</h2>
        <div className="market-nav">
          <select value={preset} onChange={(e) => { setPreset(e.target.value); setDate(null); }}>
            {(meta.data?.presets ?? []).map((p: any) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select>
          <select value={d ?? ""} onChange={(e) => setDate(e.target.value)}>
            {(dates.data ?? []).map((v) => <option key={v}>{v}</option>)}
          </select>
          <label className="muted small">成交額 ≥ <input type="number" step="0.1" min="0" style={{ width: "4.5em" }} value={turnover} onChange={(e) => setTurnover(e.target.value)} /> 億</label>
          <button disabled={busy} onClick={() => run(false)}>重新掃描</button>
          <button disabled={busy} className="ghost" onClick={() => run(true)} title="掃描並把前 10 名推播到已設定的通知管道">掃描並通知</button>
        </div>
      </div>
      <p className="hint">
        {res.data?.date ? `${res.data.date} · ${res.data.label ?? preset} · 顯示前 ${rows.length} 名。` : ""}
        分數是全市場百分位排名加權（0–100），不是機率；點列可展開全部因子，用標籤理解每檔為什麼入選。
      </p>
      {!rows.length && !res.loading && <div className="empty">尚未掃描。先確定盤面分化有資料，再按「重新掃描」。</div>}
      {rows.length > 0 && (
        <div className="table-wrap tall">
          <table>
            <thead>
              <tr>
                <th>#</th><th>代號</th><th>名稱</th><th>類股</th><th className="num">收盤</th><th className="num">今日%</th>
                <th className="num" title="20 日漲幅減去加權指數同期漲幅">RS20</th><th className="num" title="收盤 / 前 20 日最高">突破</th>
                <th className="num" title="今日成交量 / 20 日均量">量能</th><th className="num" title="外資 5 日淨買超佔 5 日成交量">外資5日</th>
                <th className="num" title="投信 5 日淨買超佔 5 日成交量">投信5日</th><th className="num">分數</th><th>訊號</th><th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((x) => {
                const f = x.factors ?? {};
                return (
                  <FragmentRow key={x.code}>
                    <tr className="sc-row" onClick={() => setOpen(open === x.code ? null : x.code)}>
                      <td className="muted">{x.rank}</td>
                      <td><b>{x.code}</b></td>
                      <td>{f.name}</td>
                      <td className="muted">{f.sector_name}</td>
                      <td className="num">{num(f.close)}</td>
                      <td className={`num ${cls(f.pct)}`}>{pctS(f.pct)}</td>
                      <td className={`num ${cls(f.rs20)}`}>{pctS(f.rs20, 1)}</td>
                      <td className="num">{f.breakout == null ? "–" : num(f.breakout, 2)}</td>
                      <td className="num">{f.vol_ratio == null ? "–" : num(f.vol_ratio, 1) + "x"}</td>
                      <td className="num"><Ratio v={f.foreign5 ?? null} /></td>
                      <td className="num"><Ratio v={f.trust5 ?? null} /></td>
                      <td className="num"><span className="score-bar"><i style={{ width: `${x.score}%` }} /></span>{x.score.toFixed(0)}</td>
                      <td>{(x.tags ?? []).map((t: string) => <span key={t} className={`tag ${tagClass(t)}`}>{t}</span>)}</td>
                      <td>{watched.has(x.code) ? <span className="badge live">追蹤中</span> : <button className="ghost" onClick={(e) => { e.stopPropagation(); addWatch(x.code); }}>加入追蹤</button>}</td>
                    </tr>
                    {open === x.code && (
                      <tr className="factor-row">
                        <td colSpan={14}>
                          {Object.entries(factors).filter(([k]) => f[k] !== undefined).map(([k, label]) => (
                            <span key={k} className="factor">{label}：<b>{f[k] == null ? "–" : typeof f[k] === "number" ? (Math.abs(f[k]) < 10 ? f[k].toFixed(2) : f[k].toFixed(1)) : String(f[k])}</b> ｜ </span>
                          ))}
                          <span className="muted">成交額 {yi(f.turnover)}</span>
                        </td>
                      </tr>
                    )}
                  </FragmentRow>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function FragmentRow({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
