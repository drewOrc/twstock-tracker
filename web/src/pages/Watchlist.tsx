import { useEffect, useState, type FormEvent } from "react";
import { engine, useAsync } from "../api/client";
import { CandleChart } from "../components/Chart";
import { useAction, useToast } from "../components/Toast";
import { cls, int, num, pctS, signed, time } from "../lib/format";

type Tab = "chart" | "ind" | "inst" | "margin" | "alerts";

export default function Watchlist() {
  const toast = useToast();
  const act = useAction();
  const list = useAsync<any[]>(() => engine("/watchlist"), [], 15000);
  const [selected, setSelected] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [note, setNote] = useState("");
  const [options, setOptions] = useState<any[]>([]);
  const rows = list.data ?? [];

  useEffect(() => {
    if (!selected && rows.length) setSelected(rows[0].code);
  }, [rows, selected]);

  useEffect(() => {
    const q = code.trim();
    if (q.length < 1) return;
    const t = setTimeout(() => engine(`/stocks/search?q=${encodeURIComponent(q)}&limit=15`).then(setOptions).catch(() => {}), 250);
    return () => clearTimeout(t);
  }, [code]);

  async function add(e: FormEvent) {
    e.preventDefault();
    const c = (code.trim().split(/\s+/)[0] || "").toUpperCase();
    if (!c) return;
    const ok = await act(async () => {
      const r = await engine("/watchlist", { method: "POST", body: { code: c, note: note || null } });
      toast(`已加入 ${r.code} ${r.name}，正在背景補歷史資料…`);
      setCode("");
      setNote("");
      await list.reload();
      setSelected(r.code);
      setTimeout(list.reload, 15000);
      setTimeout(list.reload, 45000);
    });
    if (!ok) return;
  }

  async function remove(c: string) {
    if (!confirm(`移除 ${c}？相關警示規則也會刪除。`)) return;
    await act(async () => {
      await engine(`/watchlist/${c}`, { method: "DELETE" });
      if (selected === c) setSelected(null);
      await list.reload();
    }, `已移除 ${c}`);
  }

  async function refreshQuotes() {
    await act(async () => {
      const r = await engine("/quotes/refresh", { method: "POST" });
      toast(`已更新 ${r.quotes.length} 檔報價${r.alerts.length ? `，觸發 ${r.alerts.length} 個警示` : ""}`);
      list.reload();
    });
  }

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h2>追蹤池</h2>
          <form className="add-form" onSubmit={add} autoComplete="off">
            <input list="stock-options" placeholder="代號或名稱，例如 2330" value={code} onChange={(e) => setCode(e.target.value)} required />
            <datalist id="stock-options">
              {options.map((s) => (
                <option key={s.code} value={`${s.code} ${s.name}`} />
              ))}
            </datalist>
            <input placeholder="備註（選填）" value={note} onChange={(e) => setNote(e.target.value)} />
            <button type="submit">加入</button>
          </form>
          <button className="ghost" onClick={refreshQuotes} title="立即向證交所抓一次即時報價">
            更新報價
          </button>
        </div>
        {list.error && <div className="empty up">{list.error}</div>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>代號</th><th>名稱</th><th>市場</th>
                <th className="num">現價</th><th className="num">漲跌</th><th className="num">漲跌%</th><th className="num">量(張)</th>
                <th className="num" title="外資買賣超(張)">外資</th><th className="num" title="投信買賣超(張)">投信</th><th className="num" title="自營商買賣超(張)">自營</th>
                <th className="num" title="融資餘額(張) / 增減">融資</th><th className="num" title="融券餘額(張) / 增減">融券</th>
                <th>更新</th><th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.code} className={r.code === selected ? "selected" : ""} onClick={() => setSelected(r.code)}>
                  <td><b>{r.code}</b></td>
                  <td>{r.name}{r.note ? <span className="muted" title={r.note}> ※</span> : null}</td>
                  <td><span className="badge">{r.market === "TPEX" ? "上櫃" : "上市"}</span></td>
                  <td className={`num ${cls(r.change)}`}>{num(r.price)}</td>
                  <td className={`num ${cls(r.change)}`}>{signed(r.change, 2)}</td>
                  <td className={`num ${cls(r.change)}`}>{pctS(r.change_pct)}</td>
                  <td className="num">{int(r.volume_lots)}</td>
                  <td className={`num ${cls(r.foreign_net_lots)}`}>{signed(r.foreign_net_lots)}</td>
                  <td className={`num ${cls(r.trust_net_lots)}`}>{signed(r.trust_net_lots)}</td>
                  <td className={`num ${cls(r.dealer_net_lots)}`}>{signed(r.dealer_net_lots)}</td>
                  <td className="num">{int(r.margin_balance)} <span className={`muted ${cls(r.margin_change)}`}>{r.margin_change == null ? "" : `(${signed(r.margin_change)})`}</span></td>
                  <td className="num">{int(r.short_balance)} <span className={`muted ${cls(r.short_change)}`}>{r.short_change == null ? "" : `(${signed(r.short_change)})`}</span></td>
                  <td>{r.realtime ? <span className="badge live" title="即時">{r.quote_time}</span> : <span className="badge" title="日線收盤">{r.daily_date ?? "–"}</span>}</td>
                  <td><button className="danger" onClick={(e) => { e.stopPropagation(); remove(r.code); }} title="移除">✕</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          {!list.loading && rows.length === 0 && <div className="empty">追蹤池是空的，先加入一檔股票。</div>}
        </div>
      </section>

      {selected && <Detail code={selected} name={rows.find((r) => r.code === selected)?.name} />}
    </>
  );
}

