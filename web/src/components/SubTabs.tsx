/* Hash-driven section tabs inside a view (/me#today, /market#screener …). Each tab mounts one page. */
import { type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

export interface SubTab { key: string; label: string; element: ReactNode; count?: number | null; hidden?: boolean }

export function SubTabs({ tabs, fallback, note }: { tabs: SubTab[]; fallback: string; note?: string }) {
  const { hash, pathname, search } = useLocation();
  const visible = tabs.filter((t) => !t.hidden);
  const key = hash.replace(/^#/, "").split("&")[0];
  const current = visible.find((t) => t.key === key) ?? visible.find((t) => t.key === fallback) ?? visible[0];
  return (
    <>
      <nav className="sub-tabs" aria-label="段落">
        {visible.map((t) => (
          <Link key={t.key} to={{ pathname, search, hash: `#${t.key}` }} className={t.key === current?.key ? "active" : ""} replace>
            {t.label}
            {t.count != null && t.count > 0 ? <span className="cnt">{t.count}</span> : null}
          </Link>
        ))}
        {note && <span className="legacy">{note}</span>}
      </nav>
      {current?.element}
    </>
  );
}
