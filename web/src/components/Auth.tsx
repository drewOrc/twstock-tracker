/* Session state for the whole app: who is logged in, login screen, logout. */
import { createContext, useCallback, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { auth, setUnauthorizedHandler } from "../api/client";

export interface Me { id: number; username: string; display_name: string | null; role: "admin" | "member"; line_user_id: string | null; email: string | null }

interface AuthCtx { me: Me | null; refresh: () => Promise<void>; logout: () => Promise<void> }
const Ctx = createContext<AuthCtx>({ me: null, refresh: async () => {}, logout: async () => {} });
export const useMe = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [checked, setChecked] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setMe(await auth("/me"));
    } catch {
      setMe(null);
    } finally {
      setChecked(true);
    }
  }, []);
  const logout = useCallback(async () => {
    try { await auth("/logout", { method: "POST" }); } catch { /* ignore */ }
    setMe(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setMe(null));
    refresh();
    return () => {
      setUnauthorizedHandler(null);
    };
  }, [refresh]);

  if (!checked) return <div className="login-wrap"><div className="login-box muted">連線中…</div></div>;
  if (!me) return <Login onDone={refresh} />;
  return <Ctx.Provider value={{ me, refresh, logout }}>{children}</Ctx.Provider>;
}

function Login({ onDone }: { onDone: () => Promise<void> }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await auth("/login", { method: "POST", body: { username, password } });
      await onDone();
    } catch (err: any) {
      setError(err?.message ?? "登入失敗");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-box" onSubmit={submit}>
        <div className="brand">台股追蹤引擎 <span className="sub">TW Stock Tracker + Stock CRM</span></div>
        <label>帳號<input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></label>
        <label>密碼<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        {error && <div className="warn-box">{error}</div>}
        <button className="primary" disabled={busy}>{busy ? "登入中…" : "登入"}</button>
        <div className="kv">帳號由管理員建立。忘記密碼請找管理員重設。</div>
      </form>
    </div>
  );
}
