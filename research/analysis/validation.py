"""
Validation Framework

Validates the probability model through:
1. Backtesting: Simulated P&L with realistic fees
2. Calibration: Does predicted 60% actually win ~60%?
3. Out-of-sample testing: Performance on held-out data
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Results from a backtest simulation."""
    # Trade statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float

    # P&L
    gross_pnl: float
    fees_paid: float
    net_pnl: float

    # Risk metrics
    max_drawdown: float
    sharpe_ratio: float
    profit_factor: float

    # Per-trade statistics
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float

    # Position sizing
    total_capital_deployed: float
    roi: float

    # Trade breakdown
    trades_by_direction: dict = field(default_factory=dict)
    trades_by_session: dict = field(default_factory=dict)
    trades_by_vol_regime: dict = field(default_factory=dict)


@dataclass
class CalibrationResult:
    """Results from calibration analysis."""
    # Calibration buckets
    n_buckets: int
    bucket_stats: pd.DataFrame

    # Overall metrics
    brier_score: float  # Lower is better (0 = perfect)
    log_loss: float  # Lower is better
    calibration_error: float  # Mean absolute error between predicted and actual

    # Reliability diagram data
    predicted_probs: list
    actual_freqs: list
    bucket_sizes: list

    # Is well-calibrated?
    is_calibrated: bool  # Hosmer-Lemeshow test p > 0.05
    hl_statistic: float
    hl_p_value: float


