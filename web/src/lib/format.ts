/* Number / date formatting shared by engine pages (zh-TW) and CRM pages. */
type N = number | null | undefined;

export const num = (v: N, d = 2) =>
  v == null ? "–" : Number(v).toLocaleString("zh-TW", { minimumFractionDigits: d, maximumFractionDigits: d });
export const int = (v: N) => (v == null ? "–" : Number(v).toLocaleString("zh-TW"));
export const signed = (v: N, d = 0) =>
  v == null ? "–" : (v > 0 ? "+" : "") + Number(v).toLocaleString("zh-TW", { minimumFractionDigits: d, maximumFractionDigits: d });
export const pctS = (v: N, d = 2) => (v == null ? "–" : signed(v, d) + "%");
export const cls = (v: N) => (v == null || v === 0 ? "" : v > 0 ? "up" : "down");
export const time = (iso?: string | null) => (iso ? new Date(iso).toLocaleString("zh-TW", { hour12: false }) : "–");
export const yi = (v: N) => (v == null ? "–" : (v / 1e8).toFixed(1) + " 億");
export const lots = (shares: N) => (shares == null ? null : Math.round(shares / 1000));

/* CRM conventions: fractions 0..1, UTC "YYYY-MM-DD HH:MM:SS" timestamps */
export const pct0 = (v: N) => (v == null ? "?" : Math.round(v * 100) + "%");
export const spct = (v: N) => (v == null ? "" : (v > 0 ? "+" : "") + (v * 100).toFixed(0) + "%");
export const cnum = (v: N) => (v == null ? "–" : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString("en-US") : String(v));
export const tpe = (ts?: string | null) =>
  ts
    ? new Date(ts.replace(" ", "T") + "Z").toLocaleString("zh-TW", {
        timeZone: "Asia/Taipei",
        hour12: false,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

/** Identity bridge between the two backends: engine code "2330" <-> CRM company id "TW:2330". */
export const toCrmId = (code: string) => `TW:${code.toUpperCase()}`;
export const toCode = (crmId: string) => (crmId.startsWith("TW:") ? crmId.slice(3) : null);
