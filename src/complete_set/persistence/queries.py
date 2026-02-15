"""Read queries for REST API — time-series and event data from SQLite/PostgreSQL."""

from __future__ import annotations

from sqlalchemy import desc, func, select, text

from complete_set.persistence.db import get_engine
from complete_set.persistence.schema import (
    btc_prices,
    market_windows,
    pnl_snapshots,
    probability_snapshots,
    sessions,
    trades,
)


def _rows_to_dicts(result) -> list[dict]:
    """Convert SQLAlchemy result rows to list of dicts."""
    return [dict(row._mapping) for row in result]


def get_btc_history(
    from_ts: float | None = None,
    to_ts: float | None = None,
    resolution: int | None = None,
    limit: int = 1000,
    offset: int = 0,
    session_id: str | None = None,
) -> list[dict]:
    """BTC price series for charting. Optional downsampling via resolution (seconds)."""
    engine = get_engine()

    if resolution and resolution > 1:
        # Downsample: group by time bucket, take OHLC within each bucket
        bucket = func.cast(btc_prices.c.ts / resolution, text("INTEGER")) * resolution
        q = (
            select(
                bucket.label("ts"),
                func.min(btc_prices.c.price).label("low"),
                func.max(btc_prices.c.price).label("high"),
                # First/last approximation via min/max ts within bucket
                btc_prices.c.price.label("close"),
            )
            .group_by(bucket)
            .order_by(bucket)
        )
    else:
        q = select(btc_prices).order_by(btc_prices.c.ts)

    if from_ts is not None:
        q = q.where(btc_prices.c.ts >= from_ts)
    if to_ts is not None:
        q = q.where(btc_prices.c.ts <= to_ts)
    if session_id is not None:
        q = q.where(btc_prices.c.session_id == session_id)

    q = q.limit(min(limit, 10000)).offset(offset)

    with engine.connect() as conn:
        return _rows_to_dicts(conn.execute(q))


def get_probability_history(
    slug: str | None = None,
    from_ts: float | None = None,
    to_ts: float | None = None,
    limit: int = 1000,
    offset: int = 0,
    session_id: str | None = None,
) -> list[dict]:
    """Probability snapshots for a market."""
    engine = get_engine()
    q = select(probability_snapshots).order_by(probability_snapshots.c.ts)

    if slug is not None:
        q = q.where(probability_snapshots.c.market_slug == slug)
    if from_ts is not None:
        q = q.where(probability_snapshots.c.ts >= from_ts)
    if to_ts is not None:
        q = q.where(probability_snapshots.c.ts <= to_ts)
    if session_id is not None:
        q = q.where(probability_snapshots.c.session_id == session_id)

    q = q.limit(min(limit, 10000)).offset(offset)

    with engine.connect() as conn:
        return _rows_to_dicts(conn.execute(q))


def get_trades(
    slug: str | None = None,
    from_ts: float | None = None,
    to_ts: float | None = None,
    event_type: str | None = None,
    limit: int = 1000,
    offset: int = 0,
    session_id: str | None = None,
) -> list[dict]:
    """Trade events (entries, fills, hedges, merges)."""
    engine = get_engine()
    q = select(trades).order_by(desc(trades.c.ts))

    if slug is not None:
        q = q.where(trades.c.market_slug == slug)
    if from_ts is not None:
        q = q.where(trades.c.ts >= from_ts)
    if to_ts is not None:
        q = q.where(trades.c.ts <= to_ts)
    if event_type is not None:
        q = q.where(trades.c.event_type == event_type)
    if session_id is not None:
        q = q.where(trades.c.session_id == session_id)

    q = q.limit(min(limit, 10000)).offset(offset)

    with engine.connect() as conn:
        return _rows_to_dicts(conn.execute(q))


def get_pnl_history(
    from_ts: float | None = None,
    to_ts: float | None = None,
    session_id: str | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> list[dict]:
    """PnL trajectory over time."""
    engine = get_engine()
    q = select(pnl_snapshots).order_by(pnl_snapshots.c.ts)

    if from_ts is not None:
        q = q.where(pnl_snapshots.c.ts >= from_ts)
    if to_ts is not None:
        q = q.where(pnl_snapshots.c.ts <= to_ts)
    if session_id is not None:
        q = q.where(pnl_snapshots.c.session_id == session_id)

    q = q.limit(min(limit, 10000)).offset(offset)

    with engine.connect() as conn:
        return _rows_to_dicts(conn.execute(q))


def get_sessions(limit: int = 50) -> list[dict]:
    """List bot sessions, most recent first."""
    engine = get_engine()
    q = select(sessions).order_by(desc(sessions.c.started_at)).limit(limit)

    with engine.connect() as conn:
        return _rows_to_dicts(conn.execute(q))


def get_sessions_with_stats(limit: int = 50) -> list[dict]:
    """List sessions with aggregated stats: trade count, merge count, final PnL."""
    engine = get_engine()
    q = text("""
        SELECT s.*,
            (SELECT COUNT(*) FROM trades t WHERE t.session_id = s.id) AS trade_count,
            (SELECT COUNT(*) FROM trades t WHERE t.session_id = s.id AND t.event_type = 'merge_complete') AS merge_count,
            (SELECT p.realized FROM pnl_snapshots p WHERE p.session_id = s.id ORDER BY p.ts DESC LIMIT 1) AS final_pnl
        FROM sessions s
        ORDER BY s.started_at DESC
        LIMIT :limit
    """)
    with engine.connect() as conn:
        result = conn.execute(q, {"limit": limit})
        return [dict(row._mapping) for row in result]


def get_session_detail(session_id: str) -> dict:
    """Full session detail: session metadata + trades + PnL curve + market windows."""
    engine = get_engine()
    with engine.connect() as conn:
        # Session metadata
        s = conn.execute(
            select(sessions).where(sessions.c.id == session_id)
        ).first()
        session_dict = dict(s._mapping) if s else {}

        # Trades for this session
        t = conn.execute(
            select(trades)
            .where(trades.c.session_id == session_id)
            .order_by(trades.c.ts)
        )
        trades_list = [dict(r._mapping) for r in t]

        # PnL curve
        p = conn.execute(
            select(pnl_snapshots)
            .where(pnl_snapshots.c.session_id == session_id)
            .order_by(pnl_snapshots.c.ts)
        )
        pnl_curve = [dict(r._mapping) for r in p]

        # Market windows
        mw = conn.execute(
            select(market_windows)
            .where(market_windows.c.session_id == session_id)
            .order_by(market_windows.c.entered_at)
        )
        windows = [dict(r._mapping) for r in mw]

    return {
        "session": session_dict,
        "trades": trades_list,
        "pnl_curve": pnl_curve,
        "market_windows": windows,
    }


def get_market_windows_history(
    from_ts: float | None = None,
    to_ts: float | None = None,
    outcome: str | None = None,
    limit: int = 200,
    session_id: str | None = None,
) -> list[dict]:
    """Market window outcomes."""
    engine = get_engine()
    q = select(market_windows).order_by(desc(market_windows.c.end_time))

    if from_ts is not None:
        q = q.where(market_windows.c.end_time >= from_ts)
    if to_ts is not None:
        q = q.where(market_windows.c.end_time <= to_ts)
    if outcome is not None:
        q = q.where(market_windows.c.outcome == outcome)
    if session_id is not None:
        q = q.where(market_windows.c.session_id == session_id)

    q = q.limit(min(limit, 1000))

    with engine.connect() as conn:
        return _rows_to_dicts(conn.execute(q))
