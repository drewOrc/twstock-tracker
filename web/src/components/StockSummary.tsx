/* 基本介紹 + 最近狀況 for one TW code, from the engine's /api/stocks/{code}/summary. */
import { engine, useAsync } from "../api/client";
import { cls, int, num, pctS, signed } from "../lib/format";

export function StockSummary({ code, compact = false }: { code: string; compact?: boolean }) {
  const q = useAsync(() => engine(`/stocks/${code}/summary`), [code]);
  if (q.error) return <div className="kv">引擎沒有 {code} 的資料：{q.error}</div>;
  const s = q.data;
  if (!s) return <div className="kv">載入中…</div>;
  const p = s.profile, pr = s.price, ch = s.chips, ctx = s.context;
  return (
    <>
      <section>
        <h4>基本介紹 <span className="kv">{p.market_label} · {p.sector}{p.industry ? `（產業別 ${p.industry}）` : ""}</span></h4>
        <div className="profile-grid">
          <div><span className="k">全名</span>{p.full_name ?? p.name}{p.name_en ? <span className="kv"> {p.name_en}</span> : null}</div>
          {p.chairman && <div><span className="k">董事長</span>{p.chairman}</div>}
          {p.general_manager && <div><span className="k">總經理</span>{p.general_manager}</div>}
          {p.founded && <div><span className="k">成立</span>{p.founded}</div>}
          {p.listed_date && <div><span className="k">{p.market_label}</span>{p.listed_date}</div>}
          {p.capital_yi != null && <div><span className="k">實收資本額</span>{num(p.capital_yi, 1)} 億</div>}
          {p.shares_issued != null && <div><span className="k">發行股數</span>{int(Math.round(p.shares_issued / 1000))} 張</div>}
          {p.website && <div><span className="k">網站</span><a href={p.website} target="_blank" rel="noopener noreferrer">{p.website.replace(/^https?:\/\//, "")}</a></div>}
          {!compact && p.address && <div className="wide"><span className="k">地址</span>{p.address}</div>}
          {!p.is_common_stock && <div className="wide kv">ETF / 非一般股票：沒有公司基本資料，不計入類股統計。</div>}
        </div>
      </section>

      <section>
        <h4>最近狀況 <span className="kv">{pr.available ? `資料至 ${pr.as_of}，${pr.history_days} 個交易日` : "尚無日線資料"}</span></h4>
        {pr.available && (
          <>
            <div className="tiles small-tiles">
              <div className="tile"><div className="k">{pr.quote ? `現價 ${pr.quote.time ?? ""}` : "收盤"}</div><div className={`v ${cls(pr.quote?.change_pct ?? pr.change_pct)}`}>{num(pr.quote?.price ?? pr.close)}</div><div className="s">{pctS(pr.quote?.change_pct ?? pr.change_pct)} · 量 {int(pr.quote?.volume_lots ?? pr.volume_lots)} 張{pr.volume_ratio ? `（${pr.volume_ratio}x 均量）` : ""}</div></div>
              <div className="tile"><div className="k">20 日 / 相對加權</div><div className={`v ${cls(pr.returns["20d"])}`}>{pctS(pr.returns["20d"])}</div><div className="s">加權 {pctS(pr.index_returns["20d"])} · 相對 {pctS(pr.relative["20d"])}</div></div>
              <div className="tile"><div className="k">5 日 / 60 日</div><div className="v"><span className={cls(pr.returns["5d"])}>{pctS(pr.returns["5d"])}</span> <span className="kv">/</span> <span className={cls(pr.returns["60d"])}>{pctS(pr.returns["60d"])}</span></div><div className="s">相對加權 {pctS(pr.relative["5d"])} / {pctS(pr.relative["60d"])}</div></div>
              <div className="tile"><div className="k">類股 {pr.sector.name}</div><div className="v">{pr.sector.rank_20d ? `${pr.sector.rank_20d} / ${pr.sector.peers}` : "–"}</div><div className="s">20 日排名 · 類股均 {pctS(pr.sector.ret_20d)}</div></div>
              <div className="tile"><div className="k">{pr.range.label}位置</div><div className={`v ${cls(pr.range.from_high_pct)}`}>{pctS(pr.range.from_high_pct, 1)}</div><div className="s">距高點 · 高 {num(pr.range.high)} 低 {num(pr.range.low)}</div></div>
              <div className="tile"><div className="k">均線 / 指標</div><div className="v">{pr.alignment ?? "–"}</div><div className="s">MA20 {num(pr.ma.ma20)} · RSI {num(pr.rsi14, 0)} · K {num(pr.k, 0)} D {num(pr.d, 0)}</div></div>
            </div>
            {ch.available && (
              <div className="chips-line">
                <span>外資 5 日 <b className={cls(ch.foreign_5d)}>{signed(ch.foreign_5d)}</b> / 20 日 <b className={cls(ch.foreign_20d)}>{signed(ch.foreign_20d)}</b> 張{ch.foreign_streak >= 3 ? `，連買 ${ch.foreign_streak} 日` : ""}</span>
                <span>投信 5 日 <b className={cls(ch.trust_5d)}>{signed(ch.trust_5d)}</b> / 20 日 <b className={cls(ch.trust_20d)}>{signed(ch.trust_20d)}</b> 張</span>
                {ch.margin_balance != null && <span>融資 {int(ch.margin_balance)} 張，20 日 <b className={cls(ch.margin_change_20d)}>{signed(ch.margin_change_20d)}</b>（{pctS(ch.margin_change_20d_pct, 1)}）</span>}
                <span className="kv">籌碼至 {ch.as_of ?? ch.margin_as_of}</span>
              </div>
            )}
          </>
        )}
        <div className="ctx-line">
          {ctx.screener.map((x: any) => <span key={x.preset} className="tag">{x.preset} #{x.rank} · {Math.round(x.score)} 分{x.tags?.length ? ` · ${x.tags.slice(0, 3).join(" / ")}` : ""}</span>)}
          {ctx.lists.map((l: any) => <span key={l.id} className="chip" style={{ borderColor: l.color ?? undefined }}>{l.name}</span>)}
          {ctx.alert_rules > 0 && <span className="badge live">{ctx.alert_rules} 條警示</span>}
          {ctx.recent_alerts[0] && <span className="kv">最近警示：{ctx.recent_alerts[0].message}</span>}
        </div>
      </section>

      {s.news && (
        <section>
          <h4>最近新聞 <span className="kv">Google News「{s.news.query}」{s.news.error ? ` · 取得失敗（${s.news.error}）` : ""}</span></h4>
          {s.news.items.length ? (
            <ul className="news">
              {s.news.items.slice(0, compact ? 5 : 10).map((n: any, i: number) => (
                <li key={i}><a href={n.link} target="_blank" rel="noopener noreferrer">{n.title}</a><span className="kv"> {n.source}{n.published ? ` · ${new Date(n.published).toLocaleDateString("zh-TW")}` : ""}</span></li>
              ))}
            </ul>
          ) : <div className="kv">沒有抓到新聞。</div>}
        </section>
      )}
    </>
  );
}