/* ------------------------------------------------------------------ detail */
function Detail({ code, name }: { code: string; name?: string }) {
  const [tab, setTab] = useState<Tab>("chart");
  const ind = useAsync(() => engine(`/stocks/${code}/indicators?limit=250`), [code]);
  const inst = useAsync<any[]>(() => engine(`/stocks/${code}/institutional?limit=40`), [code]);
  const margin = useAsync<any[]>(() => engine(`/stocks/${code}/margin?limit=40`), [code]);
  const l = ind.data?.latest ?? {};
  const lotsCell = (v: number | null) => (v == null ? "–" : <span className={cls(v)}>{signed(Math.round(v / 1000))}</span>);
  const diff = (a: number | null, b: number | null) => (a == null || b == null ? "–" : <span className={cls(a - b)}>{signed(a - b)}</span>);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{code} {name ?? ""}</h2>
        <div className="tabs">
          {([["chart", "走勢"], ["ind", "指標"], ["inst", "法人"], ["margin", "融資券"], ["alerts", "警示"]] as [Tab, string][]).map(([k, label]) => (
            <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{label}</button>
          ))}
        </div>
      </div>

      {tab === "chart" && <CandleChart series={ind.data?.series && ind.data.rows ? ind.data.series : null} />}

      {tab === "ind" && (
        <table className="kv">
          <tbody>
            {[
              ["日期", l.date], ["收盤", num(l.close)], ["成交量(張)", int(l.volume ? l.volume / 1000 : null)],
              ["MA5 / MA10", `${num(l.ma5)} / ${num(l.ma10)}`], ["MA20 / MA60 / MA120", `${num(l.ma20)} / ${num(l.ma60)} / ${num(l.ma120)}`],
              ["RSI(14)", num(l.rsi14, 1)], ["K / D (9,3,3)", `${num(l.k, 1)} / ${num(l.d, 1)}`],
              ["MACD DIF / DEA / 柱", `${num(l.macd_dif)} / ${num(l.macd_dea)} / ${num(l.macd_hist)}`],
              ["布林 上 / 中 / 下", `${num(l.bb_upper)} / ${num(l.bb_mid)} / ${num(l.bb_lower)}`],
              ["20 日均量(張)", int(l.vol_ma20 ? l.vol_ma20 / 1000 : null)],
            ].map(([k, v]) => (
              <tr key={String(k)}><td>{k}</td><td>{v ?? "–"}</td></tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "inst" && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>日期</th><th className="num">外資</th><th className="num">投信</th><th className="num">自營商</th><th className="num">合計</th></tr></thead>
            <tbody>
              {(inst.data ?? []).map((r) => (
                <tr key={r.date}><td>{r.date}</td><td className="num">{lotsCell(r.foreign_net)}</td><td className="num">{lotsCell(r.trust_net)}</td><td className="num">{lotsCell(r.dealer_net)}</td><td className="num">{lotsCell(r.total_net)}</td></tr>
              ))}
              {inst.data?.length === 0 && <tr><td colSpan={5} className="muted">尚無資料（新加入的股票會在背景補 20 個交易日）</td></tr>}
            </tbody>
          </table>
          <p className="hint">單位：張（千股）。</p>
        </div>
      )}

      {tab === "margin" && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>日期</th><th className="num">融資餘額</th><th className="num">資增減</th><th className="num">融券餘額</th><th className="num">券增減</th><th className="num">資券互抵</th></tr></thead>
            <tbody>
              {(margin.data ?? []).map((r) => (
                <tr key={r.date}><td>{r.date}</td><td className="num">{int(r.margin_balance)}</td><td className="num">{diff(r.margin_balance, r.margin_prev)}</td><td className="num">{int(r.short_balance)}</td><td className="num">{diff(r.short_balance, r.short_prev)}</td><td className="num">{int(r.offset)}</td></tr>
              ))}
              {margin.data?.length === 0 && <tr><td colSpan={6} className="muted">尚無資料</td></tr>}
            </tbody>
          </table>
          <p className="hint">單位：張。</p>
        </div>
      )}

      {tab === "alerts" && <CodeAlerts code={code} />}
    </section>
  );
}

/* ------------------------------------------------------------------ alert rules for one code */
export function CodeAlerts({ code }: { code: string }) {
  const act = useAction();
  const types = useAsync<any[]>(() => engine("/alerts/rule-types"), []);
  const rules = useAsync<any[]>(() => engine(`/alerts?code=${code}`), [code]);
  const [type, setType] = useState("");
  const [params, setParams] = useState<Record<string, string>>({});
  const [cooldown, setCooldown] = useState("");
  const [oneShot, setOneShot] = useState(false);
  const [note, setNote] = useState("");
  const spec = types.data?.find((t) => t.type === (type || types.data?.[0]?.type));

  useEffect(() => {
    if (!spec) return;
    setType(spec.type);
    setParams(Object.fromEntries(spec.params.map((p: any) => [p.name, p.default ?? ""])));
    setCooldown(String(spec.default_cooldown));
  }, [spec?.type]); // eslint-disable-line react-hooks/exhaustive-deps

  async function create(e: FormEvent) {
    e.preventDefault();
    await act(async () => {
      await engine("/alerts", { method: "POST", body: { code, rule_type: type, params, one_shot: oneShot, cooldown_minutes: Number(cooldown), note: note || null } });
      setNote("");
      rules.reload();
    }, "警示已新增");
  }
  const label = (t: string) => types.data?.find((x) => x.type === t)?.label ?? t;

  return (
    <>
      <form className="alert-form" onSubmit={create}>
        <div className="row">
          <label>規則{" "}
            <select value={type} onChange={(e) => setType(e.target.value)}>
              {(types.data ?? []).map((t) => <option key={t.type} value={t.type}>{t.label}（{t.scope === "intraday" ? "盤中" : "日線"}）</option>)}
            </select>
          </label>
          <div className="params">
            {(spec?.params ?? []).map((p: any) => (
              <label key={p.name}>{p.label}{" "}
                {p.type === "select" ? (
                  <select value={params[p.name] ?? p.default} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })}>
                    {p.options.map((o: string) => <option key={o}>{o}</option>)}
                  </select>
                ) : (
                  <input type="number" step="any" required={p.default === undefined} value={params[p.name] ?? ""} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })} />
                )}
              </label>
            ))}
          </div>
        </div>
        <div className="row">
          <label>冷卻(分) <input type="number" min={0} style={{ width: "6em" }} value={cooldown} onChange={(e) => setCooldown(e.target.value)} /></label>
          <label className="chk"><input type="checkbox" checked={oneShot} onChange={(e) => setOneShot(e.target.checked)} /> 觸發一次後停用</label>
          <input placeholder="備註" value={note} onChange={(e) => setNote(e.target.value)} />
          <button type="submit">新增警示</button>
        </div>
      </form>
      <div className="table-wrap">
        <table>
          <thead><tr><th>規則</th><th>參數</th><th>狀態</th><th>上次觸發</th><th></th></tr></thead>
          <tbody>
            {(rules.data ?? []).map((r) => (
              <tr key={r.id}>
                <td>{label(r.rule_type)}{r.note ? <span className="muted"> {r.note}</span> : null}</td>
                <td className="muted">{Object.entries(r.params).map(([k, v]) => `${k}=${v}`).join(", ")}</td>
                <td>{r.enabled ? <span className="badge live">啟用</span> : <span className="badge">停用</span>}{r.one_shot ? <span className="badge"> 單次</span> : null} <span className="muted">{r.cooldown_minutes}m</span></td>
                <td className="muted">{time(r.last_triggered_at)}</td>
                <td>
                  <button className="ghost" onClick={() => act(async () => { await engine(`/alerts/${r.id}`, { method: "PATCH", body: { enabled: !r.enabled } }); rules.reload(); })}>{r.enabled ? "停用" : "啟用"}</button>{" "}
                  <button className="danger" onClick={() => act(async () => { await engine(`/alerts/${r.id}`, { method: "DELETE" }); rules.reload(); })}>✕</button>
                </td>
              </tr>
            ))}
            {rules.data?.length === 0 && <tr><td colSpan={5} className="muted">尚無警示規則</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
