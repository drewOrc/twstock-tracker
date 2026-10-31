import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import BASE_DIR, settings

log = logging.getLogger(__name__)
(BASE_DIR / "data").mkdir(exist_ok=True)


def sqlite_path(url: str) -> Path | None:
    if url.startswith("sqlite:///") and not url.endswith(":memory:"):
        return Path(url[len("sqlite:///"):])
    return None


def adopt_legacy_database(target: Path | None, legacy: Path) -> bool:
    """First start after the move to the shared file: copy the engine's old per-project database
    into market.db (SQLite online backup, safe with WAL) so nothing has to be re-fetched. The old
    file is left in place with a note; only a brand-new market.db is ever written to."""
    if target is None or target.name != "market.db" or target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    if not legacy.exists() or legacy.resolve() == target.resolve():
        return False
    src = sqlite3.connect(legacy)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    (legacy.parent / "MOVED_TO_market.db.txt").write_text(
        f"{datetime.now():%Y-%m-%d %H:%M} copied {legacy.name} -> {target}\n"
        "The engine now uses the shared database; this file is only a backup.\n",
        encoding="utf-8",
    )
    log.warning("adopted legacy database %s -> %s", legacy, target)
    return True


_is_sqlite = settings.database_url.startswith("sqlite")
if _is_sqlite and (_p := sqlite_path(settings.database_url)) is not None:
    _p.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    future=True,
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    if _is_sqlite:
        adopt_legacy_database(sqlite_path(settings.database_url), settings.legacy_database)
    _prepare_multiuser_migration()  # rename pre-user tables so create_all builds the new shape
    Base.metadata.create_all(engine)
    _add_missing_columns()
    admin_id = _bootstrap_admin_id()
    _migrate_single_watchlist(admin_id)
    _finish_multiuser_migration(admin_id)
    _register_schema()


# Who writes which table in the shared file. The CRM registers its own personal_* rows the same way.
ENGINE_TABLES: dict[str, tuple[str, str]] = {
    "users": ("auth", "local accounts; the CRM reads id/username/display_name/role, never password_hash"),
    "sessions": ("auth", "login sessions"),
    "schema_registry": ("ops", "this table; each side upserts rows for the tables it owns"),
    "stocks": ("knowledge", "TWSE/TPEx master list (code without market prefix)"),
    "daily_prices": ("knowledge", "daily OHLCV"),
    "institutional_flows": ("knowledge", "三大法人"),
    "margin_balances": ("knowledge", "融資融券"),
    "market_stats": ("knowledge", "breadth / sector stats"),
    "index_daily": ("knowledge", "index closes"),
    "screener_results": ("knowledge", "screener output per day"),
    "realtime_quotes": ("knowledge", "intraday quotes"),
    "knowledge_companies": ("knowledge", "graph nodes MARKET:TICKER; CRM reads, writes via PUT /api/market/knowledge/companies/{id}"),
    "knowledge_edges": ("knowledge", "customer -> supplier relations; writes via /api/market/knowledge/edges"),
    "knowledge_edge_weights": ("knowledge", "revenue_share history per edge"),
    "knowledge_company_briefs": ("knowledge", "profile / highlights prose, append-only"),
    "knowledge_financials_ytd": ("knowledge", "quarterly YTD figures from open data"),
    "knowledge_metrics": ("knowledge", "actual metrics (model values are personal, CRM-owned)"),
    "watchlists": ("personal", "per-user lists (user_id)"),
    "watchlist_items": ("personal", "list membership"),
    "alert_rules": ("personal", "per-user alert rules"),
    "alert_events": ("personal", "fired alerts"),
    "job_runs": ("ops", "engine job history"),
}


def _register_schema() -> None:
    from .models import SchemaRegistry

    with SessionLocal() as db:
        for name, (layer, note) in ENGINE_TABLES.items():
            db.merge(SchemaRegistry(table_name=name, layer=layer, owner="engine", writer="twstock-tracker", note=note))
        db.commit()


def _bootstrap_admin_id() -> int:
    from .services.auth import ensure_admin

    with SessionLocal() as db:
        return ensure_admin(db).id


DEFAULT_LIST_NAME = "我的追蹤"
LEGACY_ADMIN_USERNAME = "admin"


