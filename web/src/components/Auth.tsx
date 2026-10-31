/* Session state for the whole app: who is logged in, login screen, logout. */
import { createContext, useCallback, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { auth, publicApi, setUnauthorizedHandler, useAsync } from "../api/client";

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

/* Login (canvas board 26): says where you will land, checks the engine first, explains lockouts, no self-signup.
 * The URL is left untouched while the login box is shown, so "next" is simply the current location. */
function Login({ onDone }: { onDone: () => Promise<void> }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const health = useAsync(() => publicApi("/health"), [], 15000);
  const next = window.location.pathname + window.location.search + window.location.hash;
  const engineDown = !!health.error;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await auth("/login", { method: "POST", body: { username, password } });
      await onDone();
    } catch (err: any) {
      const msg: string = err?.message ?? "登入失敗";
      setError(err?.status === 429 ? `這個帳號暫時鎖定：${msg}` : msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-box" onSubmit={submit}>
        <div className="brand-mark"><span className="logo" />台股追蹤 <span className="sub muted">家人用的台股研究系統</span></div>
        {next !== "/" && <div className="brief">登入後會回到：<b>{next}</b></div>}
        {engineDown && <div className="warn-box">系統現在連不上（/api/health 無回應）。這不是帳密問題，請稍後再試或聯絡 Drew。</div>}
        <label>帳號<input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required disabled={engineDown} /></label>
        <label>密碼<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required disabled={engineDown} /></label>
        {error && <div className="warn-box">{error}</div>}
        <button className="primary" disabled={busy || engineDown}>{busy ? "登入中…" : "登入"}</button>
        <div className="kv">沒有帳號或忘記密碼？這個系統沒有自助註冊，請找 Drew 建立或重設。連續失敗 5 次會鎖 10 分鐘。</div>
      </form>
    </div>
  );
}
