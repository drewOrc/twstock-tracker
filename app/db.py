from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import BASE_DIR, settings

(BASE_DIR / "data").mkdir(exist_ok=True)

_is_sqlite = settings.database_url.startswith("sqlite")
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

    Base.metadata.create_all(engine)
    _migrate_single_watchlist()


DEFAULT_LIST_NAME = "我的追蹤"


def _migrate_single_watchlist() -> None:
    """v0.1 had one global `watchlist` table (code UNIQUE). Move its rows into a default list in
    the new `watchlists` / `watchlist_items` tables, then drop the old table. Idempotent."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "watchlist" not in insp.get_table_names():
        return
    with engine.begin() as conn:
        row = conn.execute(text("SELECT id FROM watchlists WHERE system_key IS NULL ORDER BY sort_order, id LIMIT 1")).first()
        if row:
            list_id = row[0]
        else:
            conn.execute(
                text("INSERT INTO watchlists (name, color, sort_order, created_at) VALUES (:n, :c, 0, CURRENT_TIMESTAMP)"),
                {"n": DEFAULT_LIST_NAME, "c": "#4f8cff"},
            )
            list_id = conn.execute(text("SELECT id FROM watchlists WHERE name = :n"), {"n": DEFAULT_LIST_NAME}).scalar()
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
