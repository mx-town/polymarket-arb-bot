# Polymarket Probability Model Research

A framework for building calibrated probability models for Polymarket UP/DOWN markets.

## Objective

Build a real-time probability function:

```
P(UP) = f(deviation, time_remaining, volatility, session)
```

Output: Lookup table that returns calibrated probability with confidence intervals.

---

## Quick Start

```bash
# Install dependencies
pip install pandas numpy scipy pyarrow

# Fetch 6 months of BTC data and run full analysis
python research/run_research.py --all --months 6

# Or run individual steps
python research/run_research.py --fetch      # Download historical data
python research/run_research.py --analyze    # Run statistical analysis
python research/run_research.py --validate   # Run backtest validation
```

---

## Architecture

```
research/
├── __init__.py
├── run_research.py              # Main orchestration script
├── data/
│   ├── binance_historical.py    # Historical data fetcher
│   └── feature_extractor.py     # Feature engineering
├── models/
│   ├── probability_surface.py   # Core probability model
│   └── edge_calculator.py       # Trading signal generator
└── analysis/
    ├── volatility_analysis.py   # Vol regime effects
    ├── session_analysis.py      # Time-of-day effects
    ├── lag_analysis.py          # Repricing delay measurement
    └── validation.py            # Backtest & calibration
```

---

## Module Reference

### Data Collection

#### `binance_historical.py`

Downloads historical 1-minute candles from Binance API.

**Features:**
- Fetches 6+ months of data (~260,000 candles)
- Checkpointing for resumable downloads
- Incremental updates (only fetches new data)
- Rate limiting to avoid API bans

**Usage:**
```python
from research.data.binance_historical import BinanceHistoricalFetcher

fetcher = BinanceHistoricalFetcher(data_dir="research/data/raw")
df = fetcher.fetch("BTCUSDT", months=6)
```

**Output columns:**
| Column | Type | Description |
|--------|------|-------------|
| `open_time` | int | Unix timestamp (ms) |
| `open` | float | Opening price |
| `high` | float | High price |
| `low` | float | Low price |
| `close` | float | Closing price |
| `volume` | float | Volume |

---

#### `feature_extractor.py`

Transforms raw candles into labeled 15-minute windows aligned to Polymarket schedules.

**Features:**
- Aligns windows to :00, :15, :30, :45 boundaries
- Computes rolling volatility
- Classifies trading sessions
- Labels outcomes (UP=1, DOWN=0)

**Usage:**
```python
from research.data.feature_extractor import FeatureExtractor

extractor = FeatureExtractor(window_minutes=15)
features_df = extractor.extract_windows(candle_df, "BTCUSDT")
```

**Output columns:**
| Column | Type | Description |
|--------|------|-------------|
| `window_start` | int | Window start timestamp (ms) |
| `deviation_pct` | float | `(current - open) / open` |
| `time_remaining` | int | Minutes until window close |
| `realized_vol` | float | Rolling 15-min volatility |
| `session` | str | `asia`, `eu`, `us`, `eu_us`, `night` |
| `vol_regime` | str | `low`, `medium`, `high` |
| `outcome` | int | 1=UP, 0=DOWN |
| `minute_index` | int | Which minute within window (0-14) |

**Session definitions (UTC):**
| Session | Hours | Markets |
|---------|-------|---------|
| Asia | 00:00-08:00 | Tokyo, Hong Kong |
| EU | 08:00-13:00 | London |
| EU/US Overlap | 13:00-17:00 | Highest liquidity |
| US | 17:00-21:00 | New York |
| Night | 21:00-00:00 | Low activity |

---

### Probability Model

#### `probability_surface.py`

Builds empirical probability lookup table by bucketing historical observations.

**Bucket structure:**
- Deviation: 0.1% bands from -2% to +2% (40 buckets)
- Time remaining: 1-minute bands (15 buckets)
- Volatility: 3 regimes + "all" (4 options)
- Total: ~2,400 buckets

**Features:**
- Wilson score confidence intervals (better for small samples)
- Reliability flags (n ≥ 30 for reliable)
- JSON serialization for persistence

**Usage:**
```python
from research.models.probability_surface import ProbabilitySurface

# Fit model
surface = ProbabilitySurface(deviation_step=0.001, deviation_range=(-0.02, 0.02))
surface.fit(features_df)

# Query probability
prob, ci_lower, ci_upper, is_reliable = surface.get_probability(
    deviation_pct=0.003,    # +0.3% from open
    time_remaining=7,       # 7 minutes left
    vol_regime="medium"
)

# Save/load
surface.save("model.json")
surface = ProbabilitySurface.load("model.json")
```

