"""Alert rule engine.

Two evaluation passes:
  * evaluate_intraday(db, quotes) - runs on every realtime poll (price / % change rules)
  * evaluate_daily(db)            - runs after the daily data jobs (indicator / flow rules; price rules as fallback)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AlertEvent, AlertRule, Stock
from . import market_data as md
from .indicators import compute_all
from .notifier import notifier

log = logging.getLogger(__name__)

INTRADAY = "intraday"
DAILY = "daily"

# rule_type -> definition (used for validation, defaults and the UI form)
RULE_TYPES: dict[str, dict] = {
    "price_above": {
        "label": "價格突破",
        "scope": INTRADAY,
        "params": [{"name": "price", "label": "價格", "type": "number"}],
    },
    "price_below": {
        "label": "價格跌破",
        "scope": INTRADAY,
        "params": [{"name": "price", "label": "價格", "type": "number"}],
    },
    "pct_change_above": {
        "label": "漲幅超過 (%)",
        "scope": INTRADAY,
        "params": [{"name": "pct", "label": "漲幅 %", "type": "number", "default": 5}],
    },
    "pct_change_below": {
        "label": "跌幅超過 (%)",
        "scope": INTRADAY,
        "params": [{"name": "pct", "label": "跌幅 % (正數)", "type": "number", "default": 5}],
    },
    "ma_cross": {
        "label": "均線交叉",
        "scope": DAILY,
        "params": [
            {"name": "fast", "label": "短均線", "type": "int", "default": 5},
            {"name": "slow", "label": "長均線", "type": "int", "default": 20},
            {"name": "direction", "label": "方向", "type": "select", "options": ["golden", "death"], "default": "golden"},
        ],
    },
    "price_vs_ma": {
        "label": "收盤站上 / 跌破均線",
        "scope": DAILY,
        "params": [
            {"name": "period", "label": "均線週期", "type": "int", "default": 20},
            {"name": "direction", "label": "方向", "type": "select", "options": ["above", "below"], "default": "above"},
        ],
    },
    "rsi_above": {
        "label": "RSI 高於",
        "scope": DAILY,
        "params": [
            {"name": "period", "label": "週期", "type": "int", "default": 14},
            {"name": "value", "label": "門檻", "type": "number", "default": 70},
        ],
    },
    "rsi_below": {
        "label": "RSI 低於",
        "scope": DAILY,
        "params": [
            {"name": "period", "label": "週期", "type": "int", "default": 14},
            {"name": "value", "label": "門檻", "type": "number", "default": 30},
        ],
    },
    "kd_cross": {
        "label": "KD 交叉",
        "scope": DAILY,
        "params": [
            {"name": "direction", "label": "方向", "type": "select", "options": ["golden", "death"], "default": "golden"},
        ],
    },
    "volume_spike": {
        "label": "成交量爆量",
        "scope": DAILY,
        "params": [
            {"name": "multiplier", "label": "倍數 (vs 均量)", "type": "number", "default": 2},
            {"name": "window", "label": "均量天數", "type": "int", "default": 20},
        ],
    },
    "institutional_streak": {
        "label": "法人連續買 / 賣超",
        "scope": DAILY,
        "params": [
            {"name": "investor", "label": "法人", "type": "select", "options": ["foreign", "trust", "dealer", "total"], "default": "foreign"},
            {"name": "direction", "label": "方向", "type": "select", "options": ["buy", "sell"], "default": "buy"},
            {"name": "days", "label": "連續天數", "type": "int", "default": 3},
        ],
    },
    "margin_change": {
        "label": "融資餘額單日變動",
        "scope": DAILY,
        "params": [
            {"name": "direction", "label": "方向", "type": "select", "options": ["increase", "decrease"], "default": "increase"},
            {"name": "lots", "label": "變動張數門檻", "type": "int", "default": 1000},
        ],
    },
}

DEFAULT_COOLDOWN = {INTRADAY: 60, DAILY: 23 * 60}

INVESTOR_LABEL = {"foreign": "外資", "trust": "投信", "dealer": "自營商", "total": "三大法人"}
INVESTOR_FIELD = {"foreign": "foreign_net", "trust": "trust_net", "dealer": "dealer_net", "total": "total_net"}


def rule_scope(rule_type: str) -> str:
    return RULE_TYPES.get(rule_type, {}).get("scope", DAILY)


def normalise_params(rule_type: str, params: dict) -> dict:
    """Fill defaults and coerce numeric params. Raises ValueError on unknown type / missing required."""
    spec = RULE_TYPES.get(rule_type)
    if spec is None:
        raise ValueError(f"unknown rule_type: {rule_type}")
    out = dict(params or {})
    for p in spec["params"]:
        name = p["name"]
        if name not in out or out[name] in (None, ""):
            if "default" in p:
                out[name] = p["default"]
            else:
                raise ValueError(f"missing parameter: {name}")
        if p["type"] == "number":
            out[name] = float(out[name])
        elif p["type"] == "int":
            out[name] = int(out[name])
        elif p["type"] == "select" and out[name] not in p["options"]:
            raise ValueError(f"invalid value for {name}: {out[name]}")
    return out


# ---------------------------------------------------------------------- firing
def _ready(rule: AlertRule, now: datetime) -> bool:
    if not rule.enabled:
        return False
    if rule.last_triggered_at is None:
        return True
    return now - rule.last_triggered_at >= timedelta(minutes=rule.cooldown_minutes or 0)


def _label(db: Session, code: str) -> str:
    stock = db.get(Stock, code)
    return f"{code} {stock.name}" if stock and stock.name else code


def fire(db: Session, rule: AlertRule, message: str, value: float | None, now: datetime) -> AlertEvent:
    title = f"【{_label(db, rule.code)}】{RULE_TYPES.get(rule.rule_type, {}).get('label', rule.rule_type)}"
    delivery = notifier.send(title, message)
    event = AlertEvent(
        rule_id=rule.id,
        code=rule.code,
        rule_type=rule.rule_type,
        message=f"{title} {message}",
        value=value,
        triggered_at=now,
        delivery=delivery,
    )
    rule.last_triggered_at = now
    if rule.one_shot:
        rule.enabled = False
    db.add(event)
    db.commit()
    log.info("ALERT %s", event.message)
    return event


# ---------------------------------------------------------------------- intraday
def _check_price_rule(rule: AlertRule, price: float | None, pct: float | None) -> tuple[bool, str, float | None]:
    p = rule.params or {}
    t = rule.rule_type
    if t == "price_above" and price is not None:
        return price >= p["price"], f"現價 {price:g} 已突破 {p['price']:g}", price
    if t == "price_below" and price is not None:
        return price <= p["price"], f"現價 {price:g} 已跌破 {p['price']:g}", price
    if t == "pct_change_above" and pct is not None:
        return pct >= p["pct"], f"漲幅 {pct:+.2f}% 超過 {p['pct']:g}%", pct
    if t == "pct_change_below" and pct is not None:
        return pct <= -abs(p["pct"]), f"跌幅 {pct:+.2f}% 超過 {p['pct']:g}%", pct
    return False, "", None


def evaluate_intraday(db: Session, quotes: list[dict]) -> list[AlertEvent]:
    now = datetime.now()
    by_code = {q["code"]: q for q in quotes}
    if not by_code:
        return []
    rules = db.execute(
        select(AlertRule).where(AlertRule.enabled.is_(True), AlertRule.code.in_(by_code.keys()))
    ).scalars()
    events = []
    for rule in rules:
        if rule_scope(rule.rule_type) != INTRADAY or not _ready(rule, now):
            continue
        q = by_code[rule.code]
        hit, msg, value = _check_price_rule(rule, q.get("price"), q.get("change_pct"))
        if hit:
            events.append(fire(db, rule, msg, value, now))
    return events


# ---------------------------------------------------------------------- daily
def _check_daily_rule(db: Session, rule: AlertRule, cache: dict) -> tuple[bool, str, float | None]:
    p = rule.params or {}
    t = rule.rule_type
    code = rule.code

    if t in ("price_above", "price_below", "pct_change_above", "pct_change_below"):
        df = cache.setdefault(("df", code), md.load_daily_df(db, code, 300))
        if len(df) < 2:
            return False, "", None
        close = float(df["close"].iloc[-1])
        prev = float(df["close"].iloc[-2])
        pct = round((close - prev) / prev * 100, 2) if prev else None
        hit, msg, value = _check_price_rule(rule, close, pct)
        return hit, msg.replace("現價", "收盤"), value

    if t in ("ma_cross", "price_vs_ma", "rsi_above", "rsi_below", "kd_cross", "volume_spike"):
        df = cache.setdefault(("df", code), md.load_daily_df(db, code, 300))
        if len(df) < 3:
            return False, "", None
        ind = cache.setdefault(("ind", code), compute_all(df))
        last, prev = ind.iloc[-1], ind.iloc[-2]
        day = str(last["date"])

        if t == "ma_cross":
            fast, slow = p["fast"], p["slow"]
            f_now, s_now = _ma(ind, fast, -1), _ma(ind, slow, -1)
            f_prev, s_prev = _ma(ind, fast, -2), _ma(ind, slow, -2)
            if None in (f_now, s_now, f_prev, s_prev):
                return False, "", None
            if p["direction"] == "golden":
                hit = f_prev <= s_prev and f_now > s_now
                return hit, f"{day} MA{fast} ({f_now:.2f}) 黃金交叉 MA{slow} ({s_now:.2f})", f_now
            hit = f_prev >= s_prev and f_now < s_now
            return hit, f"{day} MA{fast} ({f_now:.2f}) 死亡交叉 MA{slow} ({s_now:.2f})", f_now

        if t == "price_vs_ma":
            n = p["period"]
            ma_now, ma_prev = _ma(ind, n, -1), _ma(ind, n, -2)
            if ma_now is None or ma_prev is None:
                return False, "", None
            c_now, c_prev = float(last["close"]), float(prev["close"])
            if p["direction"] == "above":
                hit = c_prev <= ma_prev and c_now > ma_now
                return hit, f"{day} 收盤 {c_now:g} 站上 MA{n} ({ma_now:.2f})", c_now
            hit = c_prev >= ma_prev and c_now < ma_now
            return hit, f"{day} 收盤 {c_now:g} 跌破 MA{n} ({ma_now:.2f})", c_now

        if t in ("rsi_above", "rsi_below"):
            from .indicators import rsi as _rsi

            series = _rsi(df["close"].astype(float), p["period"])
            v = series.iloc[-1]
            if v != v:  # NaN
                return False, "", None
            v = float(v)
            if t == "rsi_above":
                return v >= p["value"], f"{day} RSI{p['period']} = {v:.1f} 高於 {p['value']:g}", v
            return v <= p["value"], f"{day} RSI{p['period']} = {v:.1f} 低於 {p['value']:g}", v

        if t == "kd_cross":
            k_now, d_now, k_prev, d_prev = (float(last["k"]), float(last["d"]), float(prev["k"]), float(prev["d"]))
            if p["direction"] == "golden":
                hit = k_prev <= d_prev and k_now > d_now
                return hit, f"{day} K ({k_now:.1f}) 黃金交叉 D ({d_now:.1f})", k_now
            hit = k_prev >= d_prev and k_now < d_now
            return hit, f"{day} K ({k_now:.1f}) 死亡交叉 D ({d_now:.1f})", k_now

        if t == "volume_spike":
            window = p["window"]
            vols = df["volume"].astype(float)
            if len(vols) <= window:
                return False, "", None
            avg = vols.iloc[-window - 1 : -1].mean()
            v = float(vols.iloc[-1])
            ratio = v / avg if avg else 0
            return ratio >= p["multiplier"], f"{day} 成交量 {v / 1000:,.0f} 張，為 {window} 日均量的 {ratio:.1f} 倍", ratio

    if t == "institutional_streak":
        rows = cache.setdefault(("inst", code), md.load_institutional(db, code, 60))
        days = p["days"]
        if len(rows) < days:
            return False, "", None
        field = INVESTOR_FIELD[p["investor"]]
        recent = rows[:days]  # newest first
        vals = [getattr(r, field) for r in recent]
        if any(v is None for v in vals):
            return False, "", None
        if p["direction"] == "buy":
            hit = all(v > 0 for v in vals)
            word = "買超"
        else:
            hit = all(v < 0 for v in vals)
            word = "賣超"
        total = sum(vals) / 1000
        return hit, f"{INVESTOR_LABEL[p['investor']]} 連續 {days} 日{word}，合計 {total:+,.0f} 張 (至 {recent[0].date})", total

    if t == "margin_change":
        rows = cache.setdefault(("margin", code), md.load_margin(db, code, 5))
        if not rows or rows[0].margin_balance is None or rows[0].margin_prev is None:
            return False, "", None
        r = rows[0]
        delta = r.margin_balance - r.margin_prev
        if p["direction"] == "increase":
            return delta >= p["lots"], f"{r.date} 融資增加 {delta:+,} 張 (餘額 {r.margin_balance:,})", delta
        return delta <= -p["lots"], f"{r.date} 融資減少 {delta:+,} 張 (餘額 {r.margin_balance:,})", delta

    return False, "", None


def _ma(ind, n: int, idx: int) -> float | None:
    col = f"ma{n}"
    if col not in ind.columns:
        from .indicators import sma

        ind[col] = sma(ind["close"].astype(float), n)
    v = ind[col].iloc[idx]
    return None if v != v else float(v)


def evaluate_daily(db: Session, codes: set[str] | None = None) -> list[AlertEvent]:
    now = datetime.now()
    stmt = select(AlertRule).where(AlertRule.enabled.is_(True))
    if codes:
        stmt = stmt.where(AlertRule.code.in_(codes))
    rules = list(db.execute(stmt).scalars())
    cache: dict = {}
    events = []
    for rule in rules:
        if not _ready(rule, now):
            continue
        # intraday price rules are also checked on close so they work without the realtime poller
        try:
            hit, msg, value = _check_daily_rule(db, rule, cache)
        except Exception as exc:  # noqa: BLE001
            log.warning("rule %s (%s) evaluation failed: %s", rule.id, rule.rule_type, exc)
            continue
        if hit:
            events.append(fire(db, rule, msg, value, now))
    return events


def recent_events(db: Session, limit: int = 100, code: str | None = None) -> list[AlertEvent]:
    stmt = select(AlertEvent).order_by(AlertEvent.triggered_at.desc()).limit(limit)
    if code:
        stmt = stmt.where(AlertEvent.code == code)
    return list(db.execute(stmt).scalars())
