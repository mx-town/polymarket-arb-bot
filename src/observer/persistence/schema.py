"""SQLAlchemy Core table definitions for observer persistence.

All timestamps are Unix epoch floats. Separate DB from CS (data/observer.db)
to avoid WAL contention when both bots run simultaneously.
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

obs_sessions = Table(
    "obs_sessions",
    metadata,
    Column("id", String(50), primary_key=True),
    Column("started_at", Float),
    Column("ended_at", Float),
    Column("proxy_address", String(50)),
    Column("config_snapshot", Text),
)

obs_trades = Table(
    "obs_trades",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", Float, nullable=False),
    Column("side", String(10)),
    Column("price", Float),
    Column("size", Float),
    Column("usdc_size", Float),
    Column("outcome", String(10)),
    Column("outcome_index", Integer),
    Column("tx_hash", String(80), unique=True),
    Column("slug", String(120)),
    Column("event_slug", String(200)),
    Column("condition_id", String(120)),
    Column("asset", String(120)),
    Column("title", String(200)),
    Column("role", String(10)),
    Column("session_id", String(50)),
    Index("ix_obs_trades_ts", "ts"),
    Index("ix_obs_trades_slug", "slug"),
    Index("ix_obs_trades_tx", "tx_hash"),
)

obs_merges = Table(
    "obs_merges",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", Float, nullable=False),
    Column("tx_hash", String(80), unique=True),
    Column("token_id", String(120)),
    Column("shares", Float),
    Column("block_number", Integer),
    Column("session_id", String(50)),
    Index("ix_obs_merges_ts", "ts"),
    Index("ix_obs_merges_tx", "tx_hash"),
)

obs_positions = Table(
    "obs_positions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", Float, nullable=False),
    Column("asset", String(120)),
    Column("size", Float),
    Column("avg_price", Float),
    Column("cash_pnl", Float),
    Column("current_value", Float),
    Column("cur_price", Float),
    Column("slug", String(120)),
    Column("outcome", String(10)),
    Column("session_id", String(50)),
    Index("ix_obs_positions_ts", "ts"),
    Index("ix_obs_positions_slug", "slug"),
)

obs_position_changes = Table(
    "obs_position_changes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", Float, nullable=False),
    Column("asset", String(120)),
    Column("slug", String(120)),
    Column("outcome", String(10)),
    Column("field", String(30)),
    Column("old_val", Float),
    Column("new_val", Float),
    Column("session_id", String(50)),
    Index("ix_obs_pos_changes_ts", "ts"),
)

obs_market_windows = Table(
    "obs_market_windows",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("slug", String(120)),
    Column("event_slug", String(200)),
    Column("title", String(200)),
    Column("status", String(20)),
    Column("up_vwap", Float),
    Column("down_vwap", Float),
    Column("up_shares", Float),
    Column("down_shares", Float),
    Column("combined_cost", Float),
    Column("estimated_edge", Float),
    Column("hedge_delay_sec", Float),
    Column("merged_shares", Float),
    Column("first_trade_at", String(50)),
    Column("last_trade_at", String(50)),
    Column("session_id", String(50)),
    Index("ix_obs_mw_slug", "slug"),
)