class BacktestValidator:
    """
    Backtests the probability model with realistic assumptions.

    Simulates trading based on edge calculator signals and computes P&L.

    Assumptions:
    - Fee rate: 3% for 15m markets, 0% for 1H markets
    - Binary outcome: Win 1 - entry_price or lose entry_price
    - Position sizing: Fixed or Kelly-based

    Usage:
        validator = BacktestValidator(surface, fee_rate=0.03)
        result = validator.run(
            features_df,
            min_edge=0.05,
            position_size=100
        )
    """

    def __init__(
        self,
        fee_rate: float = 0.03,
        min_edge_threshold: float = 0.05,
        use_kelly_sizing: bool = False,
        max_kelly_fraction: float = 0.25
    ):
        self.fee_rate = fee_rate
        self.min_edge_threshold = min_edge_threshold
        self.use_kelly_sizing = use_kelly_sizing
        self.max_kelly_fraction = max_kelly_fraction

    def run(
        self,
        df: pd.DataFrame,
        position_size: float = 100.0,
        market_price_spread: float = 0.02,  # Simulate 2% spread from fair
        train_fraction: float = 0.7
    ) -> BacktestResult:
        """
        Run backtest on feature data.

        Args:
            df: Features DataFrame with columns:
                - deviation_pct, time_remaining, vol_regime, session
                - outcome (actual 0/1)
            position_size: Base position size in USD
            market_price_spread: How much market deviates from model fair price
            train_fraction: Fraction of data for training (rest is test)

        Returns:
            BacktestResult with full statistics
        """
        # Split train/test
        n_train = int(len(df) * train_fraction)
        train_df = df.iloc[:n_train]
        test_df = df.iloc[n_train:]

        logger.info(f"Training on {len(train_df)} samples, testing on {len(test_df)}")

        # Build probability model on training data
        from ..models.probability_surface import ProbabilitySurface
        surface = ProbabilitySurface()
        surface.fit(train_df)

        # Run backtest on test data
        trades = []

        # Only look at entry points (minute_index == 0 or specific times)
        # For simplicity, simulate one trade per unique window
        test_windows = test_df.drop_duplicates("window_start")

        for _, row in test_windows.iterrows():
            # Get model probability
            prob, ci_lower, ci_upper, is_reliable = surface.get_probability(
                deviation_pct=row["deviation_pct"],
                time_remaining=row["time_remaining"],
                vol_regime=row.get("vol_regime", "all")
            )

            # Simulate market price (adds spread from fair value)
            # If model says 55% UP, market might show 53% or 57%
            noise = np.random.uniform(-market_price_spread, market_price_spread)
            market_prob_up = max(0.01, min(0.99, prob + noise))

            # Calculate edge
            if prob > market_prob_up + self.min_edge_threshold:
                # Buy UP
                direction = "UP"
                entry_price = market_prob_up
                model_prob = prob
                edge = prob - market_prob_up
            elif (1 - prob) > (1 - market_prob_up) + self.min_edge_threshold:
                # Buy DOWN
                direction = "DOWN"
                entry_price = 1 - market_prob_up
                model_prob = 1 - prob
                edge = (1 - prob) - (1 - market_prob_up)
            else:
                # No trade
                continue

            # Skip if not reliable enough
            if not is_reliable:
                continue

            # Position sizing
            if self.use_kelly_sizing:
                win_payout = (1 - entry_price) * (1 - self.fee_rate)
                kelly = (model_prob * win_payout - (1 - model_prob) * entry_price) / win_payout
                kelly = max(0, min(self.max_kelly_fraction, kelly))
                trade_size = position_size * kelly
            else:
                trade_size = position_size

            if trade_size < 1:  # Minimum trade
                continue

            # Simulate outcome
            actual_outcome = row["outcome"]
            if direction == "UP":
                won = actual_outcome == 1
            else:
                won = actual_outcome == 0

            # Calculate P&L
            fees = trade_size * entry_price * self.fee_rate * 2  # Entry + exit

            if won:
                gross_pnl = trade_size * (1 - entry_price)  # Win 1 - entry
            else:
                gross_pnl = -trade_size * entry_price  # Lose entry

            net_pnl = gross_pnl - fees

            trades.append({
                "window_start": row["window_start"],
                "direction": direction,
                "entry_price": entry_price,
                "model_prob": model_prob,
                "edge": edge,
                "trade_size": trade_size,
                "won": won,
                "gross_pnl": gross_pnl,
                "fees": fees,
                "net_pnl": net_pnl,
                "session": row.get("session", "unknown"),
                "vol_regime": row.get("vol_regime", "unknown")
            })

        return self._compute_results(trades)

    def _compute_results(self, trades: list[dict]) -> BacktestResult:
        """Compute backtest statistics from trade list."""
        if len(trades) == 0:
            return BacktestResult(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                gross_pnl=0.0,
                fees_paid=0.0,
                net_pnl=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                profit_factor=0.0,
                avg_win=0.0,
                avg_loss=0.0,
                largest_win=0.0,
                largest_loss=0.0,
                total_capital_deployed=0.0,
                roi=0.0,
                trades_by_direction={},
                trades_by_session={},
                trades_by_vol_regime={}
            )

        df = pd.DataFrame(trades)

        total_trades = len(df)
        winning_trades = df["won"].sum()
        losing_trades = total_trades - winning_trades
        win_rate = winning_trades / total_trades

        gross_pnl = df["gross_pnl"].sum()
        fees_paid = df["fees"].sum()
        net_pnl = df["net_pnl"].sum()

        # Drawdown
        cumulative = df["net_pnl"].cumsum()
        running_max = cumulative.cummax()
        drawdowns = running_max - cumulative
        max_drawdown = drawdowns.max()

        # Sharpe (annualized, assuming ~2000 trades/year)
        daily_returns = df["net_pnl"]
        if daily_returns.std() > 0:
            sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(2000)
        else:
            sharpe_ratio = 0.0

        # Profit factor
        wins = df[df["net_pnl"] > 0]["net_pnl"].sum()
        losses = abs(df[df["net_pnl"] < 0]["net_pnl"].sum())
        profit_factor = wins / losses if losses > 0 else float("inf")

        # Per-trade stats
        win_df = df[df["won"]]
        loss_df = df[~df["won"]]

        avg_win = win_df["net_pnl"].mean() if len(win_df) > 0 else 0.0
        avg_loss = loss_df["net_pnl"].mean() if len(loss_df) > 0 else 0.0
        largest_win = df["net_pnl"].max()
        largest_loss = df["net_pnl"].min()

        total_capital = df["trade_size"].sum()
        roi = net_pnl / total_capital if total_capital > 0 else 0.0

        # Breakdowns
        trades_by_direction = df.groupby("direction").agg({
            "won": ["count", "sum", "mean"],
            "net_pnl": "sum"
        }).to_dict()

        trades_by_session = df.groupby("session").agg({
            "won": ["count", "mean"],
            "net_pnl": "sum"
        }).to_dict()

        trades_by_vol = df.groupby("vol_regime").agg({
            "won": ["count", "mean"],
            "net_pnl": "sum"
        }).to_dict()

        return BacktestResult(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            gross_pnl=gross_pnl,
            fees_paid=fees_paid,
            net_pnl=net_pnl,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            profit_factor=profit_factor,
            avg_win=avg_win,
            avg_loss=avg_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
            total_capital_deployed=total_capital,
            roi=roi,
            trades_by_direction=trades_by_direction,
            trades_by_session=trades_by_session,
            trades_by_vol_regime=trades_by_vol
        )


