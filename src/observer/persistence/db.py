"""Database engine initialization — SQLite WAL mode, separate from CS bot.

Usage:
    engine = init_db()           # creates tables at data/observer.db
    engine = init_db("sqlite:///custom.db")
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine as SAEngine

from observer.persistence.schema import metadata

log = logging.getLogger("obs.persistence")

_engine: SAEngine | None = None

DEFAULT_DB_PATH = "data/observer.db"


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
    log.info("DB │ initialized at %s", url)
    return _engine


def get_engine() -> SAEngine:
    """Return the active database engine. Raises if not initialized."""
    if _engine is None:
        raise RuntimeError("Database not initialized — call init_db() first")
    return _engine
