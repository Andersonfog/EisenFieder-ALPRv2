"""SQLAlchemy engine/session setup.

Works with both SQLite (local dev default) and PostgreSQL (production) purely by
changing DATABASE_URL.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

# SQLite needs check_same_thread=False to be used across FastAPI's threadpool.
_is_sqlite = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _tune_sqlite(dbapi_conn, _record) -> None:
        """Per-connection SQLite tuning.

        WAL journal mode is the big one: camera ingest (writes) and console
        queries (reads) stop blocking each other. synchronous=NORMAL is safe
        with WAL and skips an fsync per commit; busy_timeout retries briefly
        instead of throwing "database is locked" under concurrent load.
        """
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA cache_size=-8192")   # 8 MB page cache
        cur.execute("PRAGMA temp_store=MEMORY")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a request-scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_columns() -> None:
    """Add columns introduced after a DB was first created (idempotent).

    ``Base.metadata.create_all`` only creates missing *tables*, not new columns,
    so we patch existing databases here. Keep entries simple/additive.
    """
    from sqlalchemy import inspect, text

    additions = {
        "cameras": [("api_token", "VARCHAR(128)"), ("settings", "JSON")],
        "vehicle_events": [("vehicle_model", "VARCHAR(64)"),
                           ("pending", "BOOLEAN DEFAULT 0"),
                           ("profile_image_key", "VARCHAR(512)")],
    }
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, cols in additions.items():
            if table not in existing_tables:
                continue
            present = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in cols:
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        # Composite index for the hottest query shape: "this camera's events,
        # newest first". Works on both SQLite and PostgreSQL; no-op if present.
        if "vehicle_events" in existing_tables:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_events_camera_captured "
                "ON vehicle_events (camera_id, captured_at)"
            ))
