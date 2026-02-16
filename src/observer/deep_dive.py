"""Deep-dive analysis of Gabagool's trading parameters.

Reads observer data from SQLite, produces an HTML report with embedded charts.
Run:  uv run python -m observer.deep_dive [--session SESSION_ID] [--db data/observer.db]
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import sqlite3
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import seaborn as sns

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
CHART_DIR = Path("data/analysis/charts")
REPORT_PATH = Path("data/analysis/deep_dive_report.html")
DPI = 120
sns.set_theme(style="darkgrid", palette="muted")
plt.rcParams.update({"figure.max_open_warning": 50})

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts_to_dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _parse_timeframe(slug: str) -> str:
    if slug.startswith("btc-updown-5m-"):
        return "BTC-5m"
    if slug.startswith("btc-updown-15m-"):
        return "BTC-15m"
    if slug.startswith("eth-updown-5m-"):
        return "ETH-5m"
    if slug.startswith("eth-updown-15m-"):
        return "ETH-15m"
    if slug.startswith("bitcoin-up-or-down"):
        return "BTC-1h"
    if slug.startswith("ethereum-up-or-down"):
        return "ETH-1h"
    return "OTHER"


def _parse_asset(slug: str) -> str:
    if slug.startswith(("btc-", "bitcoin-")):
        return "BTC"
    if slug.startswith(("eth-", "ethereum-")):
        return "ETH"
    return "OTHER"


def _fig_to_base64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _save_and_embed(fig: plt.Figure, name: str) -> str:
    """Save chart to disk and return <img> tag with base64 data."""
    path = CHART_DIR / f"{name}.png"
    fig.savefig(path, format="png", dpi=DPI, bbox_inches="tight")
    b64 = _fig_to_base64(fig)
    plt.close(fig)
    return f'<img src="data:image/png;base64,{b64}" alt="{name}" style="max-width:100%;margin:10px 0;">'


def _price_bucket(price: float, width: float = 0.05) -> float:
    """Round price to nearest bucket centre."""
    return round(round(price / width) * width, 4)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(db_path: str, session_id: str | None) -> dict[str, pd.DataFrame]:
    """Load all tables into DataFrames, optionally filtered by session."""
    conn = sqlite3.connect(db_path)
    where = f" WHERE session_id = '{session_id}'" if session_id else ""
    dfs = {}
    for table in [
        "obs_trades", "obs_merges", "obs_positions", "obs_position_changes",
        "obs_prices", "obs_redemptions", "obs_market_windows", "obs_book_snapshots",
        "obs_sessions", "obs_balance_snapshots", "obs_usdc_transfers",
    ]:
        try:
            q = f"SELECT * FROM {table}"
            if table != "obs_sessions" and session_id:
                q += where
            dfs[table] = pd.read_sql_query(q, conn)
        except Exception:
            dfs[table] = pd.DataFrame()
    conn.close()

    # Augment trades
    t = dfs["obs_trades"]
    if not t.empty:
        t["timeframe"] = t["slug"].apply(_parse_timeframe)
        t["asset_type"] = t["slug"].apply(_parse_asset)
        t["dt"] = t["ts"].apply(_ts_to_dt)
    dfs["obs_trades"] = t
    return dfs


# ===================================================================
# Section 1: Data Summary
# ===================================================================

def section_summary(dfs: dict) -> tuple[str, list]:
    t = dfs["obs_trades"]
    if t.empty:
        return "<p>No trade data.</p>", []

    sess = dfs["obs_sessions"]
    n_trades = len(t)
    total_vol = t["usdc_size"].sum()
    n_markets = t["slug"].nunique()
    maker_n = (t["role"] == "MAKER").sum()
    taker_n = (t["role"] == "TAKER").sum()
    maker_pct = maker_n / n_trades * 100
    taker_pct = taker_n / n_trades * 100

    ts_min, ts_max = t["ts"].min(), t["ts"].max()
    duration_min = (ts_max - ts_min) / 60

    # Timeframe breakdown
    tf = t.groupby("timeframe").agg(
        trades=("id", "count"),
        volume=("usdc_size", "sum"),
        markets=("slug", "nunique"),
    ).sort_values("volume", ascending=False)

    html = f"""
    <table class="summary">
    <tr><td>Total trades</td><td><b>{n_trades:,}</b></td></tr>
    <tr><td>Total volume</td><td><b>${total_vol:,.2f}</b></td></tr>
    <tr><td>Unique markets</td><td><b>{n_markets}</b></td></tr>
    <tr><td>MAKER fills</td><td>{maker_n:,} ({maker_pct:.1f}%)</td></tr>
    <tr><td>TAKER fills</td><td>{taker_n:,} ({taker_pct:.1f}%)</td></tr>
    <tr><td>Session duration</td><td>{duration_min:.0f} min ({duration_min/60:.1f} hrs)</td></tr>
    <tr><td>Sessions</td><td>{len(sess)}</td></tr>
    </table>
    <h4>Timeframe Breakdown</h4>
    {tf.to_html(classes="data", float_format=lambda x: f"${x:,.2f}" if isinstance(x, float) else str(x))}
    """

    figs = []

    # Chart 1: trades + volume by timeframe (twin bar)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
    tf_sorted = tf.sort_values("volume", ascending=True)
    ax1.barh(tf_sorted.index, tf_sorted["trades"], color=sns.color_palette("muted")[0])
    ax1.set_xlabel("Trade count")
    ax1.set_title("Trades by Timeframe")
    ax2.barh(tf_sorted.index, tf_sorted["volume"], color=sns.color_palette("muted")[1])
    ax2.set_xlabel("Volume (USDC)")
    ax2.set_title("Volume by Timeframe")
    fig.tight_layout()
    figs.append(("s1_timeframe_bars", fig))

    # Chart 2: MAKER vs TAKER pie
    fig2, ax = plt.subplots(figsize=(5, 5))
    ax.pie([maker_n, taker_n], labels=["MAKER", "TAKER"],
           autopct="%1.1f%%", colors=sns.color_palette("muted")[:2],
           startangle=90)
    ax.set_title("Fill Role Distribution")
    figs.append(("s1_role_pie", fig2))

    imgs = "".join(_save_and_embed(f, n) for n, f in figs)
    return html + imgs, figs


# ===================================================================
# Section 2: Grid Parameter Extraction
# ===================================================================

def section_grid(dfs: dict) -> tuple[str, list]:
    t = dfs["obs_trades"]
    if t.empty:
        return "<p>No data.</p>", []

    # Top 10 markets by volume
    top_slugs = (
        t.groupby("slug")["usdc_size"].sum()
        .sort_values(ascending=False)
        .head(10)
        .index.tolist()
    )
    top = t[t["slug"].isin(top_slugs)].copy()
    top["bucket"] = top["price"].apply(lambda p: _price_bucket(p, 0.05))

    figs = []
    html_parts = []

    # Per-market grid table
    rows = []
    for slug in top_slugs:
        m = top[top["slug"] == slug]
        for outcome in ["Up", "Down"]:
            s = m[m["outcome"] == outcome]
            if s.empty:
                continue
            n_fills = len(s)
            avg_size = s["size"].mean()
            total_usdc = s["usdc_size"].sum()
            price_std = s["price"].std()
            mid = s["price"].median()
            within_10c = ((s["price"] - mid).abs() <= 0.10).sum()
            conc_ratio = within_10c / n_fills if n_fills else 0
            price_range = s["price"].max() - s["price"].min()
            rows.append({
                "market": slug[:40], "side": outcome, "fills": n_fills,
                "avg_size": round(avg_size, 2), "total_usdc": round(total_usdc, 2),
                "price_std": round(price_std, 4), "grid_width": round(price_range, 2),
                "concentration_ratio": round(conc_ratio, 2),
            })
    grid_df = pd.DataFrame(rows)
    html_parts.append("<h4>Per-Market Grid Parameters (Top 10)</h4>")
    html_parts.append(grid_df.to_html(classes="data", index=False))

    # Aggregate grid stats
    all_up = t[t["outcome"] == "Up"]
    all_down = t[t["outcome"] == "Down"]
    html_parts.append(f"""
    <h4>Aggregate Grid Stats</h4>
    <table class="summary">
    <tr><td>Up fills</td><td>{len(all_up):,} | avg price {all_up['price'].mean():.4f} | std {all_up['price'].std():.4f}</td></tr>
    <tr><td>Down fills</td><td>{len(all_down):,} | avg price {all_down['price'].mean():.4f} | std {all_down['price'].std():.4f}</td></tr>
    <tr><td>Avg fill size (shares)</td><td>{t['size'].mean():.2f}</td></tr>
    <tr><td>Median fill size (shares)</td><td>{t['size'].median():.2f}</td></tr>
    <tr><td>Avg fill USDC</td><td>${t['usdc_size'].mean():.2f}</td></tr>
    </table>
    """)

    # Chart: heatmap of fill count by price bucket × top market
    pivot = top.groupby(["slug", "bucket"]).size().unstack(fill_value=0)
    # Shorten slug labels
    pivot.index = [s[:35] for s in pivot.index]
    fig, ax = plt.subplots(figsize=(14, 6))
    sns.heatmap(pivot, ax=ax, cmap="YlOrRd", linewidths=0.3, cbar_kws={"label": "Fill count"})
    ax.set_title("Fill Count Heatmap: Price Bucket × Market (Top 10)")
    ax.set_xlabel("Price Bucket")
    ax.set_ylabel("Market")
    fig.tight_layout()
    figs.append(("s2_heatmap", fig))

    # Chart: overlaid Up vs Down fill-price histograms
    fig2, ax2 = plt.subplots(figsize=(10, 5))
    bins = np.arange(0, 1.05, 0.02)
    ax2.hist(all_up["price"], bins=bins, alpha=0.6, label="Up fills", color="green")
    ax2.hist(all_down["price"], bins=bins, alpha=0.6, label="Down fills", color="red")
    ax2.set_xlabel("Fill Price")
    ax2.set_ylabel("Count")
    ax2.set_title("Fill Price Distribution: Up vs Down")
    ax2.legend()
    fig2.tight_layout()
    figs.append(("s2_up_down_hist", fig2))

    # Chart: level spacing — distribution of unique prices per market
    prices_per_market = []
    for slug in top_slugs:
        m = t[t["slug"] == slug]
        unique_prices = sorted(m["price"].unique())
        if len(unique_prices) > 1:
            spacings = np.diff(unique_prices)
            prices_per_market.extend(spacings)

    if prices_per_market:
        fig3, ax3 = plt.subplots(figsize=(8, 4))
        ax3.hist(prices_per_market, bins=50, color=sns.color_palette("muted")[2], edgecolor="white")
        ax3.set_xlabel("Price Level Spacing")
        ax3.set_ylabel("Count")
        ax3.set_title("Distribution of Price Level Spacings (Top 10 Markets)")
        ax3.axvline(np.median(prices_per_market), color="red", linestyle="--",
                     label=f"Median: {np.median(prices_per_market):.3f}")
        ax3.legend()
        fig3.tight_layout()
        figs.append(("s2_spacing_dist", fig3))

    imgs = "".join(_save_and_embed(f, n) for n, f in figs)
    return "\n".join(html_parts) + imgs, figs


# ===================================================================
# Section 3: Fill Timing & Order Management
# ===================================================================

def section_timing(dfs: dict) -> tuple[str, list]:
    t = dfs["obs_trades"]
    if t.empty:
        return "<p>No data.</p>", []

    figs = []
    html_parts = []

    # Entry latency: time from window open to first fill
    # Parse window open from slug timestamp where available
    entry_rows = []
    for slug, grp in t.groupby("slug"):
        first_ts = grp["ts"].min()
        tf = _parse_timeframe(slug)
        # Try to extract window open from slug
        parts = slug.split("-")
        try:
            window_open = float(parts[-1])
            latency = first_ts - window_open
            if 0 < latency < 600:  # sanity: 0 to 10 min
                entry_rows.append({"slug": slug, "timeframe": tf, "latency_sec": latency})
        except (ValueError, IndexError):
            pass  # 1h slugs don't have epoch
    entry_df = pd.DataFrame(entry_rows)

    if not entry_df.empty:
        html_parts.append(f"""
        <h4>Entry Latency (seconds from window open to first fill)</h4>
        <table class="summary">
        <tr><td>Mean</td><td>{entry_df['latency_sec'].mean():.1f}s</td></tr>
        <tr><td>Median</td><td>{entry_df['latency_sec'].median():.1f}s</td></tr>
        <tr><td>Min</td><td>{entry_df['latency_sec'].min():.1f}s</td></tr>
        <tr><td>Max</td><td>{entry_df['latency_sec'].max():.1f}s</td></tr>
        </table>
        """)

        fig, ax = plt.subplots(figsize=(10, 5))
        for tf in entry_df["timeframe"].unique():
            sub = entry_df[entry_df["timeframe"] == tf]
            ax.scatter(sub.index, sub["latency_sec"], label=tf, alpha=0.7, s=40)
        ax.set_ylabel("Latency (seconds)")
        ax.set_xlabel("Market index")
        ax.set_title("Entry Latency by Timeframe")
        ax.legend()
        fig.tight_layout()
        figs.append(("s3_entry_latency", fig))

    # Inter-fill gaps
    inter_gaps = []
    for slug, grp in t.groupby("slug"):
        ts_sorted = grp.sort_values("ts")["ts"].values
        if len(ts_sorted) > 1:
            gaps = np.diff(ts_sorted)
            inter_gaps.extend(gaps)
    inter_gaps = np.array(inter_gaps)
    inter_gaps = inter_gaps[(inter_gaps > 0) & (inter_gaps < 300)]  # cap at 5 min

    html_parts.append(f"""
    <h4>Inter-Fill Gaps</h4>
    <table class="summary">
    <tr><td>Mean gap</td><td>{inter_gaps.mean():.2f}s</td></tr>
    <tr><td>Median gap</td><td>{np.median(inter_gaps):.2f}s</td></tr>
    <tr><td>% under 2s (burst)</td><td>{(inter_gaps < 2).mean() * 100:.1f}%</td></tr>
    <tr><td>% under 10s</td><td>{(inter_gaps < 10).mean() * 100:.1f}%</td></tr>
    </table>
    """)

    fig2, ax2 = plt.subplots(figsize=(10, 5))
    ax2.hist(inter_gaps[inter_gaps < 60], bins=100, color=sns.color_palette("muted")[3], edgecolor="white")
    ax2.set_xlabel("Gap (seconds)")
    ax2.set_ylabel("Count")
    ax2.set_title("Inter-Fill Gap Distribution (< 60s)")
    ax2.axvline(np.median(inter_gaps), color="red", linestyle="--",
                label=f"Median: {np.median(inter_gaps):.1f}s")
    ax2.legend()
    fig2.tight_layout()
    figs.append(("s3_inter_fill_gaps", fig2))

    # Side sequencing: which side fills first?
    seq_rows = []
    for slug, grp in t.groupby("slug"):
        up_first = grp[grp["outcome"] == "Up"]["ts"].min()
        down_first = grp[grp["outcome"] == "Down"]["ts"].min()
        if pd.notna(up_first) and pd.notna(down_first):
            first_side = "Up" if up_first <= down_first else "Down"
            delay = abs(up_first - down_first)
            seq_rows.append({"slug": slug, "first_side": first_side, "hedge_delay": delay})
    seq_df = pd.DataFrame(seq_rows)

    if not seq_df.empty:
        up_first_pct = (seq_df["first_side"] == "Up").mean() * 100
        html_parts.append(f"""
        <h4>Side Sequencing</h4>
        <table class="summary">
        <tr><td>Up fills first</td><td>{up_first_pct:.1f}%</td></tr>
        <tr><td>Down fills first</td><td>{100 - up_first_pct:.1f}%</td></tr>
        <tr><td>Mean hedge delay</td><td>{seq_df['hedge_delay'].mean():.1f}s</td></tr>
        <tr><td>Median hedge delay</td><td>{seq_df['hedge_delay'].median():.1f}s</td></tr>
        </table>
        """)

        fig3, ax3 = plt.subplots(figsize=(10, 4))
        ax3.hist(seq_df["hedge_delay"], bins=40, color=sns.color_palette("muted")[4], edgecolor="white")
        ax3.set_xlabel("Hedge Delay (seconds)")
        ax3.set_ylabel("Market count")
        ax3.set_title("Time Between First Up and First Down Fill")
        ax3.axvline(seq_df["hedge_delay"].median(), color="red", linestyle="--",
                     label=f"Median: {seq_df['hedge_delay'].median():.1f}s")
        ax3.legend()
        fig3.tight_layout()
        figs.append(("s3_hedge_delay", fig3))

    imgs = "".join(_save_and_embed(f, n) for n, f in figs)
    return "\n".join(html_parts) + imgs, figs


# ===================================================================
# Section 4: MAKER vs TAKER Strategy
# ===================================================================

def section_maker_taker(dfs: dict) -> tuple[str, list]:
    t = dfs["obs_trades"]
    books = dfs["obs_book_snapshots"]
    if t.empty:
        return "<p>No data.</p>", []

    figs = []
    html_parts = []

    maker = t[t["role"] == "MAKER"]
    taker = t[t["role"] == "TAKER"]

    # When does TAKER fire? Compute time-into-window for 5m/15m slugs
    taker_timing = []
    for _, row in taker.iterrows():
        slug = row["slug"]
        parts = slug.split("-")
        try:
            window_open = float(parts[-1])
            time_in = row["ts"] - window_open
            tf = _parse_timeframe(slug)
            if 0 < time_in < 3600:
                taker_timing.append({"time_in": time_in, "timeframe": tf,
                                     "price": row["price"], "outcome": row["outcome"]})
        except (ValueError, IndexError):
            pass
    taker_df = pd.DataFrame(taker_timing)

    maker_timing = []
    for _, row in maker.iterrows():
        slug = row["slug"]
        parts = slug.split("-")
        try:
            window_open = float(parts[-1])
            time_in = row["ts"] - window_open
            tf = _parse_timeframe(slug)
            if 0 < time_in < 3600:
                maker_timing.append({"time_in": time_in, "timeframe": tf})
        except (ValueError, IndexError):
            pass
    maker_df = pd.DataFrame(maker_timing)

    # TAKER breakdown
    html_parts.append(f"""
    <h4>MAKER vs TAKER Overview</h4>
    <table class="summary">
    <tr><td>MAKER fills</td><td>{len(maker):,} ({len(maker)/len(t)*100:.1f}%)</td></tr>
    <tr><td>TAKER fills</td><td>{len(taker):,} ({len(taker)/len(t)*100:.1f}%)</td></tr>
    <tr><td>MAKER avg fill USDC</td><td>${maker['usdc_size'].mean():.2f}</td></tr>
    <tr><td>TAKER avg fill USDC</td><td>${taker['usdc_size'].mean():.2f}</td></tr>
    <tr><td>TAKER avg price (Up)</td><td>{taker[taker['outcome']=='Up']['price'].mean():.4f}</td></tr>
    <tr><td>TAKER avg price (Down)</td><td>{taker[taker['outcome']=='Down']['price'].mean():.4f}</td></tr>
    </table>
    """)

    # TAKER by outcome
    taker_by_outcome = taker.groupby("outcome").agg(
        n=("id", "count"), vol=("usdc_size", "sum"), avg_price=("price", "mean")
    )
    html_parts.append("<h4>TAKER by Outcome</h4>")
    html_parts.append(taker_by_outcome.to_html(classes="data"))

    # Chart: TAKER % by time-into-window bucket
    if not taker_df.empty and not maker_df.empty:
        taker_df["bucket_30s"] = (taker_df["time_in"] // 30) * 30
        maker_df["bucket_30s"] = (maker_df["time_in"] // 30) * 30
        taker_counts = taker_df.groupby("bucket_30s").size()
        maker_counts = maker_df.groupby("bucket_30s").size()
        all_buckets = sorted(set(taker_counts.index) | set(maker_counts.index))
        taker_pcts = []
        for b in all_buckets:
            tc = taker_counts.get(b, 0)
            mc = maker_counts.get(b, 0)
            total = tc + mc
            taker_pcts.append(tc / total * 100 if total > 0 else 0)

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.bar(all_buckets, taker_pcts, width=25, color=sns.color_palette("muted")[5])
        ax.set_xlabel("Time into Window (seconds)")
        ax.set_ylabel("TAKER %")
        ax.set_title("TAKER Fill Percentage by Time into Window")
        fig.tight_layout()
        figs.append(("s4_taker_by_time", fig))

    # Chart: fill price vs book best bid/ask
    # For each trade, find nearest book snapshot for same token
    if not books.empty and "token_id" in books.columns:
        # Use a simplified join — for each trade, find book snapshot within 30s
        sample_trades = t.head(2000).copy()  # limit for perf
        book_comparisons = []
        for _, trade in sample_trades.iterrows():
            token = trade["asset"]
            ts = trade["ts"]
            near = books[(books["token_id"] == token) & ((books["ts"] - ts).abs() < 30)]
            if not near.empty:
                closest = near.iloc[(near["ts"] - ts).abs().argsort()[:1]]
                book_comparisons.append({
                    "trade_price": trade["price"],
                    "role": trade["role"],
                    "outcome": trade["outcome"],
                    "best_bid": closest["best_bid"].values[0],
                    "best_ask": closest["best_ask"].values[0],
                })

        if book_comparisons:
            bc = pd.DataFrame(book_comparisons)
            bc = bc[(bc["best_bid"] > 0) & (bc["best_ask"] > 0)]
            if not bc.empty:
                fig2, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
                maker_bc = bc[bc["role"] == "MAKER"]
                taker_bc = bc[bc["role"] == "TAKER"]
                if not maker_bc.empty:
                    ax1.scatter(maker_bc["best_bid"], maker_bc["trade_price"],
                                alpha=0.3, s=15, c="blue", label="MAKER fills")
                    ax1.plot([0, 1], [0, 1], "r--", alpha=0.5)
                    ax1.set_xlabel("Book Best Bid")
                    ax1.set_ylabel("Fill Price")
                    ax1.set_title("MAKER Fill Price vs Best Bid")
                    ax1.legend()
                if not taker_bc.empty:
                    ax2.scatter(taker_bc["best_ask"], taker_bc["trade_price"],
                                alpha=0.3, s=15, c="orange", label="TAKER fills")
                    ax2.plot([0, 1], [0, 1], "r--", alpha=0.5)
                    ax2.set_xlabel("Book Best Ask")
                    ax2.set_ylabel("Fill Price")
                    ax2.set_title("TAKER Fill Price vs Best Ask")
                    ax2.legend()
                fig2.tight_layout()
                figs.append(("s4_price_vs_book", fig2))

    imgs = "".join(_save_and_embed(f, n) for n, f in figs)
    return "\n".join(html_parts) + imgs, figs


# ===================================================================
# Section 5: Edge & P&L Estimation
# ===================================================================

def section_edge_pnl(dfs: dict) -> tuple[str, list]:
    t = dfs["obs_trades"]
    mw = dfs["obs_market_windows"]
    merges = dfs["obs_merges"]
    redemptions = dfs["obs_redemptions"]
    if t.empty:
        return "<p>No data.</p>", []

    figs = []
    html_parts = []

    # Compute per-market VWAP from trades
    market_stats = []
    for slug, grp in t.groupby("slug"):
        up = grp[grp["outcome"] == "Up"]
        down = grp[grp["outcome"] == "Down"]
        up_vwap = (up["price"] * up["size"]).sum() / up["size"].sum() if not up.empty else 0
        down_vwap = (down["price"] * down["size"]).sum() / down["size"].sum() if not down.empty else 0
        up_shares = up["size"].sum()
        down_shares = down["size"].sum()
        up_cost = up["usdc_size"].sum()
        down_cost = down["usdc_size"].sum()
        combined = up_vwap + down_vwap if (up_vwap > 0 and down_vwap > 0) else 0
        edge = 1 - combined if combined > 0 else 0
        mergeable = min(up_shares, down_shares)
        tf = _parse_timeframe(slug)
        # hedge delay
        up_first = up["ts"].min() if not up.empty else None
        down_first = down["ts"].min() if not down.empty else None
        hd = abs(up_first - down_first) if (up_first is not None and down_first is not None) else None

        market_stats.append({
            "slug": slug, "timeframe": tf, "asset": _parse_asset(slug),
            "up_vwap": round(up_vwap, 4), "down_vwap": round(down_vwap, 4),
            "combined": round(combined, 4), "edge": round(edge, 4),
            "up_shares": round(up_shares, 2), "down_shares": round(down_shares, 2),
            "up_cost": round(up_cost, 2), "down_cost": round(down_cost, 2),
            "mergeable": round(mergeable, 2), "hedge_delay": hd,
        })
    ms = pd.DataFrame(market_stats)
    hedged = ms[ms["combined"] > 0]

    # Summary stats
    total_mergeable = hedged["mergeable"].sum()
    avg_edge = hedged["edge"].mean()
    median_edge = hedged["edge"].median()
    total_up_cost = ms["up_cost"].sum()
    total_down_cost = ms["down_cost"].sum()

    # P&L estimate — gas ~0.01 per merge, count from obs_merges
    n_merges = len(merges)
    gas_estimate = n_merges * 0.01
    gross_profit = (hedged["mergeable"] * hedged["edge"]).sum()
    net_profit = gross_profit - gas_estimate

    html_parts.append(f"""
    <h4>Edge & P&L Summary</h4>
    <table class="summary">
    <tr><td>Hedged markets (both sides)</td><td>{len(hedged)}</td></tr>
    <tr><td>Total mergeable shares</td><td>{total_mergeable:,.2f}</td></tr>
    <tr><td>Average edge (hedged)</td><td>{avg_edge:.4f} ({avg_edge*100:.2f}%)</td></tr>
    <tr><td>Median edge (hedged)</td><td>{median_edge:.4f} ({median_edge*100:.2f}%)</td></tr>
    <tr><td>Total Up cost</td><td>${total_up_cost:,.2f}</td></tr>
    <tr><td>Total Down cost</td><td>${total_down_cost:,.2f}</td></tr>
    <tr><td>Merges observed</td><td>{n_merges}</td></tr>
    <tr><td>Redemptions observed</td><td>{len(redemptions)}</td></tr>
    <tr><td>Gross merge profit estimate</td><td>${gross_profit:,.2f}</td></tr>
    <tr><td>Gas estimate ({n_merges} merges)</td><td>${gas_estimate:,.2f}</td></tr>
    <tr><td><b>Net P&L estimate</b></td><td><b>${net_profit:,.2f}</b></td></tr>
    </table>
    """)

    # Top markets table
    html_parts.append("<h4>Per-Market Edge (hedged only, sorted by edge)</h4>")
    hedged_display = hedged.sort_values("edge", ascending=False)[
        ["slug", "timeframe", "up_vwap", "down_vwap", "combined", "edge",
         "mergeable", "hedge_delay"]
    ].copy()
    hedged_display["slug"] = hedged_display["slug"].str[:40]
    html_parts.append(hedged_display.to_html(classes="data", index=False, float_format="%.4f"))

    # Chart: edge histogram
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(hedged["edge"], bins=30, color=sns.color_palette("muted")[2], edgecolor="white")
    ax.set_xlabel("Edge (1 - up_vwap - down_vwap)")
    ax.set_ylabel("Market count")
    ax.set_title("Per-Market Edge Distribution")
    ax.axvline(hedged["edge"].median(), color="red", linestyle="--",
               label=f"Median: {hedged['edge'].median():.4f}")
    ax.axvline(0, color="black", linestyle="-", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    figs.append(("s5_edge_hist", fig))

    # Chart: edge vs hedge delay
    has_hd = hedged.dropna(subset=["hedge_delay"])
    if not has_hd.empty:
        fig2, ax2 = plt.subplots(figsize=(10, 5))
        colors = {"BTC-5m": "blue", "BTC-15m": "green", "BTC-1h": "red",
                   "ETH-5m": "cyan", "ETH-15m": "lime", "ETH-1h": "orange"}
        for tf in has_hd["timeframe"].unique():
            sub = has_hd[has_hd["timeframe"] == tf]
            ax2.scatter(sub["hedge_delay"], sub["edge"], label=tf, alpha=0.7, s=50,
                        color=colors.get(tf, "gray"))
        ax2.set_xlabel("Hedge Delay (seconds)")
        ax2.set_ylabel("Edge")
        ax2.set_title("Edge vs Hedge Delay")
        ax2.legend()
        fig2.tight_layout()
        figs.append(("s5_edge_vs_delay", fig2))

    # Chart: box plot edge by timeframe
    if not hedged.empty:
        fig3, ax3 = plt.subplots(figsize=(10, 5))
        tf_order = ["BTC-5m", "BTC-15m", "BTC-1h", "ETH-5m", "ETH-15m", "ETH-1h"]
        present = [tf for tf in tf_order if tf in hedged["timeframe"].values]
        if present:
            sns.boxplot(data=hedged[hedged["timeframe"].isin(present)],
                        x="timeframe", y="edge", order=present, ax=ax3)
            ax3.set_title("Edge by Timeframe")
            ax3.axhline(0, color="red", linestyle="--", alpha=0.4)
            fig3.tight_layout()
            figs.append(("s5_edge_boxplot", fig3))
        else:
            plt.close(fig3)

    imgs = "".join(_save_and_embed(f, n) for n, f in figs)
    return "\n".join(html_parts) + imgs, figs


# ===================================================================
# Section 6: Position Lifecycle Trace
# ===================================================================

def section_lifecycle(dfs: dict) -> tuple[str, list]:
    t = dfs["obs_trades"]
    if t.empty:
        return "<p>No data.</p>", []

    figs = []
    html_parts = []

    # Pick best, worst, median edge markets
    market_edges = {}
    for slug, grp in t.groupby("slug"):
        up = grp[grp["outcome"] == "Up"]
        down = grp[grp["outcome"] == "Down"]
        if up.empty or down.empty:
            continue
        up_vwap = (up["price"] * up["size"]).sum() / up["size"].sum()
        down_vwap = (down["price"] * down["size"]).sum() / down["size"].sum()
        edge = 1 - up_vwap - down_vwap
        market_edges[slug] = edge

    if len(market_edges) < 3:
        return "<p>Not enough hedged markets for lifecycle trace.</p>", []

    sorted_edges = sorted(market_edges.items(), key=lambda x: x[1])
    best = sorted_edges[-1]
    worst = sorted_edges[0]
    median_idx = len(sorted_edges) // 2
    median_m = sorted_edges[median_idx]

    for label, (slug, edge) in [("Best", best), ("Median", median_m), ("Worst", worst)]:
        grp = t[t["slug"] == slug].sort_values("ts")
        html_parts.append(f"<h4>{label} Market: {slug[:50]} (edge={edge:.4f})</h4>")

        # Build running position
        rows = []
        up_shares, down_shares, up_cost, down_cost = 0, 0, 0, 0
        for _, row in grp.iterrows():
            if row["outcome"] == "Up":
                up_shares += row["size"]
                up_cost += row["usdc_size"]
            else:
                down_shares += row["size"]
                down_cost += row["usdc_size"]
            up_vwap = up_cost / up_shares if up_shares > 0 else 0
            down_vwap = down_cost / down_shares if down_shares > 0 else 0
            rows.append({
                "ts": row["ts"], "side": row["outcome"], "price": row["price"],
                "size": row["size"], "role": row["role"],
                "up_shares": up_shares, "down_shares": down_shares,
                "up_vwap": round(up_vwap, 4), "down_vwap": round(down_vwap, 4),
                "running_combined": round(up_vwap + down_vwap, 4) if (up_shares > 0 and down_shares > 0) else None,
            })

        lc = pd.DataFrame(rows)
        # Summary table (first 20 fills)
        display_cols = ["ts", "side", "price", "size", "role", "up_shares", "down_shares", "up_vwap", "down_vwap", "running_combined"]
        html_parts.append(lc[display_cols].head(20).to_html(classes="data", index=False, float_format="%.4f"))
        if len(lc) > 20:
            html_parts.append(f"<p><i>... showing 20 of {len(lc)} fills</i></p>")

        # Chart
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
        t_arr = lc["ts"] - lc["ts"].iloc[0]  # relative seconds
        ax1.step(t_arr, lc["up_shares"], where="post", label="Up shares", color="green")
        ax1.step(t_arr, lc["down_shares"], where="post", label="Down shares", color="red")
        ax1.set_ylabel("Shares")
        ax1.set_title(f"{label}: {slug[:40]} — Position Growth")
        ax1.legend()

        combined = lc["running_combined"].dropna()
        if not combined.empty:
            ax2.plot(t_arr[combined.index], combined, label="Combined VWAP", color="purple")
            ax2.axhline(1.0, color="black", linestyle="--", alpha=0.3, label="Break-even")
            ax2.set_xlabel("Seconds from First Fill")
            ax2.set_ylabel("Up VWAP + Down VWAP")
            ax2.set_title(f"Running Combined VWAP")
            ax2.legend()

        fig.tight_layout()
        figs.append((f"s6_lifecycle_{label.lower()}", fig))

    imgs = "".join(_save_and_embed(f, n) for n, f in figs)
    return "\n".join(html_parts) + imgs, figs


# ===================================================================
# Section 7: Market Selection & Capital Allocation
# ===================================================================

def section_allocation(dfs: dict) -> tuple[str, list]:
    t = dfs["obs_trades"]
    if t.empty:
        return "<p>No data.</p>", []

    figs = []
    html_parts = []

    # Capital per timeframe
    tf_vol = t.groupby("timeframe")["usdc_size"].sum().sort_values(ascending=False)
    html_parts.append("<h4>Capital Allocation by Timeframe</h4>")
    html_parts.append(tf_vol.to_frame("Volume (USDC)").to_html(classes="data", float_format="$%.2f"))

    # BTC vs ETH
    asset_vol = t.groupby("asset_type")["usdc_size"].sum()
    btc_vol = asset_vol.get("BTC", 0)
    eth_vol = asset_vol.get("ETH", 0)
    ratio = btc_vol / eth_vol if eth_vol > 0 else float("inf")
    html_parts.append(f"""
    <h4>BTC vs ETH</h4>
    <table class="summary">
    <tr><td>BTC volume</td><td>${btc_vol:,.2f}</td></tr>
    <tr><td>ETH volume</td><td>${eth_vol:,.2f}</td></tr>
    <tr><td>BTC:ETH ratio</td><td>{ratio:.1f}:1</td></tr>
    </table>
    """)

    # Per-market capital
    mkt_vol = t.groupby("slug")["usdc_size"].sum().sort_values(ascending=False)
    html_parts.append(f"""
    <h4>Capital per Market</h4>
    <table class="summary">
    <tr><td>Mean per market</td><td>${mkt_vol.mean():,.2f}</td></tr>
    <tr><td>Median per market</td><td>${mkt_vol.median():,.2f}</td></tr>
    <tr><td>Max per market</td><td>${mkt_vol.max():,.2f}</td></tr>
    <tr><td>Min per market</td><td>${mkt_vol.min():,.2f}</td></tr>
    </table>
    """)

    # Chart: stacked bar — capital by timeframe, split into 15-min time buckets
    t_copy = t.copy()
    ts_min = t_copy["ts"].min()
    t_copy["time_bucket"] = ((t_copy["ts"] - ts_min) // 900).astype(int) * 15  # minutes
    pivot = t_copy.groupby(["time_bucket", "timeframe"])["usdc_size"].sum().unstack(fill_value=0)

    fig, ax = plt.subplots(figsize=(14, 5))
    pivot.plot.bar(stacked=True, ax=ax, width=0.8)
    ax.set_xlabel("Minutes from Session Start")
    ax.set_ylabel("Volume (USDC)")
    ax.set_title("Capital Deployment Over Time by Timeframe")
    ax.legend(title="Timeframe", bbox_to_anchor=(1.05, 1))
    fig.tight_layout()
    figs.append(("s7_capital_over_time", fig))

    # Chart: concurrent market count
    # Count distinct slugs active per 60s bucket
    t_copy["minute_bucket"] = ((t_copy["ts"] - ts_min) // 60).astype(int)
    concurrent = t_copy.groupby("minute_bucket")["slug"].nunique()
    fig2, ax2 = plt.subplots(figsize=(12, 4))
    ax2.plot(concurrent.index, concurrent.values, color=sns.color_palette("muted")[0])
    ax2.fill_between(concurrent.index, concurrent.values, alpha=0.3)
    ax2.set_xlabel("Minutes from Session Start")
    ax2.set_ylabel("Active Markets")
    ax2.set_title("Concurrent Active Markets Over Time")
    fig2.tight_layout()
    figs.append(("s7_concurrent_markets", fig2))

    imgs = "".join(_save_and_embed(f, n) for n, f in figs)
    return "\n".join(html_parts) + imgs, figs


# ===================================================================
# Section 8: Volatility Regime Overlay
# ===================================================================

def section_volatility(dfs: dict) -> tuple[str, list]:
    t = dfs["obs_trades"]
    prices = dfs["obs_prices"]
    if t.empty or prices.empty:
        return "<p>No data (need both trades and price snapshots).</p>", []

    figs = []
    html_parts = []

    # BTC price path + trade activity
    ts_min = t["ts"].min()
    t_copy = t.copy()
    t_copy["minute"] = ((t_copy["ts"] - ts_min) // 60).astype(int)
    trade_per_min = t_copy.groupby("minute").size()

    prices_sorted = prices.sort_values("ts")
    prices_sorted["minute"] = ((prices_sorted["ts"] - ts_min) // 60).astype(int)

    fig, ax1 = plt.subplots(figsize=(14, 5))
    ax2 = ax1.twinx()
    ax1.plot(prices_sorted["minute"], prices_sorted["btc_price"], color="orange", alpha=0.8, label="BTC Price")
    ax2.bar(trade_per_min.index, trade_per_min.values, alpha=0.4, color="blue", label="Trades/min")
    ax1.set_xlabel("Minutes from Session Start")
    ax1.set_ylabel("BTC Price", color="orange")
    ax2.set_ylabel("Trades per Minute", color="blue")
    ax1.set_title("BTC Price vs Trade Activity")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
    fig.tight_layout()
    figs.append(("s8_btc_vs_trades", fig))

    # Edge vs BTC 5m rolling vol
    # For each market, find BTC vol at time of first fill
    vol_edge_rows = []
    for slug, grp in t.groupby("slug"):
        up = grp[grp["outcome"] == "Up"]
        down = grp[grp["outcome"] == "Down"]
        if up.empty or down.empty:
            continue
        up_vwap = (up["price"] * up["size"]).sum() / up["size"].sum()
        down_vwap = (down["price"] * down["size"]).sum() / down["size"].sum()
        edge = 1 - up_vwap - down_vwap
        first_ts = grp["ts"].min()
        # Find nearest price snapshot
        near = prices_sorted.iloc[(prices_sorted["ts"] - first_ts).abs().argsort()[:1]]
        if not near.empty:
            vol = near["btc_rolling_vol_5m"].values[0]
            vol_edge_rows.append({"slug": slug, "edge": edge, "btc_vol_5m": vol})
    ve = pd.DataFrame(vol_edge_rows)

    if not ve.empty and ve["btc_vol_5m"].sum() > 0:
        fig2, ax = plt.subplots(figsize=(10, 5))
        ax.scatter(ve["btc_vol_5m"], ve["edge"], alpha=0.6, s=50, color=sns.color_palette("muted")[3])
        ax.set_xlabel("BTC 5m Rolling Vol at First Fill")
        ax.set_ylabel("Market Edge")
        ax.set_title("Edge vs BTC Volatility at Entry")
        ax.axhline(0, color="red", linestyle="--", alpha=0.3)
        fig2.tight_layout()
        figs.append(("s8_edge_vs_vol", fig2))

    # Fill rate vs vol
    # Bucket by 5-min windows
    t_copy["bucket_5m"] = ((t_copy["ts"] - ts_min) // 300).astype(int)
    fill_rate = t_copy.groupby("bucket_5m").size()
    prices_sorted["bucket_5m"] = ((prices_sorted["ts"] - ts_min) // 300).astype(int)
    vol_by_bucket = prices_sorted.groupby("bucket_5m")["btc_rolling_vol_5m"].mean()

    common_buckets = sorted(set(fill_rate.index) & set(vol_by_bucket.index))
    if common_buckets and vol_by_bucket.loc[common_buckets].sum() > 0:
        fig3, ax = plt.subplots(figsize=(10, 5))
        ax.scatter(vol_by_bucket.loc[common_buckets],
                   fill_rate.loc[common_buckets],
                   alpha=0.6, s=50, color=sns.color_palette("muted")[4])
        ax.set_xlabel("BTC 5m Rolling Vol (5-min bucket avg)")
        ax.set_ylabel("Fill Count (5-min bucket)")
        ax.set_title("Fill Rate vs Volatility")
        fig3.tight_layout()
        figs.append(("s8_fillrate_vs_vol", fig3))

    imgs = "".join(_save_and_embed(f, n) for n, f in figs)
    return "\n".join(html_parts) + imgs, figs


# ===================================================================
# Section 9: Actionable Cheat Sheet
# ===================================================================

def section_cheat_sheet(dfs: dict) -> tuple[str, list]:
    t = dfs["obs_trades"]
    if t.empty:
        return "<p>No data.</p>", []

    # Compute all the key parameters
    # Grid levels: unique prices per market, avg across all markets
    levels_per_market = t.groupby("slug")["price"].nunique()
    avg_levels = levels_per_market.mean()

    # Grid spacing
    spacings = []
    for slug, grp in t.groupby("slug"):
        for outcome in ["Up", "Down"]:
            s = grp[grp["outcome"] == outcome]
            prices = sorted(s["price"].unique())
            if len(prices) > 1:
                spacings.extend(np.diff(prices))
    median_spacing = np.median(spacings) if spacings else 0

    # Size curve
    avg_fill_size = t["size"].mean()
    median_fill_size = t["size"].median()
    avg_fill_usdc = t["usdc_size"].mean()

    # Entry latency
    latencies = []
    for slug, grp in t.groupby("slug"):
        parts = slug.split("-")
        try:
            window_open = float(parts[-1])
            lat = grp["ts"].min() - window_open
            if 0 < lat < 600:
                latencies.append(lat)
        except (ValueError, IndexError):
            pass
    avg_latency = np.mean(latencies) if latencies else 0
    median_latency = np.median(latencies) if latencies else 0

    # TAKER allocation
    taker_pct = (t["role"] == "TAKER").mean() * 100

    # Capital per market
    mkt_vol = t.groupby("slug")["usdc_size"].sum()
    avg_cap = mkt_vol.mean()
    median_cap = mkt_vol.median()

    # Edge
    edges = []
    for slug, grp in t.groupby("slug"):
        up = grp[grp["outcome"] == "Up"]
        down = grp[grp["outcome"] == "Down"]
        if up.empty or down.empty:
            continue
        up_vwap = (up["price"] * up["size"]).sum() / up["size"].sum()
        down_vwap = (down["price"] * down["size"]).sum() / down["size"].sum()
        edges.append(1 - up_vwap - down_vwap)
    avg_edge = np.mean(edges) if edges else 0
    median_edge = np.median(edges) if edges else 0

    # Hedge delay
    delays = []
    for slug, grp in t.groupby("slug"):
        up_first = grp[grp["outcome"] == "Up"]["ts"].min()
        down_first = grp[grp["outcome"] == "Down"]["ts"].min()
        if pd.notna(up_first) and pd.notna(down_first):
            delays.append(abs(up_first - down_first))
    avg_hedge_delay = np.mean(delays) if delays else 0
    median_hedge_delay = np.median(delays) if delays else 0

    # BTC vs ETH
    asset_vol = t.groupby("asset_type")["usdc_size"].sum()
    btc_vol = asset_vol.get("BTC", 0)
    eth_vol = asset_vol.get("ETH", 0)
    btc_eth_ratio = btc_vol / eth_vol if eth_vol > 0 else float("inf")

    # Fills per market
    fills_per_market = t.groupby("slug").size()

    # Side split
    up_trades = t[t["outcome"] == "Up"]
    down_trades = t[t["outcome"] == "Down"]

    # Timeframe split
    tf_vol = t.groupby("timeframe")["usdc_size"].sum()
    total_vol = tf_vol.sum()
    tf_pct = (tf_vol / total_vol * 100).round(1)

    html = f"""
    <table class="cheatsheet">
    <tr><th colspan="2" style="text-align:center;font-size:1.2em;padding:10px;background:#1a1a2e;color:#e0e0e0;">
        Gabagool Parameter Cheat Sheet</th></tr>
    <tr><th>Parameter</th><th>Value</th></tr>

    <tr><td colspan="2" style="background:#16213e;color:#e0e0e0;font-weight:bold;padding:8px;">Grid Shape</td></tr>
    <tr><td>Avg price levels per market</td><td>{avg_levels:.1f}</td></tr>
    <tr><td>Median level spacing</td><td>{median_spacing:.3f} (${median_spacing*100:.1f}c)</td></tr>
    <tr><td>Avg fill size (shares)</td><td>{avg_fill_size:.2f}</td></tr>
    <tr><td>Median fill size (shares)</td><td>{median_fill_size:.2f}</td></tr>
    <tr><td>Avg fill USDC</td><td>${avg_fill_usdc:.2f}</td></tr>
    <tr><td>Fills per market (mean)</td><td>{fills_per_market.mean():.0f}</td></tr>
    <tr><td>Fills per market (median)</td><td>{fills_per_market.median():.0f}</td></tr>

    <tr><td colspan="2" style="background:#16213e;color:#e0e0e0;font-weight:bold;padding:8px;">Timing</td></tr>
    <tr><td>Entry latency (mean)</td><td>{avg_latency:.1f}s</td></tr>
    <tr><td>Entry latency (median)</td><td>{median_latency:.1f}s</td></tr>
    <tr><td>Hedge delay (mean)</td><td>{avg_hedge_delay:.1f}s</td></tr>
    <tr><td>Hedge delay (median)</td><td>{median_hedge_delay:.1f}s</td></tr>

    <tr><td colspan="2" style="background:#16213e;color:#e0e0e0;font-weight:bold;padding:8px;">Order Type</td></tr>
    <tr><td>MAKER %</td><td>{100 - taker_pct:.1f}%</td></tr>
    <tr><td>TAKER %</td><td>{taker_pct:.1f}%</td></tr>

    <tr><td colspan="2" style="background:#16213e;color:#e0e0e0;font-weight:bold;padding:8px;">Capital Allocation</td></tr>
    <tr><td>Avg capital per market</td><td>${avg_cap:,.2f}</td></tr>
    <tr><td>Median capital per market</td><td>${median_cap:,.2f}</td></tr>
    <tr><td>BTC:ETH ratio</td><td>{btc_eth_ratio:.1f}:1</td></tr>
    <tr><td>Timeframe split</td><td>{'; '.join(f'{k}: {v}%' for k, v in tf_pct.items())}</td></tr>

    <tr><td colspan="2" style="background:#16213e;color:#e0e0e0;font-weight:bold;padding:8px;">Edge & Merge</td></tr>
    <tr><td>Avg edge (hedged markets)</td><td>{avg_edge:.4f} ({avg_edge*100:.2f}%)</td></tr>
    <tr><td>Median edge (hedged markets)</td><td>{median_edge:.4f} ({median_edge*100:.2f}%)</td></tr>
    <tr><td>Up avg price (all fills)</td><td>{up_trades['price'].mean():.4f}</td></tr>
    <tr><td>Down avg price (all fills)</td><td>{down_trades['price'].mean():.4f}</td></tr>

    <tr><td colspan="2" style="background:#16213e;color:#e0e0e0;font-weight:bold;padding:8px;">Selection Criteria</td></tr>
    <tr><td>Assets traded</td><td>{'BTC, ETH' if eth_vol > 0 else 'BTC only'}</td></tr>
    <tr><td>100% BUY (no SELL)</td><td>{'Yes' if (t['side'] == 'BUY').all() else 'No'}</td></tr>
    <tr><td>Exits via merge/redemption only</td><td>Yes (inferred)</td></tr>
    </table>
    """
    return html, []


# ===================================================================
# Text Summary (stdout)
# ===================================================================

def _print_summary(dfs: dict[str, pd.DataFrame]) -> None:
    """Print a compact text summary to stdout."""
    t = dfs["obs_trades"]
    if t.empty:
        print("No trade data found.")
        return

    sess = dfs["obs_sessions"]
    merges = dfs["obs_merges"]
    redemptions = dfs["obs_redemptions"]

    n_trades = len(t)
    n_markets = t["slug"].nunique()
    total_vol = t["usdc_size"].sum()
    ts_min, ts_max = t["ts"].min(), t["ts"].max()
    duration_hrs = (ts_max - ts_min) / 3600

    maker_pct = (t["role"] == "MAKER").mean() * 100
    maker_avg = t.loc[t["role"] == "MAKER", "usdc_size"].mean()
    taker_avg = t.loc[t["role"] == "TAKER", "usdc_size"].mean()

    # Per-market edge + P&L
    market_pnl = []
    for slug, grp in t.groupby("slug"):
        up = grp[grp["outcome"] == "Up"]
        down = grp[grp["outcome"] == "Down"]
        if up.empty or down.empty:
            continue
        up_vwap = (up["price"] * up["size"]).sum() / up["size"].sum()
        down_vwap = (down["price"] * down["size"]).sum() / down["size"].sum()
        edge = 1 - up_vwap - down_vwap
        mergeable = min(up["size"].sum(), down["size"].sum())
        gross = mergeable * edge
        market_pnl.append({"slug": slug, "edge": edge, "mergeable": mergeable, "gross": gross,
                           "up_cost": up["usdc_size"].sum(), "down_cost": down["usdc_size"].sum()})
    mp = pd.DataFrame(market_pnl) if market_pnl else pd.DataFrame()

    avg_edge = mp["edge"].mean() if not mp.empty else 0
    win_rate = (mp["edge"] > 0).mean() * 100 if not mp.empty else 0
    combined_vwap = 1 - avg_edge if avg_edge else 0

    # Merge/redemption revenue ($1 per share merged/redeemed)
    merge_revenue = merges["shares"].sum() if not merges.empty and "shares" in merges.columns else 0
    redeem_revenue = redemptions["shares"].sum() if not redemptions.empty and "shares" in redemptions.columns else 0
    unmerged_cost = (mp["up_cost"].sum() + mp["down_cost"].sum()) if not mp.empty else 0

    # BTC:ETH
    asset_vol = t.groupby("asset_type")["usdc_size"].sum()
    btc_v = asset_vol.get("BTC", 0)
    eth_v = asset_vol.get("ETH", 0)
    btc_n = t[t["asset_type"] == "BTC"]["slug"].nunique()
    eth_n = t[t["asset_type"] == "ETH"]["slug"].nunique()

    # Timeframe breakdown
    tf_markets = t.groupby("timeframe")["slug"].nunique().sort_values(ascending=False)

    print()
    print("=" * 60)
    print("  GABAGOOL DEEP DIVE SUMMARY")
    print("=" * 60)
    print(f"  Sessions: {len(sess)}  |  Duration: {duration_hrs:.1f} hrs")
    print(f"  Trades: {n_trades:,}  |  Markets: {n_markets}  |  Volume: ${total_vol:,.0f}")
    print(f"  MAKER: {maker_pct:.0f}% (${maker_avg:.2f} avg)  |  TAKER: {100-maker_pct:.0f}% (${taker_avg:.2f} avg)")
    print()
    print(f"  Combined VWAP: {combined_vwap:.4f}  |  Avg edge: {avg_edge*100:.2f}%  |  Win rate: {win_rate:.0f}%")
    print()
    print(f"  Merge revenue:      ${merge_revenue:,.0f}  ({len(merges)} merges)")
    print(f"  Redemption revenue: ${redeem_revenue:,.0f}  ({len(redemptions)} redemptions)")
    print(f"  Unmerged exposure:  ${unmerged_cost:,.0f}")
    print()
    print(f"  BTC: {btc_n} markets (${btc_v:,.0f})  |  ETH: {eth_n} markets (${eth_v:,.0f})")
    print(f"  Timeframes: {', '.join(f'{k}:{v}' for k, v in tf_markets.items())}")

    # Top 3 winners / losers
    if not mp.empty and len(mp) >= 3:
        top = mp.nlargest(3, "gross")
        bot = mp.nsmallest(3, "gross")
        print()
        print("  Top 3 winners:")
        for _, r in top.iterrows():
            print(f"    {r['slug'][:45]:<45s}  edge={r['edge']*100:+.2f}%  gross=${r['gross']:+,.2f}")
        print("  Top 3 losers:")
        for _, r in bot.iterrows():
            print(f"    {r['slug'][:45]:<45s}  edge={r['edge']*100:+.2f}%  gross=${r['gross']:+,.2f}")

    print("=" * 60)
    print()


# ===================================================================
# Section 10: Capital Growth
# ===================================================================

def section_capital_growth(dfs: dict) -> tuple[str, list]:
    balances = dfs["obs_balance_snapshots"]
    transfers = dfs["obs_usdc_transfers"]

    figs = []
    html_parts = []

    if balances.empty:
        return "<p>No balance data available.</p>", []

    # Sort by timestamp
    balances = balances.sort_values("ts")
    balances["dt"] = balances["ts"].apply(_ts_to_dt)

    # Chart 1: USDC balance + total equity over time
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(balances["dt"], balances["usdc_balance"],
            label="USDC Balance", color="green", linewidth=2)
    ax.plot(balances["dt"], balances["total_equity"],
            label="Total Equity", color="blue", linewidth=2)
    ax.fill_between(balances["dt"], balances["usdc_balance"],
                    balances["total_position_value"] + balances["usdc_balance"],
                    alpha=0.3, color="orange", label="Position Value")
    ax.set_xlabel("Time")
    ax.set_ylabel("USD")
    ax.set_title("Capital Growth: USDC Balance & Total Equity")
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.tight_layout()
    figs.append(("s10_capital_growth", fig))

    # Summary statistics
    initial_equity = balances["total_equity"].iloc[0]
    final_equity = balances["total_equity"].iloc[-1]
    equity_change = final_equity - initial_equity
    equity_pct = (equity_change / initial_equity * 100) if initial_equity > 0 else 0

    initial_usdc = balances["usdc_balance"].iloc[0]
    final_usdc = balances["usdc_balance"].iloc[-1]
    usdc_change = final_usdc - initial_usdc

    avg_position_value = balances["total_position_value"].mean()
    max_position_value = balances["total_position_value"].max()

    duration_hours = (balances["ts"].iloc[-1] - balances["ts"].iloc[0]) / 3600

    html_parts.append(f"""
    <h4>Capital Growth Summary</h4>
    <table class="summary">
    <tr><td>Initial equity</td><td>${initial_equity:,.2f}</td></tr>
    <tr><td>Final equity</td><td>${final_equity:,.2f}</td></tr>
    <tr><td>Total equity change</td><td>${equity_change:,.2f} ({equity_pct:+.2f}%)</td></tr>
    <tr><td>Initial USDC</td><td>${initial_usdc:,.2f}</td></tr>
    <tr><td>Final USDC</td><td>${final_usdc:,.2f}</td></tr>
    <tr><td>USDC change</td><td>${usdc_change:,.2f}</td></tr>
    <tr><td>Avg position value</td><td>${avg_position_value:,.2f}</td></tr>
    <tr><td>Max position value</td><td>${max_position_value:,.2f}</td></tr>
    <tr><td>Session duration</td><td>{duration_hours:.1f} hours</td></tr>
    </table>
    """)

    # Rebate analysis
    if not transfers.empty:
        rebates = transfers[transfers["transfer_type"] == "rebate"]
        if not rebates.empty:
            total_rebates = rebates["amount"].sum()
            n_rebates = len(rebates)
            rebates_sorted = rebates.sort_values("ts")
            rebates_sorted["dt"] = rebates_sorted["ts"].apply(_ts_to_dt)

            # Calculate daily rebate income if we have enough data
            if duration_hours >= 1:
                daily_rebate = total_rebates * (24 / duration_hours)
            else:
                daily_rebate = 0

            html_parts.append(f"""
            <h4>Rebate Income</h4>
            <table class="summary">
            <tr><td>Total rebates</td><td>${total_rebates:,.2f}</td></tr>
            <tr><td>Number of rebates</td><td>{n_rebates}</td></tr>
            <tr><td>Average rebate</td><td>${total_rebates/n_rebates:,.2f}</td></tr>
            <tr><td>Est. daily rebate rate</td><td>${daily_rebate:,.2f}/day</td></tr>
            </table>
            """)

            # Chart 2: Cumulative rebate income
            rebates_sorted["cumulative"] = rebates_sorted["amount"].cumsum()
            fig2, ax2 = plt.subplots(figsize=(12, 5))
            ax2.plot(rebates_sorted["dt"], rebates_sorted["cumulative"],
                    color="green", linewidth=2)
            ax2.scatter(rebates_sorted["dt"], rebates_sorted["cumulative"],
                       s=40, alpha=0.6, color="darkgreen")
            ax2.set_xlabel("Time")
            ax2.set_ylabel("Cumulative Rebates (USD)")
            ax2.set_title("Cumulative Rebate Income Over Time")
            ax2.grid(True, alpha=0.3)
            ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
            fig2.tight_layout()
            figs.append(("s10_rebates", fig2))
        else:
            html_parts.append("<p><i>No rebate transfers observed.</i></p>")
    else:
        html_parts.append("<p><i>No transfer data available.</i></p>")

    imgs = "".join(_save_and_embed(f, n) for n, f in figs)
    return "\n".join(html_parts) + imgs, figs


# ===================================================================
# HTML Report Assembly
# ===================================================================

HTML_TEMPLATE = textwrap.dedent("""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Gabagool Deep Dive — Parameter Extraction</title>
<style>
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: #0d1117; color: #c9d1d9; margin: 0; padding: 20px;
        line-height: 1.5;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    h1 {{ color: #58a6ff; border-bottom: 1px solid #30363d; padding-bottom: 10px; }}
    h2 {{ color: #79c0ff; margin-top: 40px; border-bottom: 1px solid #21262d; padding-bottom: 5px; }}
    h3 {{ color: #d2a8ff; }}
    h4 {{ color: #7ee787; margin-top: 20px; }}
    table {{ border-collapse: collapse; margin: 10px 0; width: auto; }}
    table.data, table.summary, table.cheatsheet {{
        border: 1px solid #30363d; background: #161b22;
    }}
    th, td {{ padding: 6px 12px; text-align: left; border: 1px solid #21262d; font-size: 0.9em; }}
    th {{ background: #1a1a2e; color: #e0e0e0; }}
    tr:nth-child(even) {{ background: #1c2333; }}
    img {{ border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.5); }}
    .section {{ background: #161b22; border-radius: 8px; padding: 20px; margin: 20px 0;
                border: 1px solid #30363d; }}
    .timestamp {{ color: #8b949e; font-size: 0.85em; }}
    table.cheatsheet {{ width: 100%; }}
    table.cheatsheet td:first-child {{ font-weight: bold; color: #58a6ff; width: 40%; }}
    table.cheatsheet td:last-child {{ font-family: monospace; }}
</style>
</head>
<body>
<div class="container">
<h1>Gabagool Deep Dive — Parameter Extraction</h1>
<p class="timestamp">Generated: {timestamp}</p>
{sections}
</div>
</body>
</html>
""")


SECTION_NAMES = [
    ("1. Data Summary", section_summary),
    ("2. Grid Parameter Extraction", section_grid),
    ("3. Fill Timing & Order Management", section_timing),
    ("4. MAKER vs TAKER Strategy", section_maker_taker),
    ("5. Edge & P&L Estimation", section_edge_pnl),
    ("6. Position Lifecycle Trace", section_lifecycle),
    ("7. Market Selection & Capital Allocation", section_allocation),
    ("8. Volatility Regime Overlay", section_volatility),
    ("9. Actionable Cheat Sheet", section_cheat_sheet),
    ("10. Capital Growth", section_capital_growth),
]


def generate_report(db_path: str, session_id: str | None = None) -> str:
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    dfs = load_data(db_path, session_id)

    # Print compact text summary to stdout
    _print_summary(dfs)

    sections_html = []
    for title, func in SECTION_NAMES:
        html, _ = func(dfs)
        sections_html.append(f'<div class="section"><h2>{title}</h2>\n{html}\n</div>')

    report = HTML_TEMPLATE.format(
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        sections="\n".join(sections_html),
    )

    REPORT_PATH.write_text(report)
    print(f"HTML report: {REPORT_PATH}")
    return str(REPORT_PATH)


# ===================================================================
# CLI
# ===================================================================

def main():
    parser = argparse.ArgumentParser(description="Gabagool deep-dive analysis")
    parser.add_argument("--session", default=None, help="Filter to specific session ID")
    parser.add_argument("--db", default="data/observer.db", help="Path to observer DB")
    args = parser.parse_args()
    generate_report(args.db, args.session)


if __name__ == "__main__":
    main()
