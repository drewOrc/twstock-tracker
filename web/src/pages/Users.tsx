/* Admin: accounts; everyone: change own password / LINE id via the admin API (admin) or password API. */
import { useState, type FormEvent } from "react";
import { admin, auth, useAsync } from "../api/client";
import { useMe } from "../components/Auth";
import { useAction } from "../components/Toast";
import { time } from "../lib/format";

export default function Users() {
  const { me } = useMe();
  return (
    <>
      <PasswordPanel />
      {me?.role === "admin" && <AccountsPanel myId={me.id} />}
      {me?.role === "admin" && <AgentKeysPanel />}
    </>
  );
}

const SCOPE_LABEL: Record<string, string> = { "market:read": "讀通用層", "knowledge:propose": "對知識層提案", "personal:read": "讀代表者的個人資料" };

function AgentKeysPanel() {
  const act = useAction();
  const keys = useAsync<any[]>(() => admin("/agents"), []);
  const users = useAsync<any[]>(() => admin("/users"), []);
  const [form, setForm] = useState({ name: "", scopes: ["market:read", "knowledge:propose"] as string[], acting_user_id: "", rate_per_minute: 60, note: "" });
  const [issued, setIssued] = useState<{ name: string; key: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const toggle = (s: string) => setForm({ ...form, scopes: form.scopes.includes(s) ? form.scopes.filter((x) => x !== s) : [...form.scopes, s] });

  const create = (e: FormEvent) => {
    e.preventDefault();
    act(async () => {
      const r = await admin("/agents", { method: "POST", body: { ...form, acting_user_id: form.acting_user_id ? Number(form.acting_user_id) : null, note: form.note || null } });
      setIssued({ name: r.agent.name, key: r.key });
      setCopied(false);
      setForm({ ...form, name: "", note: "" });
      keys.reload();
    }, "金鑰已發放，只會顯示這一次");
  };
  const patch = (id: number, body: any, ok?: string) => act(async () => { await admin(`/agents/${id}`, { method: "PATCH", body }); keys.reload(); }, ok);
  const rotate = (k: any) => act(async () => { const r = await admin(`/agents/${k.id}/rotate`, { method: "POST" }); setIssued({ name: k.name, key: r.key }); setCopied(false); keys.reload(); }, "已換新金鑰，舊的立即失效");
  const copy = async () => {
    if (!issued) return;
    try { await navigator.clipboard.writeText(issued.key); setCopied(true); } catch { setCopied(false); }
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Agent 金鑰 <span className="muted small">（管理員）</span></h2>
        <span className="muted small">給 Grok bot、Claude session 或腳本用。金鑰只存雜湊、只顯示一次；agent 只能讀通用層與提案，永遠進不了管理路徑。帶法：<code>Authorization: Bearer twa_…</code></span>
      </div>
      {issued && (
        <div className="brief">
          <b>{issued.name}</b> 的金鑰（離開這頁就看不到了）：<code style={{ userSelect: "all", wordBreak: "break-all" }}>{issued.key}</code>{" "}
          <button className="ghost tiny" onClick={copy}>{copied ? "已複製" : "複製"}</button>{" "}
          <button className="ghost tiny" onClick={() => setIssued(null)}>我記下了</button>
        </div>
      )}
      <form className="alert-form" onSubmit={create}>
        <div className="row">
          <input placeholder="名稱，例如 grok" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required style={{ width: "10em" }} />
          {Object.entries(SCOPE_LABEL).map(([s, label]) => (
            <label key={s} className="small"><input type="checkbox" checked={form.scopes.includes(s)} onChange={() => toggle(s)} /> {label}</label>
          ))}
          <select value={form.acting_user_id} onChange={(e) => setForm({ ...form, acting_user_id: e.target.value })}>
            <option value="">代表我</option>
            {(users.data ?? []).map((u) => <option key={u.id} value={u.id}>代表 {u.username}</option>)}
          </select>
          <input type="number" min={1} max={6000} value={form.rate_per_minute} onChange={(e) => setForm({ ...form, rate_per_minute: Number(e.target.value) })} style={{ width: "5em" }} title="每分鐘請求上限" />
          <input placeholder="備註（選填）" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} style={{ width: "12em" }} />
          <button type="submit">＋ 發放金鑰</button>
        </div>
      </form>
      <div className="table-wrap">
        <table>
          <thead><tr><th>名稱</th><th>前綴</th><th>範圍</th><th>代表</th><th>每分鐘</th><th>最近使用</th><th>狀態</th><th></th></tr></thead>
          <tbody>
            {(keys.data ?? []).map((k) => (
              <tr key={k.id}>
                <td><b>{k.name}</b>{k.note ? <span className="muted small"> {k.note}</span> : null}</td>
                <td><code>{k.prefix}…</code></td>
                <td className="small">{(k.scopes ?? []).map((s: string) => SCOPE_LABEL[s] ?? s).join("、")}</td>
                <td>{k.acting_username}</td>
                <td>{k.rate_per_minute}</td>
                <td className="muted">{time(k.last_used_at)}</td>
                <td>{k.disabled ? <span className="badge">停用</span> : <span className="badge live">啟用</span>}</td>
                <td>
                  <button className="ghost tiny" onClick={() => rotate(k)}>換金鑰</button>{" "}
                  <button className="ghost tiny" onClick={() => patch(k.id, { disabled: !k.disabled }, k.disabled ? "已啟用" : "已停用")}>{k.disabled ? "啟用" : "停用"}</button>
                </td>
              </tr>
            ))}
            {keys.data?.length === 0 && <tr><td colSpan={8} className="muted">還沒有 agent 金鑰。</td></tr>}
          </tbody>
        </table>
      </div>
      <p className="hint">agent 的工作入口：<code>GET /api/market/knowledge/tasks</code> 給它打包好的材料（公司資料、數字、已知關係、新聞標題），它用 <code>POST /api/market/knowledge/proposals/batch</code> 回答，你在「知識層」頁核准。</p>
    </section>
  );
}

