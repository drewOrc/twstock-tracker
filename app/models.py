from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Stock(Base):
    """Master list of listed (TWSE) and OTC (TPEx) securities."""

    __tablename__ = "stocks"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    market: Mapped[str] = mapped_column(String(8), default="TWSE")  # TWSE | TPEX
    industry: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class WatchlistItem(Base):
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(12), ForeignKey("stocks.code"), unique=True, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[str | None] = mapped_column(String(128), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    stock: Mapped[Stock] = relationship(lazy="joined")


class DailyPrice(Base):
    __tablename__ = "daily_prices"
    __table_args__ = (UniqueConstraint("code", "date", name="uq_daily_code_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(12), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(Integer)  # shares
    turnover: Mapped[float | None] = mapped_column(Float)  # NTD
    transactions: Mapped[int | None] = mapped_column(Integer)
    change: Mapped[float | None] = mapped_column(Float)


class InstitutionalFlow(Base):
    """三大法人買賣超 (shares)."""

    __tablename__ = "institutional_flows"
    __table_args__ = (UniqueConstraint("code", "date", name="uq_inst_code_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(12), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    foreign_buy: Mapped[int | None] = mapped_column(Integer)
    foreign_sell: Mapped[int | None] = mapped_column(Integer)
    foreign_net: Mapped[int | None] = mapped_column(Integer)
    trust_buy: Mapped[int | None] = mapped_column(Integer)
    trust_sell: Mapped[int | None] = mapped_column(Integer)
    trust_net: Mapped[int | None] = mapped_column(Integer)
    dealer_net: Mapped[int | None] = mapped_column(Integer)
    total_net: Mapped[int | None] = mapped_column(Integer)


class MarginBalance(Base):
    """融資融券 (lots, 張)."""

    __tablename__ = "margin_balances"
    __table_args__ = (UniqueConstraint("code", "date", name="uq_margin_code_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(12), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    margin_buy: Mapped[int | None] = mapped_column(Integer)
    margin_sell: Mapped[int | None] = mapped_column(Integer)
    margin_redeem: Mapped[int | None] = mapped_column(Integer)
    margin_prev: Mapped[int | None] = mapped_column(Integer)
    margin_balance: Mapped[int | None] = mapped_column(Integer)
    margin_limit: Mapped[int | None] = mapped_column(Integer)
    short_buy: Mapped[int | None] = mapped_column(Integer)
    short_sell: Mapped[int | None] = mapped_column(Integer)
    short_redeem: Mapped[int | None] = mapped_column(Integer)
    short_prev: Mapped[int | None] = mapped_column(Integer)
    short_balance: Mapped[int | None] = mapped_column(Integer)
    short_limit: Mapped[int | None] = mapped_column(Integer)
    offset: Mapped[int | None] = mapped_column(Integer)  # 資券互抵


class MarketStat(Base):
    """Per-market daily breadth (common stocks). TWSE rows come from the official 漲跌證券數合計 table,
    TPEx rows are computed from individual quotes."""

    __tablename__ = "market_stats"
    __table_args__ = (UniqueConstraint("market", "date", name="uq_market_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(8), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    advance: Mapped[int | None] = mapped_column(Integer)
    decline: Mapped[int | None] = mapped_column(Integer)
    flat: Mapped[int | None] = mapped_column(Integer)
    limit_up: Mapped[int | None] = mapped_column(Integer)
    limit_down: Mapped[int | None] = mapped_column(Integer)
    total: Mapped[int | None] = mapped_column(Integer)
    turnover: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String(16))  # official | computed


class IndexDaily(Base):
    """Daily close / change% of TWSE price indices (加權指數 and every 類股指數)."""

    __tablename__ = "index_daily"
    __table_args__ = (UniqueConstraint("name", "date", name="uq_index_name_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[float | None] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float)


class ScreenerResult(Base):
    """Ranked output of the daily multi-factor screener, one row per (date, preset, code)."""

    __tablename__ = "screener_results"
    __table_args__ = (UniqueConstraint("date", "preset", "code", name="uq_screen_date_preset_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    preset: Mapped[str] = mapped_column(String(32), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(12), index=True)
    score: Mapped[float] = mapped_column(Float)
    factors: Mapped[dict] = mapped_column(JSON, default=dict)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class RealtimeQuote(Base):
    """Latest intraday snapshot per code (overwritten on each poll)."""

    __tablename__ = "realtime_quotes"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(64))
    market: Mapped[str | None] = mapped_column(String(8))
    price: Mapped[float | None] = mapped_column(Float)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    prev_close: Mapped[float | None] = mapped_column(Float)
    change: Mapped[float | None] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(Integer)  # accumulated lots (張)
    bid: Mapped[float | None] = mapped_column(Float)
    ask: Mapped[float | None] = mapped_column(Float)
    trade_date: Mapped[date | None] = mapped_column(Date)
    trade_time: Mapped[str | None] = mapped_column(String(8))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(12), index=True)
    rule_type: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    one_shot: Mapped[bool] = mapped_column(Boolean, default=False)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=60)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True)
    code: Mapped[str] = mapped_column(String(12), index=True)
    rule_type: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(Float)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    delivery: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {channel: ok/err}


class JobRun(Base):
    """History of scheduled / manual job executions."""

    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