class CalibrationAnalyzer:
    """
    Analyzes calibration of probability predictions.

    A well-calibrated model should have:
    - Predictions of 60% should win ~60% of the time
    - Brier score close to 0
    - Hosmer-Lemeshow test p-value > 0.05

    Usage:
        analyzer = CalibrationAnalyzer()
        result = analyzer.analyze(predicted_probs, actual_outcomes)
    """

    def __init__(self, n_bins: int = 10):
        self.n_bins = n_bins

    def analyze(
        self,
        predicted: np.ndarray,
        actual: np.ndarray
    ) -> CalibrationResult:
        """
        Analyze calibration of predictions.

        Args:
            predicted: Array of predicted probabilities (0-1)
            actual: Array of actual outcomes (0 or 1)

        Returns:
            CalibrationResult with full analysis
        """
        predicted = np.array(predicted)
        actual = np.array(actual)

        # Brier score
        brier_score = np.mean((predicted - actual) ** 2)

        # Log loss
        eps = 1e-15
        clipped = np.clip(predicted, eps, 1 - eps)
        log_loss = -np.mean(actual * np.log(clipped) + (1 - actual) * np.log(1 - clipped))

        # Calibration by bins
        bin_edges = np.linspace(0, 1, self.n_bins + 1)
        bin_indices = np.digitize(predicted, bin_edges) - 1
        bin_indices = np.clip(bin_indices, 0, self.n_bins - 1)

        bucket_stats = []
        predicted_probs = []
        actual_freqs = []
        bucket_sizes = []

        for i in range(self.n_bins):
            mask = bin_indices == i
            n_in_bin = mask.sum()

            if n_in_bin > 0:
                mean_predicted = predicted[mask].mean()
                actual_freq = actual[mask].mean()
            else:
                mean_predicted = (bin_edges[i] + bin_edges[i + 1]) / 2
                actual_freq = 0.5

            bucket_stats.append({
                "bin_low": bin_edges[i],
                "bin_high": bin_edges[i + 1],
                "n_samples": n_in_bin,
                "mean_predicted": mean_predicted,
                "actual_frequency": actual_freq,
                "calibration_error": abs(mean_predicted - actual_freq) if n_in_bin > 0 else None
            })

            predicted_probs.append(mean_predicted)
            actual_freqs.append(actual_freq)
            bucket_sizes.append(n_in_bin)

        bucket_df = pd.DataFrame(bucket_stats)

        # Mean calibration error
        valid_errors = bucket_df[bucket_df["calibration_error"].notna()]["calibration_error"]
        calibration_error = valid_errors.mean() if len(valid_errors) > 0 else 0.5

        # Hosmer-Lemeshow test
        hl_stat, hl_p = self._hosmer_lemeshow(predicted, actual, bin_indices)

        is_calibrated = hl_p > 0.05

        return CalibrationResult(
            n_buckets=self.n_bins,
            bucket_stats=bucket_df,
            brier_score=brier_score,
            log_loss=log_loss,
            calibration_error=calibration_error,
            predicted_probs=predicted_probs,
            actual_freqs=actual_freqs,
            bucket_sizes=bucket_sizes,
            is_calibrated=is_calibrated,
            hl_statistic=hl_stat,
            hl_p_value=hl_p
        )

    def _hosmer_lemeshow(
        self,
        predicted: np.ndarray,
        actual: np.ndarray,
        bin_indices: np.ndarray
    ) -> tuple[float, float]:
        """
        Hosmer-Lemeshow goodness of fit test.

        H0: Model is well-calibrated
        Large p-value (> 0.05) = good calibration
        """
        hl_stat = 0.0

        for i in range(self.n_bins):
            mask = bin_indices == i
            n_i = mask.sum()

            if n_i == 0:
                continue

            o_i = actual[mask].sum()  # Observed positives
            e_i = predicted[mask].sum()  # Expected positives

            if e_i > 0 and (n_i - e_i) > 0:
                hl_stat += (o_i - e_i) ** 2 / (e_i * (1 - e_i / n_i))

        # Chi-square distribution with (n_bins - 2) degrees of freedom
        df = self.n_bins - 2
        p_value = 1 - stats.chi2.cdf(hl_stat, df) if df > 0 else 1.0

        return (hl_stat, p_value)

    def analyze_from_surface(
        self,
        surface,
        test_df: pd.DataFrame
    ) -> CalibrationResult:
        """
        Analyze calibration using a probability surface on test data.

        Args:
            surface: Fitted ProbabilitySurface
            test_df: Test features DataFrame

        Returns:
            CalibrationResult
        """
        predictions = []
        actuals = []

        for _, row in test_df.iterrows():
            prob, _, _, _ = surface.get_probability(
                deviation_pct=row["deviation_pct"],
                time_remaining=row["time_remaining"],
                vol_regime=row.get("vol_regime", "all")
            )
            predictions.append(prob)
            actuals.append(row["outcome"])

        return self.analyze(np.array(predictions), np.array(actuals))


