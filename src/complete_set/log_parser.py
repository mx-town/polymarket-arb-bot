"""Single-pass log parser for complete-set arb bot logs.

Reads a log file and returns a structured dict covering 4 dashboard views:
pipeline funnel, per-market lifecycle, P&L trajectory, and BTC overlay.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Compiled regex patterns — matched against ANSI-stripped log lines
# ---------------------------------------------------------------------------

# Strip ANSI escape codes
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Line structure: "2026-02-15 14:10:48 │ cs.engine        │ MESSAGE"
LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"  # timestamp
    r" │ (\S+)\s*"                                # logger
    r"│ (.*)$"                                    # message
)

# BTC_TICK │ 69473.86 → 69474.63 │ Δ=0.77
BTC_TICK_RE = re.compile(
    r"BTC_TICK │ [\d.]+ → ([\d.]+) │ Δ="
)

# SH_ENTRY / MR_ENTRY slug │ SIDE @price │ extra │ Xsh │ Xs
ENTRY_RE = re.compile(
    r"(SH_ENTRY|MR_ENTRY) (\S+) │ (UP|DOWN) @([\d.]+) │ (.+?) │ ([\d.]+)sh │ (\d+)s"
)

# DRY_FILL slug BUY UP +169.64 shares @ 0.45 (after 0.6s)
DRY_FILL_RE = re.compile(
    r"DRY_FILL (\S+) (BUY|SELL) (UP|DOWN) \+([\d.]+) shares @ ([\d.]+) \(after ([\d.]+)s\)"
)

# FILL slug UP +169 shares @ 0.45 (not DRY_FILL or SELL_FILL)
FILL_RE = re.compile(
    r"(?<![A-Z_])FILL (\S+) (UP|DOWN) \+([\d.]+) shares @ ([\d.]+)"
)

# HEDGE_LEG slug │ UP @0.54 │ DOWN_vwap=0.45 │ edge=0.010 │ 169.64sh │ 583s
HEDGE_LEG_RE = re.compile(
    r"HEDGE_LEG (\S+) │ (UP|DOWN) @([\d.]+) │ (\w+)_vwap=([\d.]+) │ edge=([\d.]+) │ ([\d.]+)sh │ (\d+)s"
)

# HEDGE_COMPLETE slug │ hedged=169.64 │ edge=0.01
HEDGE_COMPLETE_RE = re.compile(
    r"HEDGE_COMPLETE (\S+) │ hedged=([\d.]+) │ edge=([\d.]+)"
)

# DRY_MERGE slug │ merged=169.64 shares → freed $169.64 │ gas=-$0.003
DRY_MERGE_RE = re.compile(
    r"DRY_MERGE (\S+) │ merged=([\d.]+) shares → freed \$([\d.]+) │ gas=-\$([\d.]+)"
)

# MERGE_POSITION slug │ merged=169 shares │ tx=0xabc
MERGE_POSITION_RE = re.compile(
    r"MERGE_POSITION (\S+) │ merged=([\d.]+) shares │ tx=(\S+)"
)

# CLEAR_INVENTORY slug (was U169.64/D0) │ hedged=0 │ hedged_pnl=$0.00 │ ...
CLEAR_RE = re.compile(
    r"CLEAR_INVENTORY (\S+) \(was U([\d.]+)/D([\d.]+)\)"
    r" │ hedged=([\d.]+)"
    r" │ hedged_pnl=\$([\d.-]+)"
    r" │ unhedged=(\S+) \(loss=\$([\d.]+)\)"
    r" │ prior_merge_pnl=\$([\d.-]+)"
    r" │ net=\$([\d.-]+)"
)

# ┌─ SUMMARY ...  runtime=50m  ROI=0.00%
SUMMARY_RE = re.compile(
    r"┌─ SUMMARY.*?runtime=(\S+)\s+ROI=([\d.-]+)%"
)

# │ PnL: realized=$-145.07  unrealized=$0.00  total=$-145.07
PNL_RE = re.compile(
    r"│ PnL: realized=\$([\d.-]+)\s+unrealized=\$([\d.-]+)\s+total=\$([\d.-]+)"
)

# │ bankroll=$500 (0.0% used)
BANKROLL_RE = re.compile(
    r"│ bankroll=\$([\d.]+) \(([\d.]+)% used\)"
)

# ENTER window │ slug
ENTER_WINDOW_RE = re.compile(r"ENTER window │ (\S+)")

# EXIT  window │ slug
EXIT_WINDOW_RE = re.compile(r"EXIT  window │ (\S+)")

# REPRICE reason │ slug old→new │ shares shares │ Xs left
REPRICE_RE = re.compile(
    r"REPRICE (\S+) │ (\S+) ([\d.]+)→([\d.]+) │ ([\d.]+) shares │ (\d+)s left"
)

# BUFFER_HOLD slug │ UX/DY
BUFFER_HOLD_RE = re.compile(
    r"BUFFER_HOLD (\S+) │ U([\d.]+)/D([\d.]+)"
)

# Config header lines between ======== blocks
CONFIG_RE = {
    "version": re.compile(r"Complete-Set Arb Engine (v[\d.]+)"),
    "mode": re.compile(r"\[(DRY RUN|LIVE)\]"),
    "assets": re.compile(r"Assets\s+: (.+)"),
    "tick_interval": re.compile(r"Tick interval\s+: (.+)"),
    "min_edge": re.compile(r"Min edge\s+: ([\d.]+)"),
    "bankroll": re.compile(r"Bankroll\s+: \$([\d.]+)"),
    "time_window": re.compile(r"Time window\s+: (.+)"),
    "stop_hunt": re.compile(r"Stop hunt\s+: (ON|OFF)"),
    "mean_reversion": re.compile(r"Mean reversion\s+: (ON|OFF)"),
    "swing_filter": re.compile(r"Swing filter\s+: (ON|OFF)"),
    "post_merge_lock": re.compile(r"Post-merge lock\s+: (ON|OFF)"),
}


def _time_only(ts: str) -> str:
    """Extract HH:MM:SS from full timestamp."""
    return ts.split(" ", 1)[1] if " " in ts else ts


def _ensure_market(markets: dict, slug: str) -> dict:
    """Get or create a default market state dict."""
    if slug not in markets:
        markets[slug] = {
            "slug": slug,
            "enter_time": None,
            "exit_time": None,
            "clear_time": None,
            "entry_side": None,
            "entry_price": None,
            "entry_shares": None,
            "entry_type": None,
            "seconds_left_at_entry": None,
            "fill_time": None,
            "fill_price": None,
            "reprice_count": 0,
            "upward_reprice_count": 0,
            "price_chasing": False,
            "hedge_side": None,
            "hedge_price": None,
            "hedge_edge": None,
            "hedge_complete_time": None,
            "merged_shares": None,
            "merge_time": None,
            "gas_cost": None,
            "combined_cost": None,
            "pnl": None,
            "clear_was": None,
            "outcome": "no_activity",
            "status": "yellow",
        }
    return markets[slug]


def _compute_red_flags(data: dict) -> list[dict]:
    """Compute red flags from parsed data (LOG_ANALYSIS_PLAN Step 10)."""
    flags = []
    funnel = data["funnel"]

    # Infrastructure flags
    if funnel["fills"] == 0 and funnel["entries"] > 0:
        flags.append({
            "flag": "zero_fills",
            "detail": f"0 fills from {funnel['entries']} entries — fill simulation may be broken",
        })

    if funnel["entries"] == 0:
        flags.append({
            "flag": "zero_entries",
            "detail": "No entry signals fired — signal may be too strict or no markets in window",
        })

    # Strategy flags
    if funnel["fills"] > 0:
        hedge_rate = funnel["hedges_complete"] / funnel["fills"]
        if hedge_rate < 0.5:
            flags.append({
                "flag": "hedge_rate_low",
                "detail": f"Hedge rate {hedge_rate:.0%} — only {funnel['hedges_complete']}/{funnel['fills']} first legs got hedged",
            })

    if funnel["unhedged_count"] > 0:
        flags.append({
            "flag": "unhedged_losses",
            "detail": f"{funnel['unhedged_count']} market(s) had unhedged losses at settlement",
        })

    # Price chasing
    chasers = [m for m in data["markets"] if m["price_chasing"]]
    if chasers:
        slugs = ", ".join(m["slug"][-20:] for m in chasers[:3])
        flags.append({
            "flag": "price_chasing",
            "detail": f"{len(chasers)} market(s) with 3+ upward reprices: {slugs}",
        })

    # P&L declining
    if data["total_realized"] < -10:
        flags.append({
            "flag": "pnl_negative",
            "detail": f"Total realized P&L is ${data['total_realized']:.2f}",
        })

    # Low capital utilization
    snapshots = data["pnl_snapshots"]
    if snapshots:
        avg_exposure = sum(s["exposure_pct"] for s in snapshots) / len(snapshots)
        if avg_exposure < 5.0 and len(snapshots) > 3:
            flags.append({
                "flag": "low_utilization",
                "detail": f"Average capital utilization only {avg_exposure:.1f}%",
            })

    return flags


def parse_log(filepath: str | Path) -> dict:
    """Parse a complete-set bot log file and return structured data for the dashboard."""
    filepath = Path(filepath)
    lines = filepath.read_text(errors="replace").splitlines()

    # Determine mode from path
    path_str = str(filepath)
    if "/dry/" in path_str or "\\dry\\" in path_str:
        mode = "dry"
    elif "/live/" in path_str or "\\live\\" in path_str:
        mode = "live"
    else:
        mode = "unknown"

    # Result accumulators
    config: dict = {}
    markets: dict = {}  # slug -> market dict
    btc_ticks: list = []
    btc_events: list = []
    pnl_snapshots: list = []
    last_btc_price: float = 0.0
    start_time: str | None = None
    end_time: str | None = None

    # Funnel counters
    entries = 0
    fill_keys: set = set()  # (slug, side) for unique fills
    hedge_attempts = 0
    hedges_complete = 0
    merges = 0
    unhedged_count = 0

    # Tracking for summary blocks
    last_runtime: str = ""
    last_roi: float = 0.0
    last_realized: float = 0.0
    last_unrealized: float = 0.0
    last_total: float = 0.0

    # Header has 3 separator lines: ====, title, ====, config..., ====
    header_sep_count = 0
    in_header = False

    for raw_line in lines:
        # Strip ANSI
        line = _ANSI_RE.sub("", raw_line)

        m = LINE_RE.match(line)
        if not m:
            continue

        ts, _logger, msg = m.group(1), m.group(2), m.group(3)

        if start_time is None:
            start_time = ts
        end_time = ts

        time_str = _time_only(ts)

        # --- Config header (3 separator lines) ---
        if "========" in msg:
            header_sep_count += 1
            in_header = header_sep_count < 3
            continue

        if in_header:
            for key, pat in CONFIG_RE.items():
                cm = pat.search(msg)
                if cm:
                    val = cm.group(1)
                    if key in ("min_edge", "bankroll"):
                        config[key] = float(val)
                    elif key in ("stop_hunt", "mean_reversion", "swing_filter", "post_merge_lock"):
                        config[key] = val == "ON"
                    elif key == "mode":
                        if mode == "unknown":
                            mode = "dry" if val == "DRY RUN" else "live"
                    else:
                        config[key] = val
            continue

        # --- BTC_TICK ---
        bm = BTC_TICK_RE.search(msg)
        if bm:
            last_btc_price = float(bm.group(1))
            btc_ticks.append({"time": time_str, "price": last_btc_price})
            continue

        # --- ENTER window ---
        em = ENTER_WINDOW_RE.search(msg)
        if em and "ENTER window" in msg:
            slug = em.group(1)
            mk = _ensure_market(markets, slug)
            mk["enter_time"] = time_str
            continue

        # --- EXIT window ---
        xm = EXIT_WINDOW_RE.search(msg)
        if xm and "EXIT  window" in msg:
            slug = xm.group(1)
            mk = _ensure_market(markets, slug)
            mk["exit_time"] = time_str
            continue

        # --- ENTRY (SH_ENTRY / MR_ENTRY) ---
        em2 = ENTRY_RE.search(msg)
        if em2:
            reason, slug, side, price, _extra, shares, secs = em2.groups()
            mk = _ensure_market(markets, slug)
            if mk["entry_side"] is None:  # first entry for this market
                mk["entry_side"] = side
                mk["entry_price"] = float(price)
                mk["entry_shares"] = float(shares)
                mk["entry_type"] = reason
                mk["seconds_left_at_entry"] = int(secs)
                entries += 1
                btc_events.append({
                    "time": time_str,
                    "type": "entry",
                    "slug": slug,
                    "side": side,
                    "poly_price": float(price),
                    "btc_price": last_btc_price,
                })
            continue

        # --- DRY_FILL ---
        fm = DRY_FILL_RE.search(msg)
        if fm:
            slug, buy_sell, direction, shares, price, delay = fm.groups()
            mk = _ensure_market(markets, slug)
            key = (slug, direction)
            if key not in fill_keys:
                fill_keys.add(key)
                if mk["fill_time"] is None:
                    mk["fill_time"] = time_str
                    mk["fill_price"] = float(price)
                btc_events.append({
                    "time": time_str,
                    "type": "fill",
                    "slug": slug,
                    "side": direction,
                    "poly_price": float(price),
                    "btc_price": last_btc_price,
                })
            continue

        # --- FILL (live) ---
        fm2 = FILL_RE.search(msg)
        if fm2:
            slug, direction, shares, price = fm2.groups()
            mk = _ensure_market(markets, slug)
            key = (slug, direction)
            if key not in fill_keys:
                fill_keys.add(key)
                if mk["fill_time"] is None:
                    mk["fill_time"] = time_str
                    mk["fill_price"] = float(price)
                btc_events.append({
                    "time": time_str,
                    "type": "fill",
                    "slug": slug,
                    "side": direction,
                    "poly_price": float(price),
                    "btc_price": last_btc_price,
                })
            continue

        # --- REPRICE ---
        rm = REPRICE_RE.search(msg)
        if rm:
            reason, slug, old_p, new_p, _shares, _secs = rm.groups()
            mk = _ensure_market(markets, slug)
            mk["reprice_count"] += 1
            if float(new_p) > float(old_p):
                mk["upward_reprice_count"] += 1
            if mk["upward_reprice_count"] >= 3:
                mk["price_chasing"] = True
            continue

        # --- HEDGE_LEG ---
        hm = HEDGE_LEG_RE.search(msg)
        if hm:
            slug, side, price, opp_side, vwap, edge, shares, secs = hm.groups()
            mk = _ensure_market(markets, slug)
            mk["hedge_side"] = side
            mk["hedge_price"] = float(price)
            mk["hedge_edge"] = float(edge)
            hedge_attempts += 1
            btc_events.append({
                "time": time_str,
                "type": "hedge",
                "slug": slug,
                "side": side,
                "poly_price": float(price),
                "btc_price": last_btc_price,
            })
            continue

        # --- HEDGE_COMPLETE ---
        hcm = HEDGE_COMPLETE_RE.search(msg)
        if hcm:
            slug, shares, edge = hcm.groups()
            mk = _ensure_market(markets, slug)
            mk["hedge_complete_time"] = time_str
            mk["hedge_edge"] = float(edge)
            hedges_complete += 1
            continue

        # --- DRY_MERGE ---
        dm = DRY_MERGE_RE.search(msg)
        if dm:
            slug, shares, freed, gas = dm.groups()
            mk = _ensure_market(markets, slug)
            mk["merged_shares"] = float(shares)
            mk["merge_time"] = time_str
            mk["gas_cost"] = float(gas)
            merges += 1
            # Compute combined cost if we have both legs
            if mk["fill_price"] is not None and mk["hedge_price"] is not None:
                mk["combined_cost"] = mk["fill_price"] + mk["hedge_price"]
            btc_events.append({
                "time": time_str,
                "type": "merge",
                "slug": slug,
                "side": None,
                "poly_price": None,
                "btc_price": last_btc_price,
            })
            continue

        # --- MERGE_POSITION (live) ---
        mpm = MERGE_POSITION_RE.search(msg)
        if mpm:
            slug, shares, _tx = mpm.groups()
            mk = _ensure_market(markets, slug)
            mk["merged_shares"] = float(shares)
            mk["merge_time"] = time_str
            merges += 1
            if mk["fill_price"] is not None and mk["hedge_price"] is not None:
                mk["combined_cost"] = mk["fill_price"] + mk["hedge_price"]
            btc_events.append({
                "time": time_str,
                "type": "merge",
                "slug": slug,
                "side": None,
                "poly_price": None,
                "btc_price": last_btc_price,
            })
            continue

        # --- CLEAR_INVENTORY ---
        cm = CLEAR_RE.search(msg)
        if cm:
            slug = cm.group(1)
            u_shares, d_shares = cm.group(2), cm.group(3)
            hedged = cm.group(4)
            hedged_pnl = cm.group(5)
            unhedged_str = cm.group(6)
            unhedged_loss = float(cm.group(7))
            prior_merge_pnl = cm.group(8)
            net = float(cm.group(9))

            mk = _ensure_market(markets, slug)
            mk["clear_time"] = time_str
            mk["pnl"] = net
            mk["clear_was"] = f"U{u_shares}/D{d_shares}"

            if unhedged_loss > 0:
                unhedged_count += 1

            # Determine outcome
            if mk["merged_shares"] and mk["merged_shares"] > 0:
                mk["outcome"] = "merged"
                mk["status"] = "green" if net >= 0 else "red"
            elif unhedged_loss > 0:
                mk["outcome"] = "unhedged_loss"
                mk["status"] = "red"
            elif mk["fill_time"] is not None:
                mk["outcome"] = "partial"
                mk["status"] = "yellow"
            else:
                mk["outcome"] = "no_activity"
                mk["status"] = "yellow"
            continue

        # --- BUFFER_HOLD ---
        bhm = BUFFER_HOLD_RE.search(msg)
        if bhm:
            slug = bhm.group(1)
            _ensure_market(markets, slug)
            continue

        # --- SUMMARY ---
        sm = SUMMARY_RE.search(msg)
        if sm:
            last_runtime = sm.group(1)
            last_roi = float(sm.group(2))
            continue

        # --- PnL ---
        pm = PNL_RE.search(msg)
        if pm:
            last_realized = float(pm.group(1))
            last_unrealized = float(pm.group(2))
            last_total = float(pm.group(3))
            continue

        # --- bankroll ---
        bkm = BANKROLL_RE.search(msg)
        if bkm:
            _bankroll, pct_used = float(bkm.group(1)), float(bkm.group(2))
            if last_runtime:
                pnl_snapshots.append({
                    "time": time_str,
                    "runtime": last_runtime,
                    "realized": last_realized,
                    "unrealized": last_unrealized,
                    "total": last_total,
                    "roi_pct": last_roi,
                    "exposure_pct": pct_used,
                })
            continue

    # --- Post-processing ---

    # Convert markets dict to sorted list
    market_list = sorted(markets.values(), key=lambda m: m["enter_time"] or "")

    # BTC tick downsampling
    if len(btc_ticks) > 500:
        n = len(btc_ticks) // 500
        btc_ticks = btc_ticks[::n]

    # Compute final P&L from last snapshot or CLEAR lines
    total_realized = sum(m["pnl"] for m in market_list if m["pnl"] is not None)
    final_roi = last_roi

    result = {
        "filename": filepath.name,
        "mode": mode,
        "start_time": start_time or "",
        "end_time": end_time or "",
        "config": config,
        "funnel": {
            "entries": entries,
            "fills": len(fill_keys),
            "hedge_attempts": hedge_attempts,
            "hedges_complete": hedges_complete,
            "merges": merges,
            "unhedged_count": unhedged_count,
        },
        "markets": market_list,
        "pnl_snapshots": pnl_snapshots,
        "total_realized": total_realized,
        "final_roi": final_roi,
        "red_flags": [],  # computed below
        "btc_ticks": btc_ticks,
        "btc_events": btc_events,
    }

    result["red_flags"] = _compute_red_flags(result)

    return result
