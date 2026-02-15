"""REST API endpoints — live state + historical data from persistence layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Query

from complete_set.persistence.queries import (
    get_btc_history,
    get_market_windows_history,
    get_pnl_history,
    get_probability_history,
    get_session_detail,
    get_sessions,
    get_sessions_with_stats,
    get_trades,
)

if TYPE_CHECKING:
    from complete_set.engine import Engine


def create_rest_router(engine: "Engine", tr_engine=None) -> APIRouter:
    router = APIRouter()

    # ── Live state (from in-memory engine) ──

    @router.get("/state")
    async def state():
        """Full live state snapshot — markets, positions, orders, exposure, PnL."""
        snapshot = engine.get_state_snapshot()
        if tr_engine is not None:
            snapshot["trend_rider"] = tr_engine.get_state_snapshot()
        return snapshot

    @router.get("/state/markets")
    async def state_markets():
        snapshot = engine.get_state_snapshot()
        return snapshot["markets"]

    @router.get("/state/pnl")
    async def state_pnl():
        snapshot = engine.get_state_snapshot()
        return snapshot["pnl"]

    @router.get("/state/btc")
    async def state_btc():
        snapshot = engine.get_state_snapshot()
        return snapshot["btc"]

    @router.get("/config")
    async def config():
        snapshot = engine.get_state_snapshot()
        return snapshot["config"]

    # ── Historical data (from database) ──

    @router.get("/history/btc")
    async def history_btc(
        from_ts: float | None = Query(None, alias="from"),
        to_ts: float | None = Query(None, alias="to"),
        resolution: int | None = None,
        limit: int = 1000,
        offset: int = 0,
        session: str | None = None,
    ):
        return get_btc_history(from_ts, to_ts, resolution, limit, offset, session_id=session)

    @router.get("/history/probabilities")
    async def history_probabilities(
        slug: str | None = None,
        from_ts: float | None = Query(None, alias="from"),
        to_ts: float | None = Query(None, alias="to"),
        limit: int = 1000,
        offset: int = 0,
        session: str | None = None,
    ):
        return get_probability_history(slug, from_ts, to_ts, limit, offset, session_id=session)

    @router.get("/history/trades")
    async def history_trades(
        slug: str | None = None,
        from_ts: float | None = Query(None, alias="from"),
        to_ts: float | None = Query(None, alias="to"),
        event_type: str | None = Query(None, alias="type"),
        limit: int = 1000,
        offset: int = 0,
        session: str | None = None,
    ):
        return get_trades(slug, from_ts, to_ts, event_type, limit, offset, session_id=session)

    @router.get("/history/pnl")
    async def history_pnl(
        from_ts: float | None = Query(None, alias="from"),
        to_ts: float | None = Query(None, alias="to"),
        session: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ):
        return get_pnl_history(from_ts, to_ts, session, limit, offset)

    @router.get("/history/sessions")
    async def history_sessions(limit: int = 50):
        return get_sessions(limit)

    @router.get("/history/markets")
    async def history_markets(
        from_ts: float | None = Query(None, alias="from"),
        to_ts: float | None = Query(None, alias="to"),
        outcome: str | None = None,
        limit: int = 200,
        session: str | None = None,
    ):
        return get_market_windows_history(from_ts, to_ts, outcome, limit, session_id=session)

    # ── Session endpoints ──

    @router.get("/sessions")
    async def list_sessions(limit: int = 50):
        """List sessions with aggregated stats."""
        return get_sessions_with_stats(limit)

    @router.get("/sessions/{session_id}")
    async def session_detail(session_id: str):
        """Full session detail: trades, PnL curve, market windows."""
        return get_session_detail(session_id)

    return router