def _columns(table: str) -> set[str]:
    from sqlalchemy import inspect

    insp = inspect(engine)
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _prepare_multiuser_migration() -> None:
    """v0.3 watchlists had no user_id and a global UNIQUE(name). SQLite cannot change constraints,
    so park the old table; create_all then builds the per-user version and _finish copies rows."""
    cols = _columns("watchlists")
    if cols and "user_id" not in cols:
        # legacy_alter_table keeps watchlist_items' FK text pointing at "watchlists" (the table
        # create_all is about to rebuild) instead of rewriting it to the parked copy; foreign_keys
        # off so nothing cascades while the parent is temporarily missing.
        _raw_exec("PRAGMA foreign_keys=OFF", "PRAGMA legacy_alter_table=ON", "ALTER TABLE watchlists RENAME TO watchlists_v1")


def _raw_exec(*statements: str) -> None:
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        for s in statements:
            cur.execute(s)
        raw.commit()
    finally:
        raw.close()


def _finish_multiuser_migration(admin_id: int) -> None:
    """Attach every pre-existing personal row to the bootstrap admin."""
    from sqlalchemy import text

    with engine.begin() as conn:
        if _columns("watchlists_v1"):
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO watchlists (id, user_id, name, color, sort_order, system_key, created_at) "
                    "SELECT id, :uid, name, color, COALESCE(sort_order, 0), system_key, COALESCE(created_at, CURRENT_TIMESTAMP) FROM watchlists_v1"
                ),
                {"uid": admin_id},
            )
        for table in ("alert_rules", "alert_events"):
            if "user_id" in _columns(table):
                conn.execute(text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"), {"uid": admin_id})
    if _columns("watchlists_v1"):
        _raw_exec("PRAGMA foreign_keys=OFF", "DROP TABLE watchlists_v1")
    _repair_watchlist_items_fk()


def _repair_watchlist_items_fk() -> None:
    """A database migrated by an earlier build had watchlist_items' FK rewritten to point at the
    parked watchlists_v1 table (SQLite RENAME side effect). Rebuild the table against `watchlists`."""
    from sqlalchemy import inspect, text

    # Resumable: a previous run may have parked the table already.
    if "watchlist_items_old" not in inspect(engine).get_table_names():
        with engine.connect() as conn:
            sql = conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='watchlist_items'")).scalar()
        if not sql or "watchlists_v1" not in sql:
            return
        _raw_exec("PRAGMA foreign_keys=OFF", "PRAGMA legacy_alter_table=ON", "ALTER TABLE watchlist_items RENAME TO watchlist_items_old")
    # the parked table still owns the index names the new table wants
    _raw_exec("DROP INDEX IF EXISTS ix_watchlist_items_code", "DROP INDEX IF EXISTS ix_watchlist_items_watchlist_id")
    Base.metadata.tables["watchlist_items"].create(engine, checkfirst=True)
    _raw_exec(
        "PRAGMA foreign_keys=OFF",
        "INSERT OR IGNORE INTO watchlist_items (id, watchlist_id, code, note, added_at) "
        "SELECT id, watchlist_id, code, note, COALESCE(added_at, CURRENT_TIMESTAMP) FROM watchlist_items_old "
        "WHERE watchlist_id IN (SELECT id FROM watchlists)",
        "DROP TABLE watchlist_items_old",
    )


def _add_missing_columns() -> None:
    """create_all never alters existing tables; add columns that newer models declare (SQLite
    supports ADD COLUMN for nullable columns, which is all we ever add)."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                coltype = col.type.compile(engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'))


def _migrate_single_watchlist(admin_id: int) -> None:
    """v0.1 had one global `watchlist` table (code UNIQUE). Move its rows into the admin's default
    list in the new `watchlists` / `watchlist_items` tables, then drop the old table. Idempotent."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "watchlist" not in insp.get_table_names():
        return
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT id FROM watchlists WHERE user_id = :uid AND system_key IS NULL ORDER BY sort_order, id LIMIT 1"), {"uid": admin_id}
        ).first()
        if row:
            list_id = row[0]
        else:
            conn.execute(
                text("INSERT INTO watchlists (user_id, name, color, sort_order, created_at) VALUES (:uid, :n, :c, 0, CURRENT_TIMESTAMP)"),
                {"uid": admin_id, "n": DEFAULT_LIST_NAME, "c": "#4f8cff"},
            )
            list_id = conn.execute(text("SELECT id FROM watchlists WHERE user_id = :uid AND name = :n"), {"uid": admin_id, "n": DEFAULT_LIST_NAME}).scalar()
        conn.execute(
            text(
                "INSERT OR IGNORE INTO watchlist_items (watchlist_id, code, note, added_at) "
                "SELECT :lid, code, note, COALESCE(added_at, CURRENT_TIMESTAMP) FROM watchlist"
            ),
            {"lid": list_id},
        )
        conn.execute(text("DROP TABLE watchlist"))


def get_db():
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
