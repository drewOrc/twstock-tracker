/* TW Stock Tracker - vanilla JS dashboard talking to the FastAPI backend at /api */
(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const state = {
    watchlist: [],
    selected: null,
    ruleTypes: [],
    chart: null,
    series: {},
    tab: "chart",
  };

  // ------------------------------------------------------------------ helpers
  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    if (res.status === 204) return null;
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `${res.status} ${res.statusText}`);
    return data;
  }

  let toastTimer;
  function toast(msg, isError = false) {
    const el = $("#toast");
    el.textContent = msg;
    el.classList.toggle("error", isError);
    el.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), 4000);
  }

  const fmt = {
    num: (v, d = 2) => (v === null || v === undefined ? "–" : Number(v).toLocaleString("zh-TW", { minimumFractionDigits: d, maximumFractionDigits: d })),
    int: (v) => (v === null || v === undefined ? "–" : Number(v).toLocaleString("zh-TW")),
    signed: (v, d = 0) => (v === null || v === undefined ? "–" : (v > 0 ? "+" : "") + Number(v).toLocaleString("zh-TW", { minimumFractionDigits: d, maximumFractionDigits: d })),
    cls: (v) => (v === null || v === undefined || v === 0 ? "" : v > 0 ? "up" : "down"),
    time: (iso) => (iso ? new Date(iso).toLocaleString("zh-TW", { hour12: false }) : "–"),
    esc: (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])),
  };

  // ------------------------------------------------------------------ status bar
  async function loadStatus() {
    try {
      const [h, j] = await Promise.all([api("/api/health"), api("/api/jobs")]);
      const rt = j.realtime || {};
      const live = h.trading_hours && h.scheduler.running && !rt.error;
      const ch = Object.entries(h.channels).filter(([, on]) => on).map(([k]) => k).join(", ") || "無";
      $("#status").innerHTML =
        `<span class="dot ${live ? "live" : ""}"></span>` +
        `${h.trading_hours ? "盤中" : "非交易時段"} · 排程 ${h.scheduler.running ? "運行中" : "停止"} · ` +
        `即時更新 ${rt.last_success ? fmt.time(rt.last_success) : "尚未"}${rt.error ? ` <span class="up">(${fmt.esc(rt.error)})</span>` : ""} · 通知: ${ch}`;
      renderJobs(j);
    } catch (e) {
      $("#status").textContent = "無法連線到後端：" + e.message;
    }
  }

  // ------------------------------------------------------------------ watchlist
  async function loadWatchlist() {
    state.watchlist = await api("/api/watchlist");
    renderWatchlist();
  }

  function renderWatchlist() {
    const tbody = $("#watch-table tbody");
    const rows = state.watchlist;
    $("#watch-empty").classList.toggle("hidden", rows.length > 0);
    tbody.innerHTML = rows
      .map((r) => {
        const sel = r.code === state.selected ? "selected" : "";
        const upd = r.realtime ? `<span class="badge live" title="即時">${fmt.esc(r.quote_time || "")}</span>` : `<span class="badge" title="日線收盤">${fmt.esc(r.daily_date || "–")}</span>`;
        return `<tr data-code="${r.code}" class="${sel}">
          <td><b>${r.code}</b></td>
          <td>${fmt.esc(r.name || "")}${r.note ? ` <span class="muted" title="${fmt.esc(r.note)}">※</span>` : ""}</td>
          <td><span class="badge">${r.market === "TPEX" ? "上櫃" : "上市"}</span></td>
          <td class="num ${fmt.cls(r.change)}">${fmt.num(r.price)}</td>
          <td class="num ${fmt.cls(r.change)}">${fmt.signed(r.change, 2)}</td>
          <td class="num ${fmt.cls(r.change)}">${r.change_pct === null ? "–" : fmt.signed(r.change_pct, 2) + "%"}</td>
          <td class="num">${fmt.int(r.volume_lots)}</td>
          <td class="num ${fmt.cls(r.foreign_net_lots)}">${fmt.signed(r.foreign_net_lots)}</td>
          <td class="num ${fmt.cls(r.trust_net_lots)}">${fmt.signed(r.trust_net_lots)}</td>
          <td class="num ${fmt.cls(r.dealer_net_lots)}">${fmt.signed(r.dealer_net_lots)}</td>
          <td class="num">${fmt.int(r.margin_balance)} <span class="muted ${fmt.cls(r.margin_change)}">${r.margin_change === null ? "" : "(" + fmt.signed(r.margin_change) + ")"}</span></td>
          <td class="num">${fmt.int(r.short_balance)} <span class="muted ${fmt.cls(r.short_change)}">${r.short_change === null ? "" : "(" + fmt.signed(r.short_change) + ")"}</span></td>
          <td>${upd}</td>
          <td><button class="danger" data-remove="${r.code}" title="移除">✕</button></td>
        </tr>`;
      })
      .join("");
  }

  $("#watch-table").addEventListener("click", async (e) => {
    const rm = e.target.closest("[data-remove]");
    if (rm) {
      const code = rm.dataset.remove;
      if (!confirm(`移除 ${code}？相關警示規則也會刪除。`)) return;
      try {
        await api(`/api/watchlist/${code}`, { method: "DELETE" });
        if (state.selected === code) state.selected = null;
        await loadWatchlist();
        toast(`已移除 ${code}`);
      } catch (err) {
        toast(err.message, true);
      }
      return;
    }
    const tr = e.target.closest("tr[data-code]");
    if (tr) selectStock(tr.dataset.code);
  });

  $("#add-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const raw = $("#add-code").value.trim();
    const code = (raw.split(/\s+/)[0] || "").toUpperCase();
    if (!code) return;
    try {
      const r = await api("/api/watchlist", { method: "POST", body: { code, note: $("#add-note").value || null } });
      toast(`已加入 ${r.code} ${r.name}，正在背景補歷史資料…`);
      $("#add-code").value = "";
      $("#add-note").value = "";
      await loadWatchlist();
      selectStock(r.code);
      setTimeout(loadWatchlist, 15000);
      setTimeout(() => { loadWatchlist(); if (state.selected === r.code) loadDetail(); }, 45000);
    } catch (err) {
      toast(err.message, true);
    }
  });

  let searchTimer;
  $("#add-code").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    const q = e.target.value.trim();
    if (q.length < 1) return;
    searchTimer = setTimeout(async () => {
      try {
        const res = await api(`/api/stocks/search?q=${encodeURIComponent(q)}&limit=15`);
        $("#stock-options").innerHTML = res.map((s) => `<option value="${s.code} ${fmt.esc(s.name)}"></option>`).join("");
      } catch (_) { /* ignore */ }
    }, 250);
  });

  // ------------------------------------------------------------------ detail
  function selectStock(code) {
    state.selected = code;
    renderWatchlist();
    loadDetail();
  }

  async function loadDetail() {
    const code = state.selected;
    if (!code) return;
    const row = state.watchlist.find((r) => r.code === code);
    $("#detail-title").textContent = `${code} ${row?.name || ""}`;
    try {
      const [ind, inst, margin, rules] = await Promise.all([
        api(`/api/stocks/${code}/indicators?limit=250`),
        api(`/api/stocks/${code}/institutional?limit=40`),
        api(`/api/stocks/${code}/margin?limit=40`),
        api(`/api/alerts?code=${code}`),
      ]);
      renderChart(ind);
      renderIndicators(ind.latest || {});
      renderInst(inst);
      renderMargin(margin);
      renderRules(rules);
    } catch (err) {
      toast(err.message, true);
    }
  }

  function ensureChart() {
    if (state.chart) return;
    const el = $("#chart");
    const chart = LightweightCharts.createChart(el, {
      layout: { background: { color: "#171d26" }, textColor: "#8b97a8" },
      grid: { vertLines: { color: "#232c38" }, horzLines: { color: "#232c38" } },
      rightPriceScale: { borderColor: "#2a3441" },
      timeScale: { borderColor: "#2a3441", timeVisible: false },
      crosshair: { mode: 0 },
      autoSize: true,
    });
    state.series.candle = chart.addCandlestickSeries({
      upColor: "#ef5350", downColor: "#26a69a", borderVisible: false, wickUpColor: "#ef5350", wickDownColor: "#26a69a",
    });
    state.series.vol = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol" });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    state.series.ma5 = chart.addLineSeries({ color: "#f5c542", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    state.series.ma20 = chart.addLineSeries({ color: "#4f8cff", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    state.series.ma60 = chart.addLineSeries({ color: "#c084fc", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    state.chart = chart;
  }

  function renderChart(ind) {
    ensureChart();
    const s = ind.series || {};
    const n = (s.date || []).length;
    const candles = [], vols = [], ma = { ma5: [], ma20: [], ma60: [] };
    for (let i = 0; i < n; i++) {
      const t = s.date[i];
      if (s.open[i] == null || s.close[i] == null) continue;
      candles.push({ time: t, open: s.open[i], high: s.high[i], low: s.low[i], close: s.close[i] });
      const up = s.close[i] >= s.open[i];
      vols.push({ time: t, value: (s.volume[i] || 0) / 1000, color: up ? "rgba(239,83,80,.45)" : "rgba(38,166,154,.45)" });
      for (const k of Object.keys(ma)) if (s[k] && s[k][i] != null) ma[k].push({ time: t, value: s[k][i] });
    }
    state.series.candle.setData(candles);
    state.series.vol.setData(vols);
    for (const k of Object.keys(ma)) state.series[k].setData(ma[k]);
    state.chart.timeScale().fitContent();
  }

  function renderIndicators(l) {
    const rows = [
      ["日期", l.date], ["收盤", fmt.num(l.close)], ["成交量(張)", fmt.int(l.volume ? l.volume / 1000 : null)],
      ["MA5 / MA10", `${fmt.num(l.ma5)} / ${fmt.num(l.ma10)}`], ["MA20 / MA60 / MA120", `${fmt.num(l.ma20)} / ${fmt.num(l.ma60)} / ${fmt.num(l.ma120)}`],
      ["RSI(14)", fmt.num(l.rsi14, 1)], ["K / D (9,3,3)", `${fmt.num(l.k, 1)} / ${fmt.num(l.d, 1)}`],
      ["MACD DIF / DEA / 柱", `${fmt.num(l.macd_dif)} / ${fmt.num(l.macd_dea)} / ${fmt.num(l.macd_hist)}`],
      ["布林 上 / 中 / 下", `${fmt.num(l.bb_upper)} / ${fmt.num(l.bb_mid)} / ${fmt.num(l.bb_lower)}`],
      ["20 日均量(張)", fmt.int(l.vol_ma20 ? l.vol_ma20 / 1000 : null)],
    ];
    $("#ind-table tbody").innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td>${v ?? "–"}</td></tr>`).join("");
  }

  function renderInst(rows) {
    const lots = (v) => (v === null || v === undefined ? "–" : `<span class="${fmt.cls(v)}">${fmt.signed(Math.round(v / 1000))}</span>`);
    $("#inst-table tbody").innerHTML = rows.length
      ? rows.map((r) => `<tr><td>${r.date}</td><td class="num">${lots(r.foreign_net)}</td><td class="num">${lots(r.trust_net)}</td><td class="num">${lots(r.dealer_net)}</td><td class="num">${lots(r.total_net)}</td></tr>`).join("")
      : `<tr><td colspan="5" class="muted">尚無資料（新加入的股票會在背景補 20 個交易日）</td></tr>`;
  }

  function renderMargin(rows) {
    const d = (a, b) => (a == null || b == null ? "–" : `<span class="${fmt.cls(a - b)}">${fmt.signed(a - b)}</span>`);
    $("#margin-table tbody").innerHTML = rows.length
      ? rows.map((r) => `<tr><td>${r.date}</td><td class="num">${fmt.int(r.margin_balance)}</td><td class="num">${d(r.margin_balance, r.margin_prev)}</td><td class="num">${fmt.int(r.short_balance)}</td><td class="num">${d(r.short_balance, r.short_prev)}</td><td class="num">${fmt.int(r.offset)}</td></tr>`).join("")
      : `<tr><td colspan="6" class="muted">尚無資料</td></tr>`;
  }

  // tabs
  $("#detail-tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]");
    if (!b) return;
    state.tab = b.dataset.tab;
    $$("#detail-tabs button").forEach((x) => x.classList.toggle("active", x === b));
    $$("#detail .tab-body").forEach((x) => x.classList.toggle("active", x.dataset.tab === state.tab));
    if (state.tab === "chart" && state.chart) state.chart.timeScale().fitContent();
  });

  // ------------------------------------------------------------------ alerts
  async function loadRuleTypes() {
    state.ruleTypes = await api("/api/alerts/rule-types");
    $("#alert-type").innerHTML = state.ruleTypes.map((t) => `<option value="${t.type}">${t.label}（${t.scope === "intraday" ? "盤中" : "日線"}）</option>`).join("");
    renderParamInputs();
  }

  function renderParamInputs() {
    const t = state.ruleTypes.find((x) => x.type === $("#alert-type").value);
    if (!t) return;
    $("#alert-params").innerHTML = t.params
      .map((p) => {
        if (p.type === "select") {
          return `<label>${p.label} <select name="${p.name}">${p.options.map((o) => `<option ${o === p.default ? "selected" : ""}>${o}</option>`).join("")}</select></label>`;
        }
        return `<label>${p.label} <input name="${p.name}" type="number" step="any" value="${p.default ?? ""}" ${p.default === undefined ? "required" : ""} /></label>`;
      })
      .join("");
    $("#alert-cooldown").value = t.default_cooldown;
  }
  $("#alert-type").addEventListener("change", renderParamInputs);

  $("#alert-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!state.selected) return toast("請先選擇股票", true);
    const params = {};
    $$("#alert-params [name]").forEach((el) => (params[el.name] = el.value));
    try {
      await api("/api/alerts", {
        method: "POST",
        body: {
          code: state.selected,
          rule_type: $("#alert-type").value,
          params,
          one_shot: $("#alert-oneshot").checked,
          cooldown_minutes: Number($("#alert-cooldown").value),
          note: $("#alert-note").value || null,
        },
      });
      toast("警示已新增");
      $("#alert-note").value = "";
      renderRules(await api(`/api/alerts?code=${state.selected}`));
    } catch (err) {
      toast(err.message, true);
    }
  });

  function renderRules(rules) {
    const label = (t) => state.ruleTypes.find((x) => x.type === t)?.label || t;
    $("#rules-table tbody").innerHTML = rules.length
      ? rules
          .map(
            (r) => `<tr data-rule="${r.id}">
          <td>${label(r.rule_type)}${r.note ? ` <span class="muted">${fmt.esc(r.note)}</span>` : ""}</td>
          <td class="muted">${fmt.esc(Object.entries(r.params).map(([k, v]) => `${k}=${v}`).join(", "))}</td>
          <td>${r.enabled ? `<span class="badge live">啟用</span>` : `<span class="badge">停用</span>`}${r.one_shot ? ` <span class="badge">單次</span>` : ""} <span class="muted">${r.cooldown_minutes}m</span></td>
          <td class="muted">${fmt.time(r.last_triggered_at)}</td>
          <td><button class="ghost" data-toggle="${r.id}" data-enabled="${r.enabled}">${r.enabled ? "停用" : "啟用"}</button> <button class="danger" data-del="${r.id}">✕</button></td>
        </tr>`
          )
          .join("")
      : `<tr><td colspan="5" class="muted">尚無警示規則</td></tr>`;
  }

  $("#rules-table").addEventListener("click", async (e) => {
    const t = e.target.closest("[data-toggle]");
    const d = e.target.closest("[data-del]");
    try {
      if (t) await api(`/api/alerts/${t.dataset.toggle}`, { method: "PATCH", body: { enabled: t.dataset.enabled !== "true" } });
      if (d) await api(`/api/alerts/${d.dataset.del}`, { method: "DELETE" });
      if (t || d) renderRules(await api(`/api/alerts?code=${state.selected}`));
    } catch (err) {
      toast(err.message, true);
    }
  });

  async function loadEvents() {
    const events = await api("/api/alerts/events?limit=50");
    $("#events-empty").classList.toggle("hidden", events.length > 0);
    $("#events-list").innerHTML = events
      .map((ev) => {
        const delivery = ev.delivery ? Object.entries(ev.delivery).map(([k, v]) => `${k}:${v === "ok" ? "✓" : "✗"}`).join(" ") : "";
        return `<li><time>${fmt.time(ev.triggered_at)}</time>${fmt.esc(ev.message)}<span class="delivery">${fmt.esc(delivery)}</span></li>`;
      })
      .join("");
  }

  // ------------------------------------------------------------------ jobs
  function renderJobs(j) {
    $("#jobs-scheduled").innerHTML = (j.scheduled || [])
      .map((s) => `<div class="job-card"><b>${fmt.esc(s.name)}</b><span class="next">下次：${fmt.time(s.next_run)}</span></div>`)
      .join("") || `<div class="muted">排程未啟用（SCHEDULER_ENABLED=false）</div>`;
  }

  async function loadRuns() {
    const runs = await api("/api/jobs/runs?limit=20");
    $("#job-runs").innerHTML = runs
      .map((r) => `<li><time>${fmt.time(r.started_at)}</time><span class="${r.ok ? "ok" : "fail"}">${r.ok ? "OK " : "ERR"}</span> ${fmt.esc(r.job)} ${fmt.esc(r.detail || "")}</li>`)
      .join("");
  }

  // ------------------------------------------------------------------ toolbar
  $("#btn-refresh-quotes").addEventListener("click", async () => {
    try {
      const r = await api("/api/quotes/refresh", { method: "POST" });
      toast(`已更新 ${r.quotes.length} 檔報價${r.alerts.length ? `，觸發 ${r.alerts.length} 個警示` : ""}`);
      await Promise.all([loadWatchlist(), loadEvents()]);
    } catch (err) {
      toast(err.message, true);
    }
  });
  $("#btn-run-daily").addEventListener("click", async () => {
    try {
      await api("/api/jobs/full_daily/run", { method: "POST" });
      toast("每日更新已在背景開始，約 10–20 秒後完成");
      setTimeout(async () => { await Promise.all([loadWatchlist(), loadEvents(), loadRuns()]); if (state.selected) loadDetail(); }, 15000);
    } catch (err) {
      toast(err.message, true);
    }
  });
  $("#btn-notify-test").addEventListener("click", async () => {
    try {
      const r = await api("/api/notify/test", { method: "POST", body: { message: "測試通知 from 台股追蹤引擎" } });
      toast("通知結果：" + Object.entries(r.result).map(([k, v]) => `${k}=${v}`).join("; "));
    } catch (err) {
      toast(err.message, true);
    }
  });
  $("#btn-eval").addEventListener("click", async () => {
    try {
      const r = await api("/api/alerts/evaluate", { method: "POST" });
      toast(`評估完成，觸發 ${r.alerts.length} 個警示`);
      loadEvents();
    } catch (err) {
      toast(err.message, true);
    }
  });

  // ------------------------------------------------------------------ market breadth (盤面分化)
  const mk = { dates: [], date: null, hist: [], sectorHist: null, open: new Set() };
  const yi = (v) => (v === null || v === undefined ? "–" : (v / 1e8).toFixed(1) + " 億");
  const pctCell = (v) => (v === null || v === undefined ? `<span class="muted">–</span>` : `<span class="heat ${fmt.cls(v)}" style="background:${heatColor(v)}">${fmt.signed(v, 2)}%</span>`);
  function heatColor(v) {
    const a = Math.min(Math.abs(v) / 4, 1) * 0.45;
    return v > 0 ? `rgba(239,83,80,${a})` : v < 0 ? `rgba(38,166,154,${a})` : "transparent";
  }

  async function loadMarketDates() {
    mk.dates = await api("/api/market/dates?limit=60");
    const sel = $("#mk-date");
    sel.innerHTML = mk.dates.map((d) => `<option value="${d}">${d}</option>`).join("");
    if (!mk.date || !mk.dates.includes(mk.date)) mk.date = mk.dates[0] || null;
    if (mk.date) sel.value = mk.date;
    $("#mk-empty").classList.toggle("hidden", mk.dates.length > 0);
    $("#mk-body").classList.toggle("hidden", mk.dates.length === 0);
  }

  async function loadMarket() {
    await loadMarketDates();
    if (!mk.date) return;
    try {
      const [b, hist, sh] = await Promise.all([
        api(`/api/market/breadth?date=${mk.date}`),
        api("/api/market/breadth/history?days=30"),
        api("/api/market/sectors/history?days=10"),
      ]);
      mk.hist = hist;
      mk.sectorHist = sh;
      renderMarketTiles(b);
      renderBreadthChart(hist);
      renderDist(b.distribution);
      renderSectors(b, sh);
      renderMovers(b);
    } catch (err) {
      toast(err.message, true);
    }
  }

  function renderMarketTiles(b) {
    const a = b.markets.ALL, t = b.markets.TWSE, o = b.markets.TPEX;
    const tiles = [
      ["上漲 / 下跌 / 平盤", `<span class="up">${a.advance}</span> / <span class="down">${a.decline}</span> / ${a.flat}`, `上市 ${t.advance}/${t.decline} · 上櫃 ${o.advance}/${o.decline}`],
      ["上漲比例", `${a.adv_ratio ?? "–"}%`, `上市 ${t.adv_ratio ?? "–"}% · 上櫃 ${o.adv_ratio ?? "–"}%`],
      ["漲停 / 跌停", `<span class="up">${a.limit_up}</span> / <span class="down">${a.limit_down}</span>`, t.source === "official" ? "上市為證交所官方統計" : "依漲跌幅 ±9.5% 估算"],
      ["加權指數", b.index_pct === null ? "–" : `<span class="${fmt.cls(b.index_pct)}">${fmt.signed(b.index_pct, 2)}%</span>`, `個股中位數 ${a.median_pct === null ? "–" : fmt.signed(a.median_pct, 2) + "%"} · 平均 ${a.mean_pct === null ? "–" : fmt.signed(a.mean_pct, 2) + "%"}`],
      ["指數 − 中位數", b.divergence.index_minus_median === null ? "–" : `<span class="${fmt.cls(b.divergence.index_minus_median)}">${fmt.signed(b.divergence.index_minus_median, 2)}%</span>`, "正值＝權值股撐盤、個股普遍較弱"],
      ["前 5 大成交佔比", `${b.divergence.top5_turnover_share}%`, `一般股票成交額 ${yi(a.turnover)}`],
    ];
    $("#mk-tiles").innerHTML = tiles.map(([k, v, s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
  }

  function renderBreadthChart(hist) {
    const el = $("#mk-breadth-chart");
    if (!hist.length) { el.innerHTML = `<div class="muted">尚無歷史</div>`; return; }
    const W = 640, H = 160, padL = 34, padR = 30, top = 10, base = 95, bottom = 150;
    const n = hist.length, slot = (W - padL - padR) / n, bw = Math.max(2, slot * 0.6);
    const maxv = Math.max(...hist.map((h) => Math.max(h.advance, h.decline)), 1);
    const upH = base - top, dnH = bottom - base - 14;
    let s = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">`;
    s += `<line x1="${padL}" y1="${base}" x2="${W - padR}" y2="${base}" stroke="#2a3441"/>`;
    const pts = [];
    hist.forEach((h, i) => {
      const x = padL + i * slot + (slot - bw) / 2;
      const hu = (h.advance / maxv) * upH, hd = (h.decline / maxv) * dnH;
      const sel = h.date === mk.date ? ' stroke="#fff" stroke-width="1"' : "";
      s += `<rect x="${x}" y="${base - hu}" width="${bw}" height="${hu}" fill="#ef5350" opacity=".85"${sel}><title>${h.date} 上漲 ${h.advance} 漲停 ${h.limit_up}</title></rect>`;
      s += `<rect x="${x}" y="${base}" width="${bw}" height="${hd}" fill="#26a69a" opacity=".85"${sel}><title>${h.date} 下跌 ${h.decline} 跌停 ${h.limit_down}</title></rect>`;
      if (h.adv_ratio !== null) pts.push([x + bw / 2, top + (1 - h.adv_ratio / 100) * (bottom - 14 - top)]);
      if (i % Math.ceil(n / 8) === 0) s += `<text x="${x + bw / 2}" y="${H - 2}" font-size="9" fill="#8b97a8" text-anchor="middle">${h.date.slice(5)}</text>`;
    });
    if (pts.length > 1) s += `<polyline points="${pts.map((p) => p.join(",")).join(" ")}" fill="none" stroke="#f5c542" stroke-width="1.5"/>`;
    s += `<text x="2" y="${top + 8}" font-size="9" fill="#f5c542">100%</text><text x="2" y="${bottom - 12}" font-size="9" fill="#f5c542">0%</text>`;
    s += `<text x="${W - padR + 3}" y="${base - 2}" font-size="9" fill="#ef5350">${maxv}</text>`;
    el.innerHTML = s + "</svg>";
  }

  function renderDist(dist) {
    const max = Math.max(...dist.map((d) => d.count), 1);
    $("#mk-dist").innerHTML = dist
      .map((d) => {
        const cls = d.label === "0" ? "" : d.label.startsWith("-") || d.label.startsWith("<") ? "down" : "up";
        return `<div class="row"><span class="muted">${d.label}</span><div class="bar ${cls}" style="width:${(d.count / max) * 100}%"></div><span class="num">${d.count}</span></div>`;
      })
      .join("");
  }

  function renderSectors(b, sh) {
    const cum = {};
    (sh?.sectors || []).forEach((s) => (cum[s.name] = s.cum_pct));
    $("#mk-cum-head").textContent = `${(sh?.dates || []).length} 日累計%`;
    const chips = (xs) => xs.map((x) => `<span class="chip ${fmt.cls(x.pct)}" title="${x.code}">${fmt.esc(x.name)} ${fmt.signed(x.pct, 1)}%</span>`).join(" ");
    $("#mk-sectors tbody").innerHTML = b.sectors
      .map(
        (s) => `<tr class="sector-row" data-sector="${fmt.esc(s.name)}">
        <td><b>${fmt.esc(s.name)}</b></td>
        <td class="num">${s.count}</td>
        <td class="num"><span class="up">${s.advance}</span>/<span class="down">${s.decline}</span></td>
        <td class="num">${pctCell(s.avg_pct)}</td>
        <td class="num">${pctCell(s.median_pct)}</td>
        <td class="num">${pctCell(s.index_pct)}</td>
        <td class="num">${pctCell(cum[s.name] ?? null)}</td>
        <td class="num">${s.turnover_share.toFixed(1)}%</td>
        <td>${chips(s.leaders)}</td>
        <td>${chips(s.laggards)}</td>
      </tr>`
      )
      .join("");
  }

  $("#mk-sectors").addEventListener("click", async (e) => {
    const chip = e.target.closest(".chip");
    if (chip && chip.title) { $("#add-code").value = chip.title; $("#add-code").focus(); return; }
    const tr = e.target.closest("tr.sector-row");
    if (!tr) return;
    const name = tr.dataset.sector;
    const next = tr.nextElementSibling;
    if (next && next.classList.contains("sector-stocks")) { next.remove(); return; }
    try {
      const rows = await api(`/api/market/sectors/${encodeURIComponent(name)}/stocks?date=${mk.date}`);
      const row = document.createElement("tr");
      row.className = "sector-stocks";
      row.innerHTML = `<td colspan="10"><div class="stock-chips">${rows
        .map((r) => `<span class="chip ${fmt.cls(r.pct)}" title="${r.code}">${r.code} ${fmt.esc(r.name || "")} ${r.pct === null ? "" : fmt.signed(r.pct, 2) + "%"} <span class="muted">${yi(r.turnover)}</span></span>`)
        .join("")}</div></td>`;
      tr.after(row);
    } catch (err) {
      toast(err.message, true);
    }
  });

  function renderMovers(b) {
    const li = (r, extra) => `<li><span class="n"><b>${r.code}</b> ${fmt.esc(r.name || "")} <span class="sec">${fmt.esc(r.sector)}</span></span><span class="${fmt.cls(r.pct)}">${fmt.signed(r.pct, 2)}%</span>${extra ? `<span class="muted">${extra(r)}</span>` : ""}</li>`;
    $("#mk-gainers").innerHTML = b.top_gainers.map((r) => li(r, (x) => yi(x.turnover))).join("");
    $("#mk-losers").innerHTML = b.top_losers.map((r) => li(r, (x) => yi(x.turnover))).join("");
    $("#mk-turnover").innerHTML = b.turnover_leaders.map((r) => li(r, (x) => `${yi(x.turnover)} (${x.share}%)`)).join("");
  }

  $("#mk-date").addEventListener("change", (e) => { mk.date = e.target.value; loadMarket(); });
  $("#mk-prev").addEventListener("click", () => { const i = mk.dates.indexOf(mk.date); if (i < mk.dates.length - 1) { mk.date = mk.dates[i + 1]; loadMarket(); } });
  $("#mk-next").addEventListener("click", () => { const i = mk.dates.indexOf(mk.date); if (i > 0) { mk.date = mk.dates[i - 1]; loadMarket(); } });
  $("#btn-market-update").addEventListener("click", async () => {
    try { await api("/api/jobs/market_daily/run", { method: "POST" }); toast("全市場更新已開始，約 10 秒"); setTimeout(() => { mk.date = null; loadMarket(); loadRuns(); }, 10000); } catch (err) { toast(err.message, true); }
  });
  $("#btn-market-backfill").addEventListener("click", async () => {
    try { await api("/api/jobs/market_backfill/run", { method: "POST" }); toast("回補 20 日已在背景開始，約 1–2 分鐘"); setTimeout(() => { loadMarket(); loadRuns(); }, 90000); } catch (err) { toast(err.message, true); }
  });

  // ------------------------------------------------------------------ boot
  async function boot() {
    await Promise.all([loadStatus(), loadRuleTypes(), loadWatchlist(), loadEvents(), loadRuns(), loadMarket()]);
    if (state.watchlist.length && !state.selected) selectStock(state.watchlist[0].code);
    setInterval(loadWatchlist, 15000);
    setInterval(loadStatus, 30000);
    setInterval(loadEvents, 30000);
    setInterval(loadRuns, 60000);
  }
  boot().catch((e) => toast(e.message, true));
})();
