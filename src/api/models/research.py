"""Pydantic models for Research API responses.

These models match the frontend TypeScript types for the Research Dashboard.
"""

from typing import Literal

from pydantic import BaseModel, Field

# === Probability Surface Models ===


class ProbabilityBucket(BaseModel):
    """A bucket in the probability surface representing win rate for a specific condition."""

    deviation_min: float = Field(description="Minimum deviation percentage for this bucket")
    deviation_max: float = Field(description="Maximum deviation percentage for this bucket")
    time_remaining: int = Field(description="Time remaining in seconds")
    vol_regime: Literal["low", "medium", "high", "all"] = Field(
        description="Volatility regime classification"
    )
    session: Literal["asia", "europe", "us_eu_overlap", "us", "late_us", "all"] = Field(
        description="Trading session"
    )
    sample_size: int = Field(description="Number of observations in this bucket")
    win_count: int = Field(description="Number of winning outcomes")
    win_rate: float = Field(description="Win rate (win_count / sample_size)")
    ci_lower: float = Field(description="Lower bound of confidence interval")
    ci_upper: float = Field(description="Upper bound of confidence interval")
    is_reliable: bool = Field(
        description="Whether sample size is sufficient for statistical reliability"
    )
    is_usable: bool = Field(description="Whether this bucket can be used for trading decisions")


class SurfaceMetadata(BaseModel):
    """Metadata about the probability surface."""

    last_updated: str = Field(description="ISO datetime of last update")
    total_observations: int = Field(description="Total number of observations")
    reliable_buckets: int = Field(description="Number of statistically reliable buckets")
    usable_buckets: int = Field(description="Number of buckets usable for trading")
    data_start: str = Field(description="ISO datetime of earliest observation")
    data_end: str = Field(description="ISO datetime of latest observation")


class ProbabilitySurfaceResponse(BaseModel):
    """Response containing the full probability surface."""

    buckets: list[ProbabilityBucket] = Field(description="All probability buckets")
    metadata: SurfaceMetadata = Field(description="Surface metadata")


# === Signal Models ===


class Signal(BaseModel):
    """A detected trading signal."""

    signal_type: str = Field(
        description="Type of signal (DUTCH_BOOK, LAG_ARB_UP, LAG_ARB_DOWN, "
        "MOMENTUM_UP, MOMENTUM_DOWN, FLASH_CRASH_UP, FLASH_CRASH_DOWN)"
    )
    timestamp_ms: int = Field(description="Unix timestamp in milliseconds")
    up_price: float = Field(description="Current UP token price")
    down_price: float = Field(description="Current DOWN token price")
    combined_price: float = Field(description="Sum of UP and DOWN prices")
    expected_edge: float = Field(description="Expected edge from this signal")
    confidence: float = Field(ge=0, le=1, description="Confidence score (0-1)")
    deviation_pct: float = Field(description="Price deviation percentage from fair value")
    time_remaining_sec: int = Field(description="Seconds until market resolution")
    session: str = Field(description="Trading session when signal was detected")
    metadata: dict | None = Field(default=None, description="Additional signal-specific data")


class TradingOpportunity(BaseModel):
    """An evaluated trading opportunity with edge calculation."""

    direction: Literal["UP", "DOWN"] = Field(description="Trade direction")
    raw_edge: float = Field(description="Raw edge before fees")
    edge_after_fees: float = Field(description="Edge after accounting for fees")
    expected_value: float = Field(description="Expected value of the trade")
    kelly_fraction: float = Field(description="Optimal Kelly bet fraction")
    confidence_score: float = Field(description="Confidence in the opportunity")
    is_tradeable: bool = Field(description="Whether this opportunity meets trading criteria")
    reject_reason: str | None = Field(
        default=None, description="Reason for rejection if not tradeable"
    )


# === Lag Statistics Models ===


class LagStats(BaseModel):
    """Statistics about price lag between Binance and Polymarket."""

    sample_size: int = Field(description="Number of lag measurements")
    median_lag_ms: float = Field(description="Median lag in milliseconds")
    p95_lag_ms: float = Field(description="95th percentile lag in milliseconds")
    p99_lag_ms: float = Field(description="99th percentile lag in milliseconds")
    std_lag_ms: float = Field(description="Standard deviation of lag in milliseconds")