function PasswordPanel() {
  const act = useAction();
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    act(async () => { await auth("/password", { method: "POST", body: { current_password: cur, new_password: next } }); setCur(""); setNext(""); }, "密碼已更新，所有裝置將重新登入");
  };
  return (
    <section className="panel">
      <div className="panel-head"><h2>我的密碼</h2></div>
      <form className="add-form" onSubmit={submit}>
        <input type="password" placeholder="目前密碼" value={cur} onChange={(e) => setCur(e.target.value)} required autoComplete="current-password" />
        <input type="password" placeholder="新密碼（至少 8 字元）" value={next} onChange={(e) => setNext(e.target.value)} required minLength={8} autoComplete="new-password" />
        <button type="submit">更改密碼</button>
      </form>
    </section>
  );
}

function AccountsPanel({ myId }: { myId: number }) {
  const act = useAction();
  const users = useAsync<any[]>(() => admin("/users"), []);
  const [form, setForm] = useState({ username: "", password: "", display_name: "", role: "member", line_user_id: "", email: "" });
  const F = (k: string) => (e: any) => setForm({ ...form, [k]: e.target.value });

  const create = (e: FormEvent) => {
    e.preventDefault();
    act(async () => {
      await admin("/users", { method: "POST", body: { ...form, display_name: form.display_name || null, line_user_id: form.line_user_id || null, email: form.email || null } });
      setForm({ username: "", password: "", display_name: "", role: "member", line_user_id: "", email: "" });
      users.reload();
    }, "帳號已建立");
  };
  const patch = (id: number, body: any, ok?: string) => act(async () => { await admin(`/users/${id}`, { method: "PATCH", body }); users.reload(); }, ok);
  const resetPw = (u: any) => {
    const pw = prompt(`為 ${u.username} 設定新密碼（至少 8 字元）`);
    if (pw) patch(u.id, { password: pw }, "密碼已重設，該帳號所有裝置已登出");
  };
  const editField = (u: any, field: string, label: string) => {
    const v = prompt(`${u.username} 的${label}`, u[field] ?? "");
    if (v !== null) patch(u.id, { [field]: v });
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>帳號管理 <span className="muted small">（管理員）</span></h2>
        <span className="muted small">每個人有自己的清單、警示、卡片與通知；LINE 使用者 ID 填了就會收到自己的警示推播。</span>
      </div>
      <form className="alert-form" onSubmit={create}>
        <div className="row">
          <input placeholder="帳號（英數）" value={form.username} onChange={F("username")} required style={{ width: "10em" }} />
          <input type="password" placeholder="密碼（≥ 8）" value={form.password} onChange={F("password")} required minLength={8} style={{ width: "10em" }} autoComplete="new-password" />
          <input placeholder="顯示名稱" value={form.display_name} onChange={F("display_name")} style={{ width: "8em" }} />
          <select value={form.role} onChange={F("role")}><option value="member">成員</option><option value="admin">管理員</option></select>
          <input placeholder="LINE 使用者 ID（選填）" value={form.line_user_id} onChange={F("line_user_id")} style={{ width: "16em" }} />
          <input placeholder="Email（選填）" value={form.email} onChange={F("email")} style={{ width: "14em" }} />
          <button type="submit">＋ 建立帳號</button>
        </div>
      </form>
      <div className="table-wrap">
        <table>
          <thead><tr><th>帳號</th><th>名稱</th><th>角色</th><th>LINE</th><th>Email</th><th>上次登入</th><th>狀態</th><th></th></tr></thead>
          <tbody>
            {(users.data ?? []).map((u) => (
              <tr key={u.id}>
                <td><b>{u.username}</b>{u.id === myId ? <span className="muted"> （我）</span> : null}</td>
                <td><a className="link" onClick={() => editField(u, "display_name", "顯示名稱")}>{u.display_name || "–"}</a></td>
                <td>
                  <select value={u.role} disabled={u.id === myId} onChange={(e) => patch(u.id, { role: e.target.value })}>
                    <option value="member">成員</option><option value="admin">管理員</option>
                  </select>
                </td>
                <td><a className="link" onClick={() => editField(u, "line_user_id", "LINE 使用者 ID")}>{u.line_user_id ? u.line_user_id.slice(0, 8) + "…" : "未設定"}</a></td>
                <td><a className="link" onClick={() => editField(u, "email", "Email")}>{u.email || "未設定"}</a></td>
                <td className="muted">{time(u.last_login_at)}</td>
                <td>{u.disabled ? <span className="badge">停用</span> : <span className="badge live">啟用</span>}</td>
                <td>
                  <button className="ghost tiny" onClick={() => resetPw(u)}>重設密碼</button>{" "}
                  {u.id !== myId && <button className="ghost tiny" onClick={() => patch(u.id, { disabled: !u.disabled }, u.disabled ? "已啟用" : "已停用")}>{u.disabled ? "啟用" : "停用"}</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">LINE 使用者 ID 在 LINE Developers 的 Messaging API 頻道加入好友後，從 webhook 事件或「Your user ID」取得；通知的 channel access token 仍在伺服器的 .env。</p>
    </section>
  );
}
