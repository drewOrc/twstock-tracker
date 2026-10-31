import { useState } from "react";
import { engine, useAsync } from "../api/client";
import { useAction, useToast } from "../components/Toast";
import { cls, pctS, signed, yi } from "../lib/format";

const heat = (v: number | null | undefined) => {
  if (v == null) return "transparent";
  const a = Math.min(Math.abs(v) / 4, 1) * 0.45;
  return v > 0 ? `rgba(239,83,80,${a})` : v < 0 ? `rgba(38,166,154,${a})` : "transparent";
};
const PctCell = ({ v }: { v: number | null | undefined }) =>
  v == null ? <span className="muted">–</span> : <span className={`heat ${cls(v)}`} style={{ background: heat(v) }}>{signed(v, 2)}%</span>;

export default function Market() {
  const toast = useToast();
  const act = useAction();
  const dates = useAsync<string[]>(() => engine("/market/dates?limit=60"), []);
  const [date, setDate] = useState<string | null>(null);
  const d = date ?? dates.data?.[0] ?? null;
  const b = useAsync(() => (d ? engine(`/market/breadth?date=${d}`) : Promise.resolve(null)), [d]);
  const hist = useAsync<any[]>(() => engine("/market/breadth/history?days=30"), [dates.data]);
  const sh = useAsync(() => engine("/market/sectors/history?days=10"), [dates.data]);
  const [open, setOpen] = useState<Record<string, any[]>>({});

  const nav = (delta: number) => {
    const list = dates.data ?? [];
    const i = list.indexOf(d ?? "");
    const j = i + delta;
    if (j >= 0 && j < list.length) setDate(list[j]);
  };
  const runJob = (name: string, msg: string, wait: number) =>
    act(async () => {
      await engine(`/jobs/${name}/run`, { method: "POST" });
      toast(msg);
      setTimeout(() => { dates.reload(); b.reload(); hist.reload(); sh.reload(); }, wait);
    });
  const toggleSector = async (name: string) => {
    if (open[name]) { const { [name]: _x, ...rest } = open; setOpen(rest); return; }
    await act(async () => setOpen({ ...open, [name]: await engine(`/market/sectors/${encodeURIComponent(name)}/stocks?date=${d}`) }));
  };

  const x = b.data;
  const cum: Record<string, number | null> = {};
  (sh.data?.sectors ?? []).forEach((s: any) => (cum[s.name] = s.cum_pct));

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>盤面分化</h2>
        <div className="market-nav">
          <button className="ghost" onClick={() => nav(1)} title="前一交易日">‹</button>
          <select value={d ?? ""} onChange={(e) => setDate(e.target.value)}>
            {(dates.data ?? []).map((v) => <option key={v}>{v}</option>)}
          </select>
          <button className="ghost" onClick={() => nav(-1)} title="後一交易日">›</button>
          <button className="ghost" onClick={() => runJob("market_daily", "全市場更新已開始，約 10 秒", 10000)}>更新全市場</button>
          <button className="ghost" onClick={() => runJob("market_backfill", "回補 20 日已在背景開始，約 1–2 分鐘", 90000)}>回補 20 日</button>
        </div>
      </div>
      {!x?.available && !b.loading && <div className="empty">尚無全市場資料，按「更新全市場」或「回補 20 日」。</div>}
      {x?.available && (
        <>
          <Tiles b={x} />
          <div className="mk-grid">
            <div className="mk-block">
              <h3>漲跌家數走勢 <span className="muted">（紅＝上漲、綠＝下跌；線＝上漲比例）</span></h3>
              <BreadthChart hist={hist.data ?? []} current={d} />
            </div>
            <div className="mk-block">
              <h3>漲跌幅分布 <span className="muted">（一般股票）</span></h3>
              <Dist dist={x.distribution} />
            </div>
          </div>
          <div className="mk-block">
            <h3>類股強弱 <span className="muted">（點擊類股展開成分股；累計為近 {sh.data?.dates?.length ?? 0} 日平均漲跌複利）</span></h3>
            <div className="table-wrap tall">
              <table>
                <thead>
                  <tr><th>類股</th><th className="num">家數</th><th className="num">漲/跌</th><th className="num">平均%</th><th className="num">中位%</th><th className="num" title="證交所官方類股指數漲跌%（僅上市）">類指數%</th><th className="num">累計%</th><th className="num">成交佔比</th><th>領漲</th><th>領跌</th></tr>
                </thead>
                <tbody>
                  {x.sectors.map((s: any) => (
                    <SectorRow key={s.name} s={s} cum={cum[s.name] ?? null} stocks={open[s.name]} onToggle={() => toggleSector(s.name)} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="mk-grid three">
            <Movers title="漲幅前 15" sub="（成交額 ≥ 2 千萬）" rows={x.top_gainers} />
            <Movers title="跌幅前 15" rows={x.top_losers} />
            <Movers title="成交金額前 10" rows={x.turnover_leaders} share />
          </div>
        </>
      )}
    </section>
  );
}

function Tiles({ b }: { b: any }) {
  const a = b.markets.ALL, t = b.markets.TWSE, o = b.markets.TPEX, dv = b.divergence;
  const tiles: [string, React.ReactNode, string][] = [
    ["上漲 / 下跌 / 平盤", <><span className="up">{a.advance}</span> / <span className="down">{a.decline}</span> / {a.flat}</>, `上市 ${t.advance}/${t.decline} · 上櫃 ${o.advance}/${o.decline}`],
    ["上漲比例", `${a.adv_ratio ?? "–"}%`, `上市 ${t.adv_ratio ?? "–"}% · 上櫃 ${o.adv_ratio ?? "–"}%`],
    ["漲停 / 跌停", <><span className="up">{a.limit_up}</span> / <span className="down">{a.limit_down}</span></>, t.source === "official" ? "上市為證交所官方統計" : "依漲跌幅 ±9.5% 估算"],
    ["加權指數", b.index_pct == null ? "–" : <span className={cls(b.index_pct)}>{pctS(b.index_pct)}</span>, `個股中位數 ${pctS(a.median_pct)} · 平均 ${pctS(a.mean_pct)}`],
    ["指數 − 中位數", dv.index_minus_median == null ? "–" : <span className={cls(dv.index_minus_median)}>{pctS(dv.index_minus_median)}</span>, "正值＝權值股撐盤、個股普遍較弱"],
    ["前 5 大成交佔比", `${dv.top5_turnover_share}%`, `一般股票成交額 ${yi(a.turnover)}`],
  ];
  return (
    <div className="tiles">
      {tiles.map(([k, v, s]) => (
        <div className="tile" key={k}><div className="k">{k}</div><div className="v">{v}</div><div className="s">{s}</div></div>
      ))}
    </div>
  );
}

function BreadthChart({ hist, current }: { hist: any[]; current: string | null }) {
  if (!hist.length) return <div className="muted">尚無歷史</div>;
  const W = 640, H = 160, padL = 34, padR = 30, top = 10, base = 95, bottom = 150;
  const n = hist.length, slot = (W - padL - padR) / n, bw = Math.max(2, slot * 0.6);
  const maxv = Math.max(...hist.map((h) => Math.max(h.advance, h.decline)), 1);
  const upH = base - top, dnH = bottom - base - 14;
  const pts: string[] = [];
  const bars = hist.map((h, i) => {
    const x = padL + i * slot + (slot - bw) / 2;
    const hu = (h.advance / maxv) * upH, hd = (h.decline / maxv) * dnH;
    if (h.adv_ratio != null) pts.push(`${x + bw / 2},${top + (1 - h.adv_ratio / 100) * (bottom - 14 - top)}`);
    const sel = h.date === current;
    return (
      <g key={h.date}>
        <rect x={x} y={base - hu} width={bw} height={hu} fill="#ef5350" opacity={0.85} stroke={sel ? "#fff" : "none"}><title>{`${h.date} 上漲 ${h.advance} 漲停 ${h.limit_up}`}</title></rect>
        <rect x={x} y={base} width={bw} height={hd} fill="#26a69a" opacity={0.85} stroke={sel ? "#fff" : "none"}><title>{`${h.date} 下跌 ${h.decline} 跌停 ${h.limit_down}`}</title></rect>
        {i % Math.ceil(n / 8) === 0 && <text x={x + bw / 2} y={H - 2} fontSize={9} fill="#8b97a8" textAnchor="middle">{h.date.slice(5)}</text>}
      </g>
    );
  });
  return (
    <div className="svg-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        <line x1={padL} y1={base} x2={W - padR} y2={base} stroke="#2a3441" />
        {bars}
        {pts.length > 1 && <polyline points={pts.join(" ")} fill="none" stroke="#f5c542" strokeWidth={1.5} />}
        <text x={2} y={top + 8} fontSize={9} fill="#f5c542">100%</text>
        <text x={2} y={bottom - 12} fontSize={9} fill="#f5c542">0%</text>
        <text x={W - padR + 3} y={base - 2} fontSize={9} fill="#ef5350">{maxv}</text>
      </svg>
    </div>
  );
}

function Dist({ dist }: { dist: any[] }) {
  const max = Math.max(...dist.map((d) => d.count), 1);
  return (
    <div className="dist">
      {dist.map((d) => {
        const c = d.label === "0" ? "" : d.label.startsWith("-") || d.label.startsWith("<") ? "down" : "up";
        return (
          <div className="row" key={d.label}>
            <span className="muted">{d.label}</span>
            <div className={`bar ${c}`} style={{ width: `${(d.count / max) * 100}%` }} />
            <span className="num">{d.count}</span>
          </div>
        );
      })}
    </div>
  );
}

function Chips({ xs }: { xs: any[] }) {
  return <>{xs.map((x) => <span key={x.code} className={`chip ${cls(x.pct)}`} title={x.code}>{x.name} {signed(x.pct, 1)}%</span>)}</>;
}

function SectorRow({ s, cum, stocks, onToggle }: { s: any; cum: number | null; stocks?: any[]; onToggle: () => void }) {
  return (
    <>
      <tr className="sector-row" onClick={onToggle}>
        <td><b>{s.name}</b></td>
        <td className="num">{s.count}</td>
        <td className="num"><span className="up">{s.advance}</span>/<span className="down">{s.decline}</span></td>
        <td className="num"><PctCell v={s.avg_pct} /></td>
        <td className="num"><PctCell v={s.median_pct} /></td>
        <td className="num"><PctCell v={s.index_pct} /></td>
        <td className="num"><PctCell v={cum} /></td>
        <td className="num">{s.turnover_share.toFixed(1)}%</td>
        <td><Chips xs={s.leaders} /></td>
        <td><Chips xs={s.laggards} /></td>
      </tr>
      {stocks && (
        <tr className="sector-stocks">
          <td colSpan={10}>
            <div className="stock-chips">
              {stocks.map((r) => (
                <span key={r.code} className={`chip ${cls(r.pct)}`} title={r.code}>{r.code} {r.name} {r.pct == null ? "" : pctS(r.pct)} <span className="muted">{yi(r.turnover)}</span></span>
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function Movers({ title, sub, rows, share }: { title: string; sub?: string; rows: any[]; share?: boolean }) {
  return (
    <div className="mk-block">
      <h3>{title} {sub && <span className="muted">{sub}</span>}</h3>
      <ol className="movers">
        {rows.map((r) => (
          <li key={r.code}>
            <span className="n"><b>{r.code}</b> {r.name} <span className="sec">{r.sector}</span></span>
            <span className={cls(r.pct)}>{pctS(r.pct)}</span>
            <span className="muted">{yi(r.turnover)}{share ? ` (${r.share}%)` : ""}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
