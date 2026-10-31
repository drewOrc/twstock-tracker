import { useEffect, useMemo, useState, type FormEvent } from "react";
import { engine, useAsync } from "../api/client";
import { CandleChart } from "../components/Chart";
import { useAction, useToast } from "../components/Toast";
import { cls, int, num, pctS, signed, time } from "../lib/format";

import { StockSummary } from "../components/StockSummary";

type Tab = "summary" | "chart" | "ind" | "inst" | "margin" | "alerts";
export interface WatchlistDef { id: number; name: string; color: string | null; sort_order: number; system_key: string | null; count: number }

const ALL = 0; // pseudo id for "全部"

export default function Watchlist() {
  const toast = useToast();
  const act = useAction();
  const lists = useAsync<WatchlistDef[]>(() => engine("/watchlists"), [], 60000);
  const [listId, setListId] = useState<number>(() => Number(localStorage.getItem("tw.watchlist") ?? ALL));
  const current = lists.data?.find((l) => l.id === listId) ?? null;
  const userLists = useMemo(() => (lists.data ?? []).filter((l) => !l.system_key), [lists.data]);
  const rowsQ = useAsync<any[]>(() => engine(listId === ALL ? "/watchlist" : `/watchlist?list=${listId}`), [listId], 15000);
  const [selected, setSelected] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [note, setNote] = useState("");
  const [targets, setTargets] = useState<number[]>([]);
  const [options, setOptions] = useState<any[]>([]);
  const rows = rowsQ.data ?? [];
  const byId = useMemo(() => Object.fromEntries((lists.data ?? []).map((l) => [l.id, l])), [lists.data]);

  useEffect(() => { try { localStorage.setItem("tw.watchlist", String(listId)); } catch { /* ignore */ } }, [listId]);
  useEffect(() => {
    if (lists.data && listId !== ALL && !lists.data.some((l) => l.id === listId)) setListId(ALL);
  }, [lists.data, listId]);
  useEffect(() => {
    // default target for "加入": the current user list, else the default (first) user list
    if (!userLists.length) return;
    setTargets(current && !current.system_key ? [current.id] : [userLists[0].id]);
  }, [listId, userLists.length]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (rows.length && (!selected || !rows.some((r) => r.code === selected))) setSelected(rows[0].code);
    if (!rows.length) setSelected(null);
  }, [rows, selected]);
  useEffect(() => {
    const q = code.trim();
    if (q.length < 1) return;
    const t = setTimeout(() => engine(`/stocks/search?q=${encodeURIComponent(q)}&limit=15`).then(setOptions).catch(() => {}), 250);
    return () => clearTimeout(t);
  }, [code]);

  const refreshAll = () => Promise.all([lists.reload(), rowsQ.reload()]);

  async function add(e: FormEvent) {
    e.preventDefault();
    const c = (code.trim().split(/\s+/)[0] || "").toUpperCase();
    if (!c) return;
    if (!targets.length) return toast("請至少選一個清單", true);
    await act(async () => {
      const r = await engine("/watchlist", { method: "POST", body: { code: c, note: note || null, lists: targets } });
      const names = targets.map((id) => byId[id]?.name).filter(Boolean).join("、");
      toast(r.is_new ? `已加入 ${r.code} ${r.name} 到 ${names}，正在背景補歷史資料…` : `已將 ${r.code} ${r.name} 加入 ${names}`);
      setCode(""); setNote("");
      await refreshAll();
      setSelected(r.code);
      if (r.backfill) { setTimeout(rowsQ.reload, 15000); setTimeout(rowsQ.reload, 45000); }
    });
  }

  async function remove(c: string) {
    const scope = current && !current.system_key ? `從「${current.name}」移除 ${c}？` : `從所有自訂清單移除 ${c}？`;
    if (!confirm(scope + " 若它不再屬於任何清單，相關警示規則也會刪除。")) return;
    await act(async () => {
      const r = await engine(`/watchlist/${c}${current && !current.system_key ? `?list=${current.id}` : ""}`, { method: "DELETE" });
      toast(r.unsubscribed ? `已移除 ${c}，並停止追蹤` : `已從清單移除 ${c}`);
      await refreshAll();
    });
  }

  async function createList() {
    const name = prompt("新清單名稱（例如 AI 供應鏈、短線觀察）");
    if (!name?.trim()) return;
    await act(async () => { const r = await engine("/watchlists", { method: "POST", body: { name: name.trim() } }); await lists.reload(); setListId(r.id); }, "清單已建立");
  }
  async function renameList() {
    if (!current || current.system_key) return;
    const name = prompt("清單名稱", current.name);
    if (!name?.trim() || name.trim() === current.name) return;
    await act(() => engine(`/watchlists/${current.id}`, { method: "PATCH", body: { name: name.trim() } }).then(lists.reload), "已改名");
  }
  async function deleteList() {
    if (!current || current.system_key) return;
    if (!confirm(`刪除清單「${current.name}」？裡面 ${current.count} 檔股票若不在其他清單，會停止追蹤並刪除警示規則。`)) return;
    await act(async () => { await engine(`/watchlists/${current.id}`, { method: "DELETE" }); setListId(ALL); await lists.reload(); }, "清單已刪除");
  }
  const syncLists = () => act(async () => { await engine("/watchlists/sync", { method: "POST" }); toast("系統清單同步中（CRM、掃描候選、今日警示），約 10 秒"); setTimeout(refreshAll, 10000); });
  const refreshQuotes = () => act(async () => {
    const r = await engine("/quotes/refresh", { method: "POST" });
    toast(`已更新 ${r.quotes.length} 檔報價${r.alerts.length ? `，觸發 ${r.alerts.length} 個警示` : ""}`);
    rowsQ.reload();
  });
  const toggleMembership = (r: any, lid: number) =>
    act(async () => {
      const next = r.lists.includes(lid) ? r.lists.filter((x: number) => x !== lid) : [...r.lists, lid];
      const userOnly = next.filter((x: number) => byId[x] && !byId[x].system_key);
      await engine(`/watchlist/${r.code}`, { method: "PATCH", body: { lists: userOnly } });
      await refreshAll();
    });

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h2>追蹤池</h2>
          <button className="ghost tiny" onClick={createList}>＋ 新清單</button>
          {current && !current.system_key && (<><button className="ghost tiny" onClick={renameList}>改名</button><button className="ghost tiny" onClick={deleteList}>刪除清單</button></>)}
          <button className="ghost tiny" onClick={syncLists} title="重建 CRM 持有 / 觀察、掃描候選、今日警示">同步系統清單</button>
          <button className="ghost" onClick={refreshQuotes} title="立即向證交所抓一次即時報價">更新報價</button>
        </div>

        <div className="list-tabs">
          <button className={listId === ALL ? "active" : ""} onClick={() => setListId(ALL)}>全部{listId === ALL && rows.length ? <span className="cnt">{rows.length}</span> : null}</button>
          {(lists.data ?? []).map((l) => (
            <button key={l.id} className={listId === l.id ? "active" : ""} onClick={() => setListId(l.id)} title={l.system_key ? "系統清單：自動維護" : ""}>
              <i className="sw" style={{ background: l.color ?? "var(--none)" }} />{l.name} <span className="cnt">{l.count}</span>{l.system_key && <span className="sys">自動</span>}
            </button>
          ))}
        </div>
        {current?.system_key && (
          <p className="hint">
            {{ crm_hold: "Stock CRM 中 stage=持有 的台股卡片，每 15 分鐘同步。", crm_watch: "Stock CRM 中 stage=觀察 的台股卡片，每 15 分鐘同步。", screener: `最新一次均衡預設掃描的前 20 名，每次掃描後覆蓋。`, alerts_today: "過去 24 小時觸發過警示的股票。" }[current.system_key]}
            系統清單不能手動增減，但可以把股票複製到自訂清單。
          </p>
        )}

        <form className="add-form" onSubmit={add} autoComplete="off">
          <input list="stock-options" placeholder="代號或名稱，例如 2330" value={code} onChange={(e) => setCode(e.target.value)} required />
          <datalist id="stock-options">{options.map((s) => <option key={s.code} value={`${s.code} ${s.name}`} />)}</datalist>
          <input placeholder="備註（選填）" value={note} onChange={(e) => setNote(e.target.value)} />
          <span className="muted small">加入到</span>
          <div className="list-picker">
            {userLists.map((l) => (
              <label key={l.id} className={`chip pick ${targets.includes(l.id) ? "on" : ""}`}>
                <input type="checkbox" checked={targets.includes(l.id)} onChange={(e) => setTargets(e.target.checked ? [...targets, l.id] : targets.filter((x) => x !== l.id))} />
                {l.name}
              </label>
            ))}
          </div>
          <button type="submit">加入</button>
        </form>

        {rowsQ.error && <div className="empty up">{rowsQ.error}</div>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>代號</th><th>名稱</th><th>市場</th>
                <th className="num">現價</th><th className="num">漲跌</th><th className="num">漲跌%</th><th className="num">量(張)</th>
                <th className="num" title="外資買賣超(張)">外資</th><th className="num" title="投信買賣超(張)">投信</th><th className="num" title="自營商買賣超(張)">自營</th>
                <th className="num" title="融資餘額(張) / 增減">融資</th><th className="num" title="融券餘額(張) / 增減">融券</th>
                <th>清單</th><th>更新</th><th></th>
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
                  <td onClick={(e) => e.stopPropagation()}>
                    <ListDots lists={lists.data ?? []} member={r.lists} onToggle={(lid) => toggleMembership(r, lid)} />
                  </td>
                  <td>{r.realtime ? <span className="badge live" title="即時">{r.quote_time}</span> : <span className="badge" title="日線收盤">{r.daily_date ?? "–"}</span>}</td>
                  <td>{current?.system_key ? null : <button className="danger" onClick={(e) => { e.stopPropagation(); remove(r.code); }} title="移除">✕</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!rowsQ.loading && rows.length === 0 && <div className="empty">{current?.system_key ? "這個系統清單目前是空的。" : "這個清單是空的，先加入一檔股票。"}</div>}
        </div>
      </section>

      {selected && <Detail code={selected} name={rows.find((r) => r.code === selected)?.name} />}
    </>
  );
}

