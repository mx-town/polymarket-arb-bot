/**
 * Research feature TypeScript types
 * Types for probability surfaces, signals, trading opportunities, and backtesting
 */

/**
 * Signal types for trading opportunities
 */
export const SignalType = {
  DUTCH_BOOK: 'DUTCH_BOOK',
  LAG_ARB_UP: 'LAG_ARB_UP',
  LAG_ARB_DOWN: 'LAG_ARB_DOWN',
  MOMENTUM_UP: 'MOMENTUM_UP',
  MOMENTUM_DOWN: 'MOMENTUM_DOWN',
  FLASH_CRASH_UP: 'FLASH_CRASH_UP',
  FLASH_CRASH_DOWN: 'FLASH_CRASH_DOWN',
} as const;

export type SignalType = (typeof SignalType)[keyof typeof SignalType];

/**
 * Volatility regime classification
 */
export type VolatilityRegime = 'low' | 'medium' | 'high';

/**
 * Trading session classification
 */
export type TradingSession = 'asia' | 'europe' | 'us' | 'overlap';

/**
 * A bucket in the probability surface representing historical win rates
 * for a specific combination of market conditions
 */
export interface ProbabilityBucket {
  /** Minimum price deviation percentage for this bucket */
  deviation_min: number;
  /** Maximum price deviation percentage for this bucket */
  deviation_max: number;
  /** Time remaining to resolution in seconds */
  time_remaining: number;
  /** Volatility regime classification */
  vol_regime: VolatilityRegime;
  /** Trading session when observation occurred */
  session: TradingSession;
  /** Number of observations in this bucket */
  sample_size: number;
  /** Number of winning trades */
  win_count: number;
  /** Win rate (win_count / sample_size) */
  win_rate: number;
  /** Lower bound of confidence interval */
  ci_lower: number;
  /** Upper bound of confidence interval */
  ci_upper: number;
  /** Whether the bucket has enough samples for statistical reliability */
  is_reliable: boolean;
  /** Whether the bucket can be used for trading decisions */
  is_usable: boolean;
}

/**
 * Metadata about the probability surface
 */
export interface ProbabilitySurfaceMetadata {
  /** When the surface was last updated */
  last_updated: string;
  /** Total number of observations across all buckets */
  total_observations: number;
  /** Number of buckets with reliable data */
  reliable_buckets: number;
  /** Number of buckets usable for trading */
  usable_buckets: number;
  /** Data collection start timestamp */
  data_start: string;
  /** Data collection end timestamp */
  data_end: string;
}

/**
 * Complete probability surface with all buckets and metadata
 */
export interface ProbabilitySurface {
  /** Array of probability buckets */
  buckets: ProbabilityBucket[];
  /** Surface metadata */
  metadata: ProbabilitySurfaceMetadata;
}

/**
 * Signal metadata containing additional context
 */
export interface SignalMetadata {
  /** Source of the signal */
  source?: string;
  /** Model version that generated the signal */
  model_version?: string;
  /** Additional context-specific data */
  [key: string]: unknown;
}

/**
 * A trading signal detected by the research system
 */
export interface Signal {
  /** Type of signal detected */
  signal_type: SignalType;
  /** Unix timestamp in milliseconds when signal was detected */
  timestamp_ms: number;
  /** Current UP token price */
  up_price: number;
  /** Current DOWN token price */
  down_price: number;
  /** Combined price (up_price + down_price) */
  combined_price: number;
  /** Expected edge based on historical probability surface */
  expected_edge: number;
  /** Confidence score (0-1) based on bucket reliability */
  confidence: number;
  /** Current price deviation from fair value in percentage */
  deviation_pct: number;
  /** Time remaining until market resolution in seconds */
  time_remaining_sec: number;
  /** Current trading session */
  session: TradingSession;
  /** Additional signal metadata */
  metadata?: SignalMetadata;
}

/**
 * A potential trading opportunity with calculated metrics
 */
