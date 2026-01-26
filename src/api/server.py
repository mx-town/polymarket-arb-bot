"""
FastAPI server for Polymarket Arbitrage Bot Admin Dashboard.

Runs independently from the bot, communicates via:
- /tmp/polymarket_metrics.json (metrics)
- /tmp/polymarket_bot.pid (PID file)
- config/default.yaml (configuration)
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from src.api.routes import config, metrics, control

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

# Health check endpoint (before routers to ensure it's accessible)
@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}


# Include routers
app.include_router(config.router, prefix="/api", tags=["config"])
app.include_router(metrics.router, prefix="/api", tags=["metrics"])
app.include_router(control.router, prefix="/api", tags=["control"])

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
