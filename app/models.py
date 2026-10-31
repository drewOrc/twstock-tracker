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


class User(Base):
    """Local account. role: admin (runs jobs, manages users, approves shared-layer proposals) | member."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="member")  # admin | member
    line_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # per-user LINE push target
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UserSession(Base):
    """Server-side session; the cookie holds only the random token so sessions can be revoked."""

    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)

    user: Mapped[User] = relationship(lazy="joined")


class Stock(Base):
    """Master list of listed (TWSE) and OTC (TPEx) securities."""

    __tablename__ = "stocks"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    market: Mapped[str] = mapped_column(String(8), default="TWSE")  # TWSE | TPEX
    industry: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # company profile (from the exchanges' 公司基本資料; ETFs have none)
    full_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name_en: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chairman: Mapped[str | None] = mapped_column(String(64), nullable=True)
    general_manager: Mapped[str | None] = mapped_column(String(64), nullable=True)
    founded: Mapped[str | None] = mapped_column(String(10), nullable=True)  # YYYY-MM-DD
    listed_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    capital: Mapped[float | None] = mapped_column(Float, nullable=True)  # 實收資本額 NTD
    shares_issued: Mapped[int | None] = mapped_column(Integer, nullable=True)
    website: Mapped[str | None] = mapped_column(String(256), nullable=True)
    address: Mapped[str | None] = mapped_column(String(256), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class Watchlist(Base):
    """A named pool of stocks. A stock can sit in several lists; data subscription (backfill,
    realtime polling, flows, alert evaluation) is computed over the union of all lists.
    System lists (system_key set) are maintained automatically and cannot be edited by hand."""

    __tablename__ = "watchlists"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_watchlist_user_name"),
        UniqueConstraint("user_id", "system_key", name="uq_watchlist_user_system"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    system_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "code", name="uq_watchlist_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[int] = mapped_column(Integer, ForeignKey("watchlists.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(12), ForeignKey("stocks.code"), index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    stock: Mapped[Stock] = relationship(lazy="joined")
    watchlist: Mapped[Watchlist] = relationship(lazy="joined")


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
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
    code: Mapped[str] = mapped_column(String(12), index=True)
    rule_type: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    one_shot: Mapped[bool] = mapped_column(Boolean, default=False)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=60)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # provenance: None = created by the user; "crm_target" / "crm_stop" = mirrored from a CRM card
    source: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)  # e.g. CRM position id
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
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


# ------------------------------------------------------------------ shared knowledge layer
# These tables live in the shared market.db next to the CRM's personal_* tables. The engine is their
# only writer; the CRM reads them directly and sends changes through /api/market/knowledge/*.
# Column names mirror the CRM's former companies / edges / company_briefs / financials_ytd / metrics
# tables so the CRM's reads only had to change table names.


class SchemaRegistry(Base):
    """Who writes which table in the shared file. Both sides upsert rows for their own tables."""

    __tablename__ = "schema_registry"

    table_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    layer: Mapped[str] = mapped_column(String(16))  # knowledge | personal | auth | ops
    owner: Mapped[str] = mapped_column(String(16))  # engine | crm
    writer: Mapped[str] = mapped_column(String(64))  # process allowed to write
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class Company(Base):
    """Graph node. id is MARKET:TICKER ("TW:2330", "US:NVDA"); TW ids map onto `stocks.code`."""

    __tablename__ = "knowledge_companies"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    market: Mapped[str] = mapped_column(String(8))  # TW | US
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(128))
    name_en: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(256), nullable=True)
    confidence: Mapped[str] = mapped_column(String(8), default="medium")  # high | medium | low
    created_by: Mapped[str] = mapped_column(String(64), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class Edge(Base):
    """Directed relation. customer buys from supplier; revenue_share = share of the SUPPLIER's revenue
    that comes from the CUSTOMER (0..1). relation: customer | partner | holding (fund constituent)."""

    __tablename__ = "knowledge_edges"
    __table_args__ = (UniqueConstraint("customer_id", "supplier_id", name="uq_edge_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String(24), ForeignKey("knowledge_companies.id"), index=True)
    supplier_id: Mapped[str] = mapped_column(String(24), ForeignKey("knowledge_companies.id"), index=True)
    revenue_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    lag_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[str] = mapped_column(String(8), default="medium")
    relation: Mapped[str] = mapped_column(String(16), default="customer")
    source: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class EdgeWeight(Base):
    """History of an edge's revenue_share; the edge row keeps the latest value for quick reads."""

    __tablename__ = "knowledge_edge_weights"
    __table_args__ = (UniqueConstraint("edge_id", "date", name="uq_edge_weight_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    edge_id: Mapped[int] = mapped_column(Integer, ForeignKey("knowledge_edges.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    revenue_share: Mapped[float] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class CompanyBrief(Base):
    """Prose about a company. Append-only: latest row per kind wins.
    kind: profile (what it does, stable) | highlights (recent developments, dated)."""

    __tablename__ = "knowledge_company_briefs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(24), ForeignKey("knowledge_companies.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[list | None] = mapped_column(JSON, default=list)  # [{title, url, date}]
    created_by: Mapped[str] = mapped_column(String(64), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class FinancialYTD(Base):
    """Year-to-date quarterly income statement figures (open data publishes YTD). Thousands of TWD."""

    __tablename__ = "knowledge_financials_ytd"
    __table_args__ = (UniqueConstraint("company_id", "year", "quarter", name="uq_fin_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(24), ForeignKey("knowledge_companies.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    quarter: Mapped[int] = mapped_column(Integer)
    revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    opex: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_income: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(512), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class MetricActual(Base):
    """Observed standard metrics (revenue_m, revenue_q, gross_margin, opex, eps, shares) per period.
    Model values are a personal matter and stay in the CRM's personal tables."""

    __tablename__ = "knowledge_metrics"
    __table_args__ = (UniqueConstraint("company_id", "metric", "period", name="uq_metric_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(24), ForeignKey("knowledge_companies.id"), index=True)
    metric: Mapped[str] = mapped_column(String(16))
    period: Mapped[str] = mapped_column(String(10))  # 2026 | 2026Q2 | 2026-05
    value: Mapped[float] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
