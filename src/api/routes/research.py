"""
Research API endpoints.

Serves research data to the frontend dashboard:
- GET /research/surface - Probability surface data
- GET /research/signals - Recent signals from buffer
- GET /research/lag-stats - Lag statistics from observations
- GET /research/backtest - Backtest results
- GET /research/metrics - Aggregated metrics
- POST /research/observation/start - Start live observation
- POST /research/observation/stop - Stop live observation
- GET /research/observation/status - Get observation status
- WS /ws/research - Real-time updates
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from src.api.models.pipeline import PipelineStartRequest
from src.api.models.research import (
    BacktestMetrics,
    BacktestResult,
    BacktestTrade,
    EquityCurvePoint,
    LagStats,
    ObservationStatus,
    ProbabilityBucket,
    ProbabilitySurfaceResponse,
    ResearchMetrics,
    Signal,
    SurfaceMetadata,
)
from src.api.pipeline_controller import PipelineController
from src.api.research_state import ResearchStateManager
from src.utils.logging import get_logger

logger = get_logger("research_api")

router = APIRouter()

# Paths
SURFACE_PATH = Path("research/models/probability_surface.json")
OBSERVATIONS_DIR = Path("research/data/observations")
REPORTS_DIR = Path("research/output/reports")


# =============================================================================
# Helpers
# =============================================================================


def load_probability_surface() -> dict | None:
    """Load probability surface from JSON file."""
    if not SURFACE_PATH.exists():
        logger.warning("SURFACE_NOT_FOUND", str(SURFACE_PATH))
        return None

    try:
        with open(SURFACE_PATH) as f:
            return json.load(f)
    except Exception as e:
        logger.error("SURFACE_LOAD_ERROR", str(e))
        return None


def parse_surface_to_response(raw_data: dict) -> ProbabilitySurfaceResponse:
    """Parse raw surface JSON to response model."""
    buckets = []

    for _key_str, bucket_dict in raw_data.get("buckets", {}).items():
        # Handle inf values in deviation bounds
        dev_min = bucket_dict.get("deviation_min", 0)
        dev_max = bucket_dict.get("deviation_max", 0)

        # Skip buckets with infinite bounds for frontend display
        if dev_min == float("-inf") or dev_max == float("inf"):
            continue
        if isinstance(dev_min, str) and "inf" in dev_min.lower():
            continue
        if isinstance(dev_max, str) and "inf" in dev_max.lower():
            continue

        buckets.append(
            ProbabilityBucket(
                deviation_min=float(dev_min),
                deviation_max=float(dev_max),
                time_remaining=int(bucket_dict.get("time_remaining", 0)),
                vol_regime=bucket_dict.get("vol_regime", "all"),
                session=bucket_dict.get("session", "all"),
                sample_size=int(bucket_dict.get("sample_size", 0)),
                win_count=int(bucket_dict.get("win_count", 0)),
                win_rate=float(bucket_dict.get("win_rate", 0.5)),
                ci_lower=float(bucket_dict.get("ci_lower", 0)),
                ci_upper=float(bucket_dict.get("ci_upper", 1)),
                is_reliable=bucket_dict.get("is_reliable", False),
                is_usable=bucket_dict.get("is_usable", False),
            )
        )

    # Calculate metadata
    reliable_count = sum(1 for b in buckets if b.is_reliable)
    usable_count = sum(1 for b in buckets if b.is_usable)
    total_observations = sum(
        b.sample_size for b in buckets if b.vol_regime == "all" and b.session == "all"
    )

    metadata = SurfaceMetadata(
        last_updated=datetime.now().isoformat(),
        total_observations=total_observations,
        reliable_buckets=reliable_count,
        usable_buckets=usable_count,
        data_start="",  # Would need to track in surface
        data_end="",
    )

    return ProbabilitySurfaceResponse(buckets=buckets, metadata=metadata)


def compute_lag_stats() -> LagStats | None:
    """Compute lag statistics from most recent observation parquet."""
    if not OBSERVATIONS_DIR.exists():
        return None

    # Find most recent parquet file
    parquet_files = sorted(OBSERVATIONS_DIR.glob("snapshots_*.parquet"), reverse=True)
    if not parquet_files:
        return None

    try:
        df = pd.read_parquet(parquet_files[0])
        if "lag_ms" not in df.columns or len(df) == 0:
            return None

        lag_values = df["lag_ms"].dropna()
        if len(lag_values) == 0:
            return None

        return LagStats(
            sample_size=len(lag_values),
            median_lag_ms=float(np.median(lag_values)),
            p95_lag_ms=float(np.percentile(lag_values, 95)),
            p99_lag_ms=float(np.percentile(lag_values, 99)),
            std_lag_ms=float(np.std(lag_values)),
        )
    except Exception as e:
        logger.error("LAG_STATS_ERROR", str(e))
        return None


def load_backtest_results() -> BacktestResult | None:
    """Load backtest results from reports directory."""
    if not REPORTS_DIR.exists():
        return None

    # Look for backtest JSON file
    backtest_files = list(REPORTS_DIR.glob("*backtest*.json"))
    if not backtest_files:
        # Return empty result if no backtest has been run
        return BacktestResult(
            trades=[],
            equity_curve=[],
            metrics=BacktestMetrics(
                total_trades=0,
                winning_trades=0,
                win_rate=0.0,
                total_pnl=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                profit_factor=0.0,
                expectancy=0.0,
            ),
        )

    try:
        with open(backtest_files[0]) as f:
            data = json.load(f)

        trades = [BacktestTrade(**t) for t in data.get("trades", [])]
        equity_curve = [EquityCurvePoint(**p) for p in data.get("equity_curve", [])]
        metrics = BacktestMetrics(**data.get("metrics", {}))

        return BacktestResult(trades=trades, equity_curve=equity_curve, metrics=metrics)
    except Exception as e:
        logger.error("BACKTEST_LOAD_ERROR", str(e))
        return None


# =============================================================================
# REST Endpoints
# =============================================================================


@router.get("/surface")
async def get_surface() -> dict:
    """Get probability surface data."""
    raw_data = load_probability_surface()
    if raw_data is None:
        return {"surface": None, "error": "Probability surface not found"}

    surface = parse_surface_to_response(raw_data)
    return {"surface": surface.model_dump()}


@router.get("/signals")
async def get_signals(limit: int = Query(default=50, ge=1, le=100)) -> dict:
    """Get recent signals from buffer."""
    state = ResearchStateManager.get_instance()
    signals = state.get_signals(limit)
    return {"signals": signals}


@router.get("/lag-stats")
async def get_lag_stats() -> dict:
    """Get lag statistics from observations."""
    stats = compute_lag_stats()
    if stats is None:
        return {"lag_stats": None, "error": "No observation data available"}
    return {"lag_stats": stats.model_dump()}


@router.get("/backtest")
async def get_backtest() -> dict:
    """Get backtest results."""
    results = load_backtest_results()
    if results is None:
        return {"backtest": None, "error": "No backtest results available"}
    return {"backtest": results.model_dump()}


@router.get("/metrics")
async def get_metrics() -> dict:
    """Get aggregated research metrics."""
    state = ResearchStateManager.get_instance()

    # Load surface
    raw_surface = load_probability_surface()
    surface = parse_surface_to_response(raw_surface) if raw_surface else None

    # Get signals
    signals = state.get_signals(50)

    # Get lag stats
    lag_stats = compute_lag_stats()

    # Get observation status
    obs_status = state.get_observation_status()

    metrics = ResearchMetrics(
        surface=surface,
        signals=[Signal(**s) for s in signals] if signals else [],
        opportunities=[],  # Calculated by frontend from surface
        lag_stats=lag_stats,
        observation_status=ObservationStatus(
            is_running=obs_status.get("is_running", False),
            started_at=obs_status.get("started_at"),
            duration_sec=obs_status.get("duration_sec"),
            snapshots_collected=obs_status.get("snapshots_collected", 0),
            signals_detected=obs_status.get("signals_detected", 0),
            time_remaining_sec=None,
        ),
    )

    return {"metrics": metrics.model_dump()}


# =============================================================================
# Pipeline Control Endpoints
# =============================================================================


@router.get("/pipeline/status")
async def get_pipeline_status() -> dict:
    """Check filesystem state + current job (fast, no subprocess)."""
    controller = PipelineController.get_instance()
    status = controller.get_pipeline_status()
    return {"status": status.model_dump()}


@router.post("/pipeline/start")
async def start_pipeline_command(request: PipelineStartRequest) -> dict:
    """Start a pipeline command. Returns 409 if another command is running."""
    controller = PipelineController.get_instance()
    try:
        job = await controller.start_command(request.command, request.args)
        return {"job": job.model_dump()}
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error("PIPELINE_START_ERROR", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pipeline/stop")
async def stop_pipeline_command() -> dict:
    """Cancel the currently running command."""
    controller = PipelineController.get_instance()
    job = await controller.stop_command()
    if job is None:
        return {"job": None, "error": "No command running"}
    return {"job": job.model_dump()}


@router.get("/pipeline/job")
async def get_pipeline_job() -> dict:
    """Get current job details + progress log."""
    controller = PipelineController.get_instance()
    job = controller.current_job
    if job is None:
        return {"job": None}
    return {"job": job.model_dump()}


# =============================================================================
# Observation Control Endpoints (delegate to PipelineController)
# =============================================================================


class ObservationStartRequest(BaseModel):
    """Request body for starting observation."""

    duration_sec: int = 3600  # Default 1 hour


@router.post("/observation/start")
async def start_observation(request: ObservationStartRequest) -> dict:
    """Start live observation via PipelineController."""
    controller = PipelineController.get_instance()
    state = ResearchStateManager.get_instance()

    if controller.is_running:
        return {
            "status": state.get_observation_status(),
            "error": "Pipeline busy — another command is running",
        }

    try:
        await controller.start_command("observe", {"duration": request.duration_sec})
        logger.info("OBSERVATION_STARTED", f"duration_sec={request.duration_sec}")
        return {"status": state.get_observation_status()}
    except Exception as e:
        logger.error("OBSERVATION_START_ERROR", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/observation/stop")
async def stop_observation() -> dict:
    """Stop live observation via PipelineController."""
    controller = PipelineController.get_instance()
    state = ResearchStateManager.get_instance()

    if not state.observation_state.is_running:
        return {
            "status": state.get_observation_status(),
            "error": "Observation not running",
        }

    await controller.stop_command()
    logger.info("OBSERVATION_STOPPED", "")
    return {"status": state.get_observation_status()}


@router.get("/observation/status")
async def get_observation_status() -> dict:
    """Get current observation status."""
    state = ResearchStateManager.get_instance()
    return {"status": state.get_observation_status()}


# =============================================================================
# WebSocket Endpoint
# =============================================================================


@router.websocket("/ws/research")
async def websocket_research(websocket: WebSocket):
    """WebSocket endpoint for real-time research updates."""
    await websocket.accept()

    state = ResearchStateManager.get_instance()
    state.register_websocket(websocket)

    logger.info("WS_CONNECTED", f"total={len(state.websocket_connections)}")

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
        logger.info("WS_DISCONNECTED", "client_disconnected")
    except Exception as e:
        logger.error("WS_ERROR", str(e))
    finally:
        state.unregister_websocket(websocket)