/** Coloured dots: one per list the stock is in; click a user list's dot to toggle membership. */
function ListDots({ lists, member, onToggle }: { lists: WatchlistDef[]; member: number[]; onToggle: (lid: number) => void }) {
  return (
    <span className="list-dots">
      {lists.map((l) => {
        const on = member.includes(l.id);
        if (!on && l.system_key) return null;
        return (
          <i key={l.id} className={`ldot ${on ? "on" : ""} ${l.system_key ? "sys" : ""}`} style={{ background: on ? l.color ?? "var(--accent)" : "transparent", borderColor: l.color ?? "var(--border)" }}
            title={`${l.name}${l.system_key ? "（系統）" : on ? "：點擊移出" : "：點擊加入"}`} onClick={() => !l.system_key && onToggle(l.id)} />
        );
      })}
    </span>
  );
}

/* ------------------------------------------------------------------ detail */
function Detail({ code, name }: { code: string; name?: string }) {
  const [tab, setTab] = useState<Tab>("summary");
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
          {([["summary", "概況"], ["chart", "走勢"], ["ind", "指標"], ["inst", "法人"], ["margin", "融資券"], ["alerts", "警示"]] as [Tab, string][]).map(([k, label]) => (
            <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{label}</button>
          ))}
        </div>
      </div>

      {tab === "summary" && <div className="summary-wrap"><StockSummary code={code} /></div>}
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
            {rules.data?.length === 0 && <tr><td colSpan={5} className="muted">尚無警示規則</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
