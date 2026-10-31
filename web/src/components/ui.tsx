/* Base pieces shared by every page (canvas board 27 §3): freshness tag, "mine" tag, source tag, stock row. */
import { Link } from "react-router-dom";
import { cls, num, pctS } from "../lib/format";

export type FreshKind = "live" | "close" | "late" | "stale" | "off";

/** Data-time marker. kind: live=盤中 close=收盤 late=落後 stale=過期 off=休市/未設定 */
export function FreshTag({ kind, children, title }: { kind: FreshKind; children: React.ReactNode; title?: string }) {
  return <span className={`ftag ${kind === "close" ? "" : kind}`} title={title}>{children}</span>;
}

/** Amber "this is yours" marker; variant sys = system list (dashed), alert = fired alert (red). */
export function MineTag({ variant, children }: { variant?: "sys" | "alert"; children: React.ReactNode }) {
  return <span className={`mtag ${variant ?? ""}`}>{children}</span>;
}

/** Source marker for shared-layer data: 官方 / 交易所 / agent · confidence. */
export function SourceTag({ children, title }: { children: React.ReactNode; title?: string }) {
  return <span className="stag" title={title}>{children}</span>;
}

export interface StockRowData {
  code: string;
  name: string;
  sector?: string | null;
  market?: string | null;
  price?: number | null;
  change_pct?: number | null;
}

/** One stock per row: code+name, optional marks, price and change on the right. Links to the stock page. */
export function StockRow({ s, marks, to, onClick, active }: { s: StockRowData; marks?: React.ReactNode; to?: string; onClick?: () => void; active?: boolean }) {
  const body = (
    <>
      <div className="nm">
        <b>{s.code} {s.name}</b>
        <div className="sub">
          {s.sector && <span>{s.sector}</span>}
          {s.market && <span>· {s.market}</span>}
          {marks}
        </div>
      </div>
      {s.price != null && (
        <div className={`px ${cls(s.change_pct)}`}>
          <b>{num(s.price)}</b>
          <span>{pctS(s.change_pct)}</span>
        </div>
      )}
    </>
  );
  const className = `stock-row${active ? " on" : ""}`;
  if (onClick) return <div className={className} role="button" tabIndex={0} onClick={onClick} onKeyDown={(e) => e.key === "Enter" && onClick()}>{body}</div>;
  return <Link to={to ?? `/stock/${s.code}`} className={className}>{body}</Link>;
}
