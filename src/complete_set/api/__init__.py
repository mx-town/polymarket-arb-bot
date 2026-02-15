"""FastAPI application factory for the dashboard API."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

from complete_set.api.middleware import setup_middleware
from complete_set.api.routes_rest import create_rest_router
from complete_set.api.routes_ws import create_ws_router

if TYPE_CHECKING:
    from complete_set.engine import Engine


def create_app(engine: "Engine", tr_engine=None) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Polymarket Bot Dashboard API",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url=None,
    )

    setup_middleware(app)

    app.state.engine = engine
    app.state.tr_engine = tr_engine

    app.include_router(create_rest_router(engine, tr_engine=tr_engine), prefix="/api/v1")
    app.include_router(create_ws_router(engine, tr_engine=tr_engine))

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "engine": "running"}

    return app
