"""Database engine initialization — SQLite WAL mode (MVP), PostgreSQL-ready.

Usage:
    engine = init_db()           # creates tables, returns engine
    engine = init_db("postgresql://...")  # swap for production
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine as SAEngine

from complete_set.persistence.schema import metadata

log = logging.getLogger("cs.persistence")

_engine: SAEngine | None = None

DEFAULT_DB_PATH = "data/bot.db"


def _set_sqlite_wal(dbapi_conn, connection_record):
    """Enable WAL mode for concurrent reads during batch writes."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def init_db(url: str | None = None) -> SAEngine:
    """Initialize the database engine and create tables if needed."""
    global _engine

    if url is None:
        db_path = Path(DEFAULT_DB_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{db_path}"

    _engine = create_engine(url, pool_pre_ping=True)

    if url.startswith("sqlite"):
        event.listen(_engine, "connect", _set_sqlite_wal)

    metadata.create_all(_engine)
    _ensure_columns(_engine)
    log.info("DB │ initialized at %s", url)
    return _engine


# New columns added after initial schema — ALTER TABLE for existing databases.
_MIGRATIONS: list[tuple[str, str, str]] = [
    ("trades", "session_id", "VARCHAR(50)"),
    ("trades", "strategy", "VARCHAR(20)"),
    ("btc_prices", "session_id", "VARCHAR(50)"),
    ("probability_snapshots", "session_id", "VARCHAR(50)"),
    ("market_windows", "session_id", "VARCHAR(50)"),
]


def _ensure_columns(engine: SAEngine) -> None:
    """Add columns that may be missing from existing databases."""
    insp = inspect(engine)
    added = 0
    for table_name, col_name, col_type in _MIGRATIONS:
        existing = {c["name"] for c in insp.get_columns(table_name)}
        if col_name not in existing:
            with engine.begin() as conn:
                conn.execute(text(
                    f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"
                ))
            added += 1
    if added:
        log.info("DB │ migrated %d new columns", added)


def get_engine() -> SAEngine:
    """Return the active database engine. Raises if not initialized."""
    if _engine is None:
        raise RuntimeError("Database not initialized — call init_db() first")
    return _engine


def cleanup_old_data(retention_days: int = 30) -> int:
    """Delete time-series rows older than retention_days. Returns total deleted."""
    import time
    from complete_set.persistence.schema import btc_prices, probability_snapshots

    engine = get_engine()
    cutoff = time.time() - (retention_days * 86400)
    total = 0

    with engine.begin() as conn:
        for table in (btc_prices, probability_snapshots):
            result = conn.execute(
                table.delete().where(table.c.ts < cutoff)
            )
            total += result.rowcount

    if total > 0:
        log.info("DB │ cleaned up %d rows older than %d days", total, retention_days)
    return total
