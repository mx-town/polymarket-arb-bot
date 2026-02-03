"""
FastAPI server for Polymarket Arbitrage Bot Admin Dashboard.

Runs independently from the bot, communicates via:
- /tmp/polymarket_metrics.json (metrics)
- /tmp/polymarket_bot.pid (PID file)
- config/default.yaml (configuration)
"""

import asyncio
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.pipeline_controller import PipelineController
from src.api.research_state import ResearchStateManager
from src.api.routes import config, control, metrics, research

# Create FastAPI app
app = FastAPI(
    title="Polymarket Arb Bot API",
    description="Admin dashboard API for controlling the arbitrage bot",
    version="1.0.0",
)

# CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Shutdown hook — kill any running pipeline subprocess
@app.on_event("shutdown")
async def shutdown_event():
    controller = PipelineController.get_instance()
    await controller.shutdown()


# Health check endpoint (before routers to ensure it's accessible)
@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}


# Research WebSocket endpoint - mounted here to match /api/ws/research path
@app.websocket("/api/ws/research")
async def websocket_research(websocket: WebSocket):
    """WebSocket endpoint for real-time research updates."""
    await websocket.accept()

    state = ResearchStateManager.get_instance()
    state.register_websocket(websocket)

    try:
        # Send initial state (including pipeline status)
        pipeline = PipelineController.get_instance()
        pipeline_status = pipeline.get_pipeline_status()

        await websocket.send_json(
            {
                "type": "initial",
                "data": {
                    "observation_status": state.get_observation_status(),
                    "signals": state.get_signals(50),
                    "pipeline_status": pipeline_status.model_dump(),
                },
                "timestamp": datetime.now().isoformat(),
            }
        )

        # Keep connection alive and listen for messages
        while True:
            try:
                # Wait for client messages (heartbeat/ping)
                message = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)

                if message == "ping":
                    await websocket.send_json(
                        {"type": "pong", "timestamp": datetime.now().isoformat()}
                    )

            except TimeoutError:
                # Send heartbeat
                await websocket.send_json(
                    {"type": "heartbeat", "timestamp": datetime.now().isoformat()}
                )

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        state.unregister_websocket(websocket)


# Include routers
app.include_router(config.router, prefix="/api", tags=["config"])
app.include_router(metrics.router, prefix="/api", tags=["metrics"])
app.include_router(control.router, prefix="/api", tags=["control"])
app.include_router(research.router, prefix="/api/research", tags=["research"])

# Serve static files (React dashboard) if built - MUST be last
# Static files mounted at "/" will catch all non-API routes
dashboard_dist = Path(__file__).parent.parent.parent / "dashboard" / "dist"
if dashboard_dist.exists():
    app.mount("/", StaticFiles(directory=str(dashboard_dist), html=True), name="dashboard")


def main():
    """Run the API server"""
    uvicorn.run(
        "src.api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
