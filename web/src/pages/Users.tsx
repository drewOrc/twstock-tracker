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
    </>
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
