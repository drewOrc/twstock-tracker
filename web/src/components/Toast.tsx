import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

type ToastFn = (msg: string, isError?: boolean) => void;
const Ctx = createContext<ToastFn>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [item, setItem] = useState<{ msg: string; error: boolean } | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const toast = useCallback<ToastFn>((msg, isError = false) => {
    setItem({ msg, error: isError });
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setItem(null), isError ? 6000 : 3500);
  }, []);
  return (
    <Ctx.Provider value={toast}>
      {children}
      {item && <div className={`toast ${item.error ? "error" : ""}`}>{item.msg}</div>}
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);

/** Wrap an async action so failures surface as a toast instead of an unhandled rejection. */
export function useAction() {
  const toast = useToast();
  return useCallback(
    async (fn: () => Promise<unknown>, okMsg?: string) => {
      try {
        await fn();
        if (okMsg) toast(okMsg);
        return true;
      } catch (e: any) {
        toast(e?.message ?? String(e), true);
        return false;
      }
    },
    [toast],
  );
}