export interface TradingOpportunity {
  /** Direction to trade (UP or DOWN) */
  direction: 'UP' | 'DOWN';
  /** Raw edge before fees */
  raw_edge: number;
  /** Edge after accounting for fees */
  edge_after_fees: number;
  /** Expected value of the trade */
  expected_value: number;
  /** Kelly criterion fraction for position sizing */
  kelly_fraction: number;
  /** Overall confidence score for the opportunity */
  confidence_score: number;
  /** Whether the opportunity meets all criteria for trading */
  is_tradeable: boolean;
  /** Reason for rejection if not tradeable */
  reject_reason: string | null;
}

/**
 * Statistics about lag between Binance and Polymarket
 */
export interface LagStats {
  /** Number of lag measurements */
  sample_size: number;
  /** Median lag in milliseconds */
  median_lag_ms: number;
  /** 95th percentile lag in milliseconds */
  p95_lag_ms: number;
  /** 99th percentile lag in milliseconds */
  p99_lag_ms: number;
  /** Standard deviation of lag in milliseconds */
  std_lag_ms: number;
}

/**
 * A snapshot of market state enriched with research data
 */
export interface EnrichedSnapshot {
  /** Unix timestamp in milliseconds */
  timestamp_ms: number;
  /** Current Binance BTC price */
  binance_price: number;
  /** Current Chainlink oracle price */
  chainlink_price: number;
  /** Measured lag between sources in milliseconds */
  lag_ms: number;
  /** Divergence between Binance and Chainlink in percentage */
  divergence_pct: number;
  /** Model-predicted probability of UP winning */
  model_prob_up: number;
  /** Model confidence in its prediction */
  model_confidence: number;
  /** Edge after fees if trading based on model */
  edge_after_fees: number;
  /** Whether a signal was detected */
  signal_detected: boolean;
  /** Candle open price for momentum calculation */
  candle_open_price: number;
  /** Time remaining until market resolution in seconds */
  time_remaining_sec: number;
}

/**
 * A single trade in backtest results
 */
export interface BacktestTrade {
  /** Entry timestamp */
  entry_time: string;
  /** Exit timestamp */
  exit_time: string;
  /** Direction traded */
  direction: 'UP' | 'DOWN';
  /** Entry price */
  entry_price: number;
  /** Exit price */
  exit_price: number;
  /** Position size */
  size: number;
  /** Profit/loss in USD */
  pnl: number;
  /** Return percentage */
  return_pct: number;
  /** Signal type that triggered the trade */
  signal_type: SignalType;
}

/**
 * A point in the equity curve
 */
export interface EquityCurvePoint {
  /** Timestamp */
  timestamp: string;
  /** Equity value */
  equity: number;
  /** Drawdown percentage from peak */
  drawdown_pct: number;
}

/**
 * Backtest performance metrics
 */
export interface BacktestMetrics {
  /** Total number of trades */
  total_trades: number;
  /** Number of winning trades */
  winning_trades: number;
  /** Number of losing trades */
  losing_trades: number;
  /** Win rate percentage */
  win_rate: number;
  /** Total profit/loss */
  total_pnl: number;
  /** Maximum drawdown percentage */
  max_drawdown_pct: number;
  /** Sharpe ratio (annualized) */
  sharpe_ratio: number;
  /** Sortino ratio (annualized) */
  sortino_ratio: number;
  /** Profit factor (gross profit / gross loss) */
  profit_factor: number;
  /** Average trade return */
  avg_trade_return: number;
  /** Average winning trade return */
  avg_win: number;
  /** Average losing trade return */
  avg_loss: number;
  /** Expectancy per trade */
  expectancy: number;
}

/**
 * Complete backtest results
 */
export interface BacktestResult {
  /** Array of trades executed during backtest */
  trades: BacktestTrade[];
  /** Equity curve over time */
  equity_curve: EquityCurvePoint[];
  /** Performance metrics */
  metrics: BacktestMetrics;
}