**Return values:**
| Field | Type | Description |
|-------|------|-------------|
| `win_rate` | float | Empirical P(UP) |
| `ci_lower` | float | 95% CI lower bound |
| `ci_upper` | float | 95% CI upper bound |
| `is_reliable` | bool | True if sample_size ≥ 30 |

**Example results (synthetic test data):**
```
Deviation | P(UP)  | CI           | Samples | Reliable
-0.3%    | 38.2%  | [34.9%, 41.5%] |   830   | YES
-0.2%    | 44.6%  | [42.2%, 47.1%] |  1574   | YES
 0.0%    | 52.4%  | [50.2%, 54.6%] |  1926   | YES
+0.2%    | 62.6%  | [59.4%, 65.6%] |   943   | YES
+0.3%    | 65.7%  | [61.3%, 69.8%] |   475   | YES
```

---

#### `edge_calculator.py`

Compares model probability to market prices and identifies trading opportunities.

**Features:**
- Accounts for trading fees (3% for 15m, 0% for 1H)
- Kelly criterion position sizing
- Conservative edge using CI bound
- Minimum edge threshold filtering

**Usage:**
```python
from research.models.edge_calculator import EdgeCalculator

calc = EdgeCalculator(
    surface=surface,
    fee_rate=0.03,           # 3% per side
    min_edge_threshold=0.05  # 5% minimum edge
)

opp = calc.calculate_edge(
    deviation_pct=0.003,
    time_remaining=7,
    market_price_up=0.55,
    market_price_down=0.49,
    vol_regime="medium"
)

if opp.is_tradeable:
    print(f"BUY {opp.direction.value}")
    print(f"Edge after fees: {opp.edge_after_fees:.1%}")
    print(f"Kelly fraction: {opp.kelly_fraction:.1%}")
```

**TradingOpportunity fields:**
| Field | Type | Description |
|-------|------|-------------|
| `direction` | Direction | `UP`, `DOWN`, or `NONE` |
| `model_prob_up` | float | Model's P(UP) estimate |
| `raw_edge` | float | Model prob - market prob |
| `edge_after_fees` | float | Edge minus round-trip fees |
| `kelly_fraction` | float | Optimal position size (0-25%) |
| `confidence_score` | float | 0-1 based on sample size & CI |
| `is_tradeable` | bool | Meets all criteria |
| `reject_reason` | str | Why not tradeable (if applicable) |

---

### Analysis

#### `volatility_analysis.py`

Tests if probability surface changes across volatility regimes.

**Key questions:**
- Does high volatility reduce predictability?
- Does the deviation→outcome relationship flatten?
- Should we use different thresholds per regime?

**Usage:**
```python
from research.analysis.volatility_analysis import VolatilityAnalyzer, generate_volatility_report

analyzer = VolatilityAnalyzer()
regime_stats = analyzer.analyze(features_df)
comparison = analyzer.compare_regimes(features_df)
thresholds = analyzer.optimal_thresholds_by_regime(features_df, target_win_rate=0.55)

report = generate_volatility_report(features_df, output_path="vol_report.txt")
```

---

#### `session_analysis.py`

Compares win rates and mean reversion strength across trading sessions.

**Key questions:**
- Does mean reversion vary by session?
- Are extreme moves more common in certain sessions?
- Which hours have highest predictability?

**Usage:**
```python
from research.analysis.session_analysis import SessionAnalyzer, generate_session_report

analyzer = SessionAnalyzer()
session_stats = analyzer.analyze(features_df)
comparison = analyzer.compare_sessions(features_df)
hourly = analyzer.hourly_analysis(features_df)

report = generate_session_report(features_df, output_path="session_report.txt")
```

---

#### `lag_analysis.py`

Framework for measuring Polymarket repricing delays.

**Note:** Requires live data collection to measure actual lags.

**Usage:**
```python
from research.analysis.lag_analysis import LagAnalyzer, LagDataCollector

# Collect lag events during live trading
collector = LagDataCollector()
collector.record_event(
    binance_timestamp=...,
    binance_price=...,
    polymarket_timestamp=...,
    ...
)
collector.save()

# Analyze collected data
analyzer = LagAnalyzer()
distribution = analyzer.analyze_lag_distribution(collector.load())
optimal_window = analyzer.optimal_lag_window(distribution, target_capture_rate=0.90)
```

---

#### `validation.py`

Backtests and calibration analysis.

**Backtest features:**
- Realistic fee modeling (3% round-trip)
- Train/test split (70/30)
- Kelly or fixed position sizing
- Full P&L and risk metrics

