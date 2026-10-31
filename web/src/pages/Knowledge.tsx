/* 知識層：提案審核（agent / 成員提出，管理員核准）、ETF 成分股、產業鏈、待補清單。 */
import { useMemo, useState } from "react";
import { engine, useAsync } from "../api/client";
import { useMe } from "../components/Auth";
import { useAction } from "../components/Toast";
import { time } from "../lib/format";

type Tab = "proposals" | "funds" | "chains" | "todo";
const KIND: Record<string, string> = { company: "公司", edge: "供應鏈關係", edge_weight: "權重", brief: "簡介 / 重點", metric: "實際值", financial: "季報" };
const CONF: Record<string, string> = { high: "高", medium: "中", low: "低" };

export default function Knowledge() {
  const [tab, setTab] = useState<Tab>("proposals");
  const counts = useAsync<Record<string, number>>(() => engine("/knowledge/proposals/counts"), [tab], 60000);
  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h2>知識層 <span className="muted small">共用給所有人的公司、供應鏈、簡介與官方數字</span></h2>
          <div className="tabs">
            {([["proposals", `提案審核${counts.data?.pending ? `（${counts.data.pending}）` : ""}`], ["funds", "ETF 成分股"], ["chains", "產業鏈"], ["todo", "待補"]] as [Tab, string][]).map(([k, label]) => (
              <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{label}</button>
            ))}
          </div>
        </div>
        {tab === "proposals" && <Proposals onChanged={counts.reload} />}
        {tab === "funds" && <Funds />}
        {tab === "chains" && <Chains />}
        {tab === "todo" && <Todo />}
      </section>
    </>
  );
}