// =============================================================================
// Pipeline Control Types
// =============================================================================

/**
 * A progress event from a pipeline command execution
 */
export interface PipelineProgressEvent {
  /** Stage marker name (e.g., INIT_START, DOWNLOAD_COMPLETE) */
  stage: string;
  /** Human-readable progress message */
  message: string;
  /** Additional detail from CLI output */
  detail: string;
  /** ISO datetime when stage was reached */
  timestamp: string;
}

/**
 * Status of a running or completed pipeline job
 */
export interface PipelineJobStatus {
  /** CLI command being executed */
  command: string;
  /** Arguments passed to the command */
  args: Record<string, unknown>;
  /** Job status: running, completed, failed, cancelled */
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  /** ISO datetime when job started */
  started_at: string;
  /** Seconds elapsed since start */
  elapsed_sec: number;
  /** Stage progress trail */
  progress: PipelineProgressEvent[];
  /** Process exit code (null if still running) */
  exit_code: number | null;
}

/**
 * Filesystem state check — what data/models exist
 */
export interface PipelineStatus {
  /** Whether probability_surface.json exists */
  has_model: boolean;
  /** Hours since model was last modified */
  model_age_hours: number | null;
  /** Whether raw candle data exists */
  has_raw_data: boolean;
  /** Number of observation parquet files */
  observation_files: number;
  /** Total size of observation files in MB */
  observation_size_mb: number;
  /** Currently running job, if any */
  current_job: PipelineJobStatus | null;
}

/**
 * Status of the observation/data collection process
 */
export interface ObservationStatus {
  /** Whether observation is currently active */
  is_running: boolean;
  /** When observation started */
  started_at: string | null;
  /** Planned duration in seconds */
  duration_sec: number | null;
  /** Number of snapshots collected */
  snapshots_collected: number;
  /** Number of signals detected */
  signals_detected: number;
  /** Time remaining in seconds */
  time_remaining_sec: number | null;
}

/**
 * Complete research metrics payload
 */
export interface ResearchMetrics {
  /** Probability surface data */
  surface: ProbabilitySurface | null;
  /** Recent signals */
  signals: Signal[];
  /** Current trading opportunities */
  opportunities: TradingOpportunity[];
  /** Lag statistics */
  lag_stats: LagStats | null;
  /** Current observation status */
  observation_status: ObservationStatus;
}

/**
 * WebSocket message types for real-time updates
 */
export type ResearchWebSocketMessageType =
  | 'initial'
  | 'snapshot'
  | 'signal'
  | 'opportunity'
  | 'surface_update'
  | 'observation_status'
  | 'pipeline_progress'
  | 'pipeline_complete';

/**
 * Base WebSocket message structure
 */
export interface ResearchWebSocketMessage<T = unknown> {
  /** Message type */
  type: ResearchWebSocketMessageType;
  /** Message payload */
  data: T;
  /** Timestamp when message was sent */
  timestamp: string;
}

/**
 * Snapshot WebSocket message
 */
export type SnapshotMessage = ResearchWebSocketMessage<EnrichedSnapshot>;

/**
 * Signal WebSocket message
 */
export type SignalMessage = ResearchWebSocketMessage<Signal>;

/**
 * Opportunity WebSocket message
 */
export type OpportunityMessage = ResearchWebSocketMessage<TradingOpportunity>;

/**
 * Surface update WebSocket message
 */
export type SurfaceUpdateMessage = ResearchWebSocketMessage<ProbabilitySurface>;

/**
 * Observation status WebSocket message
 */
export type ObservationStatusMessage = ResearchWebSocketMessage<ObservationStatus>;

/**
 * Pipeline progress WebSocket message
 */
export type PipelineProgressMessage = ResearchWebSocketMessage<PipelineProgressEvent>;

/**
 * Pipeline complete WebSocket message
 */
export type PipelineCompleteMessage = ResearchWebSocketMessage<PipelineJobStatus>;