def generate_validation_report(
    backtest_result: BacktestResult,
    calibration_result: CalibrationResult,
    output_path: Optional[str] = None
) -> str:
    """Generate a formatted validation report."""
    lines = []
    lines.append("=" * 60)
    lines.append("MODEL VALIDATION REPORT")
    lines.append("=" * 60)
    lines.append("")

    # Backtest section
    lines.append("1. BACKTEST RESULTS")
    lines.append("-" * 40)
    lines.append(f"  Total Trades: {backtest_result.total_trades:,}")
    lines.append(f"  Winning Trades: {backtest_result.winning_trades:,} ({backtest_result.win_rate:.1%})")
    lines.append(f"  Losing Trades: {backtest_result.losing_trades:,}")
    lines.append("")
    lines.append("  P&L Summary:")
    lines.append(f"    Gross P&L: ${backtest_result.gross_pnl:,.2f}")
    lines.append(f"    Fees Paid: ${backtest_result.fees_paid:,.2f}")
    lines.append(f"    Net P&L: ${backtest_result.net_pnl:,.2f}")
    lines.append(f"    ROI: {backtest_result.roi:.2%}")
    lines.append("")
    lines.append("  Risk Metrics:")
    lines.append(f"    Max Drawdown: ${backtest_result.max_drawdown:,.2f}")
    lines.append(f"    Sharpe Ratio: {backtest_result.sharpe_ratio:.2f}")
    lines.append(f"    Profit Factor: {backtest_result.profit_factor:.2f}")
    lines.append("")
    lines.append("  Per-Trade Stats:")
    lines.append(f"    Average Win: ${backtest_result.avg_win:,.2f}")
    lines.append(f"    Average Loss: ${backtest_result.avg_loss:,.2f}")
    lines.append(f"    Largest Win: ${backtest_result.largest_win:,.2f}")
    lines.append(f"    Largest Loss: ${backtest_result.largest_loss:,.2f}")

    # Calibration section
    lines.append("")
    lines.append("2. CALIBRATION ANALYSIS")
    lines.append("-" * 40)
    lines.append(f"  Brier Score: {calibration_result.brier_score:.4f} (lower is better)")
    lines.append(f"  Log Loss: {calibration_result.log_loss:.4f} (lower is better)")
    lines.append(f"  Mean Calibration Error: {calibration_result.calibration_error:.4f}")
    lines.append("")
    lines.append(f"  Hosmer-Lemeshow Test:")
    lines.append(f"    Statistic: {calibration_result.hl_statistic:.2f}")
    lines.append(f"    P-value: {calibration_result.hl_p_value:.4f}")
    lines.append(f"    Well-calibrated: {'YES' if calibration_result.is_calibrated else 'NO'}")

    lines.append("")
    lines.append("  Reliability Diagram Data:")
    lines.append("    Predicted | Actual | N")
    lines.append("    " + "-" * 30)
    for i in range(len(calibration_result.predicted_probs)):
        if calibration_result.bucket_sizes[i] > 0:
            lines.append(
                f"    {calibration_result.predicted_probs[i]:8.1%} | "
                f"{calibration_result.actual_freqs[i]:6.1%} | "
                f"{calibration_result.bucket_sizes[i]:,}"
            )

    # Verdict
    lines.append("")
    lines.append("3. VERDICT")
    lines.append("-" * 40)

    passed = []
    failed = []

    # Check criteria
    if backtest_result.net_pnl > 0:
        passed.append("Positive net P&L after fees")
    else:
        failed.append("Negative net P&L")

    if calibration_result.is_calibrated:
        passed.append("Model is well-calibrated (HL p > 0.05)")
    else:
        failed.append("Model is poorly calibrated")

    if backtest_result.win_rate >= 0.5:
        passed.append(f"Win rate >= 50% ({backtest_result.win_rate:.1%})")
    else:
        failed.append(f"Win rate < 50% ({backtest_result.win_rate:.1%})")

    if backtest_result.sharpe_ratio > 0.5:
        passed.append(f"Sharpe ratio > 0.5 ({backtest_result.sharpe_ratio:.2f})")
    else:
        failed.append(f"Sharpe ratio < 0.5 ({backtest_result.sharpe_ratio:.2f})")

    lines.append("  PASSED:")
    for p in passed:
        lines.append(f"    [+] {p}")

    if failed:
        lines.append("  FAILED:")
        for f in failed:
            lines.append(f"    [-] {f}")

    overall = "PASS" if len(failed) == 0 else "NEEDS IMPROVEMENT"
    lines.append("")
    lines.append(f"  OVERALL: {overall}")

    report = "\n".join(lines)

    if output_path:
        with open(output_path, "w") as f:
            f.write(report)
        logger.info(f"Report saved to {output_path}")

    return report


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    print("Validation module loaded successfully")