**Calibration features:**
- Brier score (lower is better)
- Log loss
- Hosmer-Lemeshow test (p > 0.05 = well-calibrated)
- Reliability diagram data

**Usage:**
```python
from research.analysis.validation import BacktestValidator, CalibrationAnalyzer

# Backtest
validator = BacktestValidator(fee_rate=0.03, min_edge_threshold=0.05)
result = validator.run(features_df, position_size=100.0, train_fraction=0.7)

print(f"Trades: {result.total_trades}")
print(f"Win rate: {result.win_rate:.1%}")
print(f"Net P&L: ${result.net_pnl:,.2f}")
print(f"Sharpe: {result.sharpe_ratio:.2f}")

# Calibration
cal_analyzer = CalibrationAnalyzer(n_bins=10)
cal_result = cal_analyzer.analyze_from_surface(surface, test_df)

print(f"Brier score: {cal_result.brier_score:.4f}")
print(f"Well-calibrated: {cal_result.is_calibrated}")
```

---

## Output Files

After running `python research/run_research.py --all`:

```
research/output/
├── models/
│   ├── BTCUSDT_15m_surface.json     # Full probability model
│   ├── BTCUSDT_15m_surface.csv      # Surface as CSV
│   ├── BTCUSDT_15m_lookup.csv       # Flat lookup table
│   └── BTCUSDT_15m_lookup.parquet   # Fast-loading format
└── reports/
    ├── BTCUSDT_15m_volatility.txt   # Volatility regime analysis
    ├── BTCUSDT_15m_sessions.txt     # Session analysis
    ├── BTCUSDT_15m_validation.txt   # Backtest & calibration results
    ├── BTCUSDT_15m_prob_by_deviation.csv
    └── BTCUSDT_15m_prob_by_time.csv
```

---

## Strategy Integration

| Strategy Tier | Uses From Research |
|---------------|-------------------|
| **Tier 1: Math Arb** | Nothing (pure spread arbitrage) |
| **Tier 2: Lag Arb Tilt** | Probability surface + lag timing |
| **Tier 3: Directional** | Probability at extreme deviations |
| **Tier 4: Late Certainty** | Probability with <2 min remaining |

**Integration example:**
```python
from research.models.edge_calculator import EdgeCalculator, StrategyIntegration

integration = StrategyIntegration(calculator)

# Tier 2: Add tilt to lag arb positions
is_signal, opp = integration.evaluate_tier2_signal(
    deviation_pct=current_deviation,
    time_remaining=time_left,
    market_price_up=market_up,
    market_price_down=market_down
)

# Tier 4: Late certainty plays
is_signal, opp = integration.evaluate_tier4_signal(...)
```

---

## Validation Criteria

| Criterion | Threshold | Description |
|-----------|-----------|-------------|
| Minimum edge | >5% | Only flag opportunities with significant edge |
| Calibration | p > 0.05 | Hosmer-Lemeshow test passes |
| Sample size | ≥30 | Reliable bucket estimate |
| Positive P&L | >0 | Net profitable after 3% fees |

---

## Key Design Decisions

1. **Empirical over parametric**: Uses raw historical win rates rather than fitting a logistic regression. More robust to non-linear patterns.

2. **Wilson score intervals**: Better than normal approximation for small samples. Avoids impossible CI values (<0 or >1).

3. **Volatility segmentation**: Separate surfaces per vol regime since high-vol may flatten the deviation→outcome relationship.

4. **Conservative edge**: Uses CI lower bound by default, not point estimate. Reduces false positives.

5. **Fee-aware**: Edge calculator subtracts round-trip fees before signaling. 15m markets have 3% fees; 1H markets have 0%.

---

## Mathematical Details

### Wilson Score Confidence Interval

For proportion p̂ = wins/n with confidence level (1-α):

```
center = (p̂ + z²/2n) / (1 + z²/n)
spread = z × √[(p̂(1-p̂) + z²/4n) / n] / (1 + z²/n)

CI = [center - spread, center + spread]
```

Where z = Φ⁻¹(1 - α/2) ≈ 1.96 for 95% confidence.

### Kelly Criterion

Optimal fraction of bankroll to bet:

```
f* = (p × b - q) / b
```

Where:
- p = probability of winning
- q = 1 - p = probability of losing
- b = net odds (payout per dollar risked)

For binary markets: b = (1 - entry_price) / entry_price

### Brier Score

Measures prediction accuracy:

```
BS = (1/n) × Σ(predicted_i - actual_i)²
```

- 0 = perfect predictions
- 0.25 = random guessing on 50/50 outcomes
- Lower is better
