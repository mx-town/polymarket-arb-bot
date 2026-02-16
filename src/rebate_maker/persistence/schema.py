"""SQLAlchemy Core table definitions for persistence.

All timestamps are Unix epoch floats — works identically in SQLite and PostgreSQL.
"""

from sqlalchemy import (
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

metadata = MetaData()

trades = Table(
    "trades",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", Float, nullable=False),
    Column("market_slug", String(120)),
    Column("event_type", String(30), nullable=False),
    Column("direction", String(10)),
    Column("side", String(10)),
    Column("price", Float),
    Column("shares", Float),
    Column("reason", String(50)),
    Column("btc_price_at", Float),
    Column("order_id", String(80)),
    Column("tx_hash", String(80)),
    Column("session_id", String(50)),
    Column("strategy", String(20)),
    Index("ix_trades_ts", "ts"),
    Index("ix_trades_slug", "market_slug"),
)

pnl_snapshots = Table(
    "pnl_snapshots",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", Float, nullable=False),
    Column("realized", Float),
    Column("unrealized", Float),
    Column("total", Float),
    Column("exposure", Float),
    Column("exposure_pct", Float),
    Column("gas_spent", Float),
    Column("session_id", String(50)),
    Index("ix_pnl_ts", "ts"),
)

market_windows = Table(
    "market_windows",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("slug", String(120), unique=True, nullable=False),
    Column("market_type", String(30)),
    Column("end_time", Float),
    Column("up_token_id", String(120)),
    Column("down_token_id", String(120)),
    Column("entered_at", Float),
    Column("exited_at", Float),
    Column("outcome", String(30)),
    Column("total_pnl", Float),
    Column("session_id", String(50)),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", String(50), primary_key=True),
    Column("started_at", Float),
    Column("ended_at", Float),
    Column("mode", String(10)),
    Column("config_snapshot", Text),
    Column("user_id", String(50)),
)