# === Snapshot Models ===


class EnrichedSnapshot(BaseModel):
    """A market snapshot enriched with model predictions."""

    timestamp_ms: int = Field(description="Unix timestamp in milliseconds")
    binance_price: float = Field(description="Binance spot price")
    chainlink_price: float = Field(description="Chainlink oracle price")
    lag_ms: float = Field(description="Detected lag in milliseconds")
    divergence_pct: float = Field(description="Price divergence percentage")
    model_prob_up: float = Field(description="Model-predicted probability of UP")
    model_confidence: float = Field(description="Model confidence in prediction")
    edge_after_fees: float = Field(description="Calculated edge after fees")
    signal_detected: bool = Field(description="Whether a signal was detected")
    candle_open_price: float = Field(description="Opening price of current candle")
    time_remaining_sec: int = Field(description="Seconds until market resolution")


# === Backtest Models ===


class BacktestTrade(BaseModel):
    """A single trade from backtesting."""

    entry_time: str = Field(description="ISO datetime of entry")
    exit_time: str = Field(description="ISO datetime of exit")
    direction: Literal["UP", "DOWN"] = Field(description="Trade direction")
    entry_price: float = Field(description="Entry price")
    exit_price: float = Field(description="Exit price")
    size: float = Field(description="Position size in USDC")
    pnl: float = Field(description="Profit/loss in USDC")
    return_pct: float = Field(description="Return percentage")
    signal_type: str = Field(description="Type of signal that triggered the trade")


class BacktestMetrics(BaseModel):
    """Aggregate metrics from backtesting."""

    total_trades: int = Field(description="Total number of trades")
    winning_trades: int = Field(description="Number of winning trades")
    win_rate: float = Field(description="Win rate (winning_trades / total_trades)")
    total_pnl: float = Field(description="Total profit/loss in USDC")
    max_drawdown_pct: float = Field(description="Maximum drawdown percentage")
    sharpe_ratio: float = Field(description="Risk-adjusted return (Sharpe ratio)")
    sortino_ratio: float = Field(description="Downside risk-adjusted return (Sortino ratio)")
    profit_factor: float = Field(description="Gross profit / gross loss")
    expectancy: float = Field(description="Average expected profit per trade")


class EquityCurvePoint(BaseModel):
    """A point on the equity curve."""

    timestamp: str = Field(description="ISO datetime")
    equity: float = Field(description="Portfolio equity value")
    drawdown_pct: float = Field(description="Current drawdown percentage")


class BacktestResult(BaseModel):
    """Complete backtest results."""

    trades: list[BacktestTrade] = Field(description="All trades executed in backtest")
    equity_curve: list[EquityCurvePoint] = Field(description="Equity curve over time")
    metrics: BacktestMetrics = Field(description="Aggregate performance metrics")


# === Observation Status Models ===


class ObservationStatus(BaseModel):
    """Status of the live observation process."""

    is_running: bool = Field(description="Whether observation is currently running")
    started_at: str | None = Field(
        default=None, description="ISO datetime when observation started"
    )
    duration_sec: int | None = Field(
        default=None, description="How long observation has been running"
    )
    snapshots_collected: int = Field(description="Number of snapshots collected")
    signals_detected: int = Field(description="Number of signals detected")
    time_remaining_sec: int | None = Field(
        default=None, description="Seconds until observation ends (if time-limited)"
    )


# === Aggregate Research Metrics ===


class ResearchMetrics(BaseModel):
    """Complete research metrics for the dashboard."""

    surface: ProbabilitySurfaceResponse | None = Field(
        default=None, description="Current probability surface"
    )
    signals: list[Signal] = Field(default_factory=list, description="Recent signals detected")
    opportunities: list[TradingOpportunity] = Field(
        default_factory=list, description="Current trading opportunities"
    )
    lag_stats: LagStats | None = Field(default=None, description="Current lag statistics")
    observation_status: ObservationStatus = Field(description="Status of observation process")