function Proposals({ onChanged }: { onChanged: () => void }) {
  const { me } = useMe();
  const act = useAction();
  const [status, setStatus] = useState("pending");
  const [kind, setKind] = useState("");
  const [company, setCompany] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const q = `/knowledge/proposals?status=${status}${kind ? `&kind=${kind}` : ""}${company ? `&company=${encodeURIComponent(company)}` : ""}&limit=500`;
  const list = useAsync<any[]>(() => engine(q), [q], 60000);
  const isAdmin = me?.role === "admin";
  const decide = (ids: number[], approve: boolean) =>
    act(async () => {
      const r = await engine("/knowledge/proposals/decide", { method: "POST", body: { ids, approve } });
      list.reload(); onChanged();
      if (r.failed || r.skipped) throw new Error(`完成：核准 ${r.approved}、拒絕 ${r.rejected}、失敗 ${r.failed}、略過 ${r.skipped}`);
    }, approve ? `已套用 ${ids.length} 筆` : `已拒絕 ${ids.length} 筆`);
  const rows = list.data ?? [];
  const groups = useMemo(() => {
    const g: Record<string, any[]> = {};
    for (const r of rows) (g[r.kind] ??= []).push(r);
    return g;
  }, [rows]);

  return (
    <>
      <div className="row toolbar">
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="pending">待審</option><option value="approved">已核准</option><option value="rejected">已拒絕</option><option value="failed">套用失敗</option><option value="all">全部</option>
        </select>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">所有類型</option>{Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <input placeholder="公司 id，例如 TW:2330" value={company} onChange={(e) => setCompany(e.target.value)} style={{ width: "12em" }} />
        <span className="muted small">{rows.length} 筆</span>
        {isAdmin && status === "pending" && rows.length > 0 && (
          <>
            <button className="primary tiny" onClick={() => { if (confirm(`核准並套用目前列出的 ${rows.length} 筆？`)) decide(rows.map((r) => r.id), true); }}>全部核准</button>
            {Object.entries(groups).length > 1 && Object.entries(groups).map(([k, rs]) => (
              <button key={k} className="ghost tiny" onClick={() => decide(rs.map((r) => r.id), true)}>核准 {KIND[k] ?? k}（{rs.length}）</button>
            ))}
          </>
        )}
      </div>
      {list.error && <div className="empty up">{list.error}</div>}
      {rows.length === 0 && !list.error && <div className="empty">沒有{status === "pending" ? "待審" : ""}提案。agent 從新聞、法說、年報整理出的供應鏈關係與公司簡介會出現在這裡，核准後才寫進共用知識層。</div>}
      <div className="table-wrap">
        <table>
          <thead><tr><th>類型</th><th>內容</th><th>信心</th><th>來源 / 理由</th><th>提出者</th><th>時間</th><th></th></tr></thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id} className={p.status !== "pending" ? "muted" : ""}>
                <td><span className="badge">{KIND[p.kind] ?? p.kind}</span></td>
                <td>
                  <a className="link" onClick={() => setOpen(open === p.id ? null : p.id)}>{p.summary}</a>
                  {open === p.id && (
                    <div className="brief" style={{ marginTop: 6 }}>
                      <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{JSON.stringify(p.payload, null, 1)}</pre>
                      {p.evidence?.length > 0 && <ul className="news">{p.evidence.map((e: any, i: number) => <li key={i}>{e.url ? <a href={e.url} target="_blank" rel="noopener noreferrer">{e.title ?? e.url}</a> : e.title}{e.quote ? <span className="kv">「{e.quote}」</span> : null}</li>)}</ul>}
                      {p.note && <div className="kv">備註：{p.note}</div>}
                      {p.applied_ref && <div className="kv">已寫入 {p.applied_ref}</div>}
                    </div>
                  )}
                </td>
                <td><span className={`badge ${p.confidence === "high" ? "live" : ""}`}>{CONF[p.confidence] ?? p.confidence}</span></td>
                <td className="small" style={{ maxWidth: "28em" }}>{p.rationale || p.source}</td>
                <td className="small">{p.created_by}</td>
                <td className="muted small">{time(p.created_at)}</td>
                <td>
                  {isAdmin && p.status === "pending" && (
                    <>
                      <button className="primary tiny" onClick={() => decide([p.id], true)}>核准</button>{" "}
                      <button className="ghost tiny" onClick={() => decide([p.id], false)}>拒絕</button>
                    </>
                  )}
                  {p.status !== "pending" && <span className="kv">{{ approved: "已核准", rejected: "已拒絕", failed: "失敗" }[p.status as string] ?? p.status}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Funds() {
  const { me } = useMe();
  const act = useAction();
  const funds = useAsync<any[]>(() => engine("/knowledge/funds"), [], 300000);
  const [fund, setFund] = useState<string | null>(null);
  const current = fund ?? funds.data?.[0]?.id ?? null;
  const holdings = useAsync<any[]>(() => (current ? engine(`/knowledge/funds/${encodeURIComponent(current)}/holdings`) : Promise.resolve([])), [current], 300000);
  const [compare, setCompare] = useState(false);
  const all = useAsync<Record<string, any[]>>(async () => {
    if (!compare || !funds.data) return {};
    const out: Record<string, any[]> = {};
    for (const f of funds.data) out[f.id] = await engine(`/knowledge/funds/${encodeURIComponent(f.id)}/holdings`);
    return out;
  }, [compare, funds.data]);
  const refresh = (id: string) => act(async () => { await engine(`/knowledge/funds/${encodeURIComponent(id)}/refresh`, { method: "POST" }); holdings.reload(); funds.reload(); }, "已重新讀取成分股");

  const overlap = useMemo(() => {
    if (!all.data || !funds.data) return [];
    const ids = funds.data.map((f) => f.id);
    const map: Record<string, any> = {};
    for (const fid of ids) for (const h of all.data[fid] ?? []) {
      map[h.company_id] ??= { company_id: h.company_id, name: h.name, sector: h.sector, w: {} };
      map[h.company_id].w[fid] = h.weight_pct;
    }
    return Object.values(map).filter((r: any) => Object.keys(r.w).length > 1).sort((a: any, b: any) => Object.keys(b.w).length - Object.keys(a.w).length || (b.w[ids[0]] ?? 0) - (a.w[ids[0]] ?? 0));
  }, [all.data, funds.data]);

  return (
    <>
      <div className="row toolbar">
        {(funds.data ?? []).map((f) => (
          <button key={f.id} className={`ghost tiny ${current === f.id ? "active" : ""}`} onClick={() => { setFund(f.id); setCompare(false); }}>{f.name} <span className="kv">{f.constituents} 檔</span></button>
        ))}
        {(funds.data?.length ?? 0) > 1 && <button className={`ghost tiny ${compare ? "active" : ""}`} onClick={() => setCompare(!compare)}>重疊比較</button>}
        {me?.role === "admin" && current?.startsWith("TW:") && !compare && <button className="ghost tiny" onClick={() => refresh(current)}>重新讀取（MoneyDJ）</button>}
      </div>
      {funds.data?.length === 0 && <div className="empty">還沒有 ETF。用 <code>python cli.py knowledge holdings 0050</code> 載入成分股。</div>}
      {!compare && current && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>#</th><th>代號</th><th>名稱</th><th>產業</th><th className="num">權重 %</th><th>更新</th></tr></thead>
            <tbody>
              {(holdings.data ?? []).map((h, i) => (
                <tr key={h.company_id}><td className="muted">{i + 1}</td><td>{h.company_id}</td><td>{h.name}</td><td className="small">{h.sector}</td><td className="num"><b>{h.weight_pct.toFixed(2)}</b></td><td className="muted small">{time(h.updated_at)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {compare && (
        <div className="table-wrap">
          <p className="hint">同時出現在兩檔以上 ETF 的公司。權重為各 ETF 最近一次成分股資料。</p>
          <table>
            <thead><tr><th>代號</th><th>名稱</th><th>產業</th>{(funds.data ?? []).map((f) => <th key={f.id} className="num">{f.name}</th>)}</tr></thead>
            <tbody>
              {overlap.map((r: any) => (
                <tr key={r.company_id}><td>{r.company_id}</td><td>{r.name}</td><td className="small">{r.sector}</td>{(funds.data ?? []).map((f) => <td key={f.id} className="num">{r.w[f.id] != null ? r.w[f.id].toFixed(2) : <span className="kv">–</span>}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

const STAGE_ORDER = ["上游", "中游", "下游"];

function Chains() {
  const { me } = useMe();
  const act = useAction();
  const list = useAsync<any>(() => engine("/knowledge/chains"), [], 600000);
  const [pick, setPick] = useState<string>(() => { try { return localStorage.getItem("kn.chain") || "D000"; } catch { return "D000"; } });
  const [q, setQ] = useState("");
  const detail = useAsync<any>(() => engine(`/knowledge/chains/${encodeURIComponent(pick)}`).catch(() => null), [pick], 600000);
  const choose = (id: string) => { setPick(id); try { localStorage.setItem("kn.chain", id); } catch { /* private mode */ } };
  const refresh = () => act(async () => { await engine(`/knowledge/chains/refresh?ic=${encodeURIComponent(pick)}`, { method: "POST" }); detail.reload(); list.reload(); }, "已重新讀取這條產業鏈");
  const st = list.data?.stats;
  const d = detail.data;
  const hit = (m: any) => !q || m.name.includes(q) || (m.code ?? "").startsWith(q);
  const groups = useMemo(() => {
    const out: Record<string, any[]> = {};
    for (const s of d?.segments ?? []) (out[s.stage ?? "分類"] ??= []).push(s);
    return Object.entries(out).sort(([a], [b]) => (STAGE_ORDER.indexOf(a) + 1 || 9) - (STAGE_ORDER.indexOf(b) + 1 || 9));
  }, [d]);
  const members = (ms: any[]) => (
    <div className="ctx-line">
      {ms.filter(hit).map((m, i) => (
        <span key={i} className={`chip${m.code ? "" : " muted"}${q && hit(m) ? " pick on" : ""}`} title={`${m.listing ?? ""}${m.in_graph ? " · 已在關係圖" : ""}`}>
          {m.in_graph ? "● " : ""}{m.name}{m.code ? ` ${m.code}` : ""}
        </span>
      ))}
      {!ms.filter(hit).length && <span className="kv">{ms.length ? "沒有符合的公司" : "平台未列公司"}</span>}
    </div>
  );
  if (list.data && !list.data.chains.length) return <div className="empty">還沒有產業鏈資料。管理員可用 <code>python cli.py knowledge chains</code> 抓取，之後每週日 06:30 自動更新。</div>;
  return (
    <>
      <p className="hint">來源：櫃買中心產業價值鏈資訊平台，系統每週日自動更新{st?.fetched_at ? `（上次 ${time(st.fetched_at)}）` : ""}。共 {st?.chains ?? "…"} 個產業、{st?.tw_companies ?? "…"} 家台灣公司；● 表示這家公司已在供應鏈關係圖裡。這是「同一段有誰」的分類，不是客戶與供應商關係。</p>
      <div className="row toolbar">
        <select value={pick} onChange={(e) => choose(e.target.value)}>
          {(list.data?.chains ?? []).map((c: any) => <option key={c.id} value={c.id}>{c.name}（{c.companies}）</option>)}
        </select>
        <input placeholder="找公司名稱或代號" value={q} onChange={(e) => setQ(e.target.value.trim())} style={{ maxWidth: "14em" }} />
        {me?.role === "admin" && <button className="ghost tiny" onClick={refresh}>重新讀取</button>}
        {d?.source_url && <a className="kv" href={d.source_url} target="_blank" rel="noopener noreferrer">原始頁面</a>}
      </div>
      {d?.intro && <p className="brief small">{d.intro.length > 400 ? `${d.intro.slice(0, 400)}…` : d.intro}</p>}
      {groups.map(([stage, segs]) => (
        <section key={stage} className="panel">
          <h4>{stage}</h4>
          {segs.map((s: any) => (
            <div key={s.code} className="brief">
              <b>{s.name}</b> <span className="kv">{s.members.length + s.children.reduce((n: number, c: any) => n + c.members.length, 0)} 家</span>
              {s.members.length > 0 && members(s.members)}
              {s.children.map((c: any) => (
                <div key={c.code} style={{ marginTop: 6 }}><span className="kv">{c.name}</span>{members(c.members)}</div>
              ))}
            </div>
          ))}
        </section>
      ))}
    </>
  );
}

function Todo() {
  const q = useAsync<any>(() => engine("/knowledge/todo"), [], 120000);
  const d = q.data;
  if (!d) return <div className="kv">載入中…</div>;
  const block = (title: string, rows: any[], render: (r: any) => string) => (
    <div className="brief">
      <b>{title}</b> <span className="kv">{rows.length}</span>
      <div className="ctx-line">{rows.slice(0, 60).map((r, i) => <span key={i} className="chip">{render(r)}</span>)}{rows.length > 60 && <span className="kv">…</span>}</div>
    </div>
  );
  return (
    <>
      <p className="hint">知識層目前 {d.companies} 家公司，還缺 {d.total} 項。這份清單也提供給 agent（<code>GET /api/market/knowledge/todo</code>），由它讀新聞與法說後提案補上。</p>
      {block("沒有公司簡介", d.missing_profile, (r) => `${r.name ?? r.id}`)}
      {block("近期重點過期或缺少", d.stale_highlights, (r) => `${r.name ?? r.id}${r.latest ? `（${r.latest}）` : ""}`)}
      {block("沒有任何供應鏈關係", d.isolated_companies, (r) => `${r.name ?? r.id}`)}
      {block("關係沒有來源", d.edges_without_source, (r) => `${r.customer_id} → ${r.supplier_id}`)}
    </>
  );
}
