"""One-time order book analysis — captures snapshots around a market boundary
and detects gabagool's grid fingerprint.

Usage:
    uv run python -m observer.book_analysis [--asset bitcoin] [--timeframe 5m]

Finds the next market to OPEN, waits until just before its start boundary,
then polls the order book at high frequency (every 2.5s) for 90s to catch
gabagool's grid burst right when it posts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests

from observer.book import BOOK_URL, _parse_levels
from observer.poller import ACTIVITY_URL
from shared.market_data import (
    _ASSET_PREFIXES_5M,
    _ASSET_PREFIXES_15M,
    _candidate_5m_slugs,
    _candidate_15m_slugs,
    _fetch_market_by_slug,
)
from grid_maker.market_data import _ASSET_PREFIXES_1H, _candidate_1h_slugs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("book_analysis")

# Known gabagool sizes per asset×timeframe
GABAGOOL_SIZES = {
    ("bitcoin", "5m"): 20,
    ("bitcoin", "15m"): 15,
    ("bitcoin", "1h"): 26,
    ("ethereum", "15m"): 10,
    ("ethereum", "1h"): 16,
}

# Timeframe → boundary interval in seconds
TF_INTERVAL = {"5m": 300, "15m": 900, "1h": 3600}

GABAGOOL_PROXY = "0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d"
ACTIVITY_POLL_INTERVAL = 3.0


def _find_next_market(asset: str, tf: str):
    """Find the next market that hasn't opened yet (start_time > now)."""
    now = time.time()
    interval = TF_INTERVAL[tf]
    prefix_map = {"5m": _ASSET_PREFIXES_5M, "15m": _ASSET_PREFIXES_15M, "1h": _ASSET_PREFIXES_1H}
    slug_fn = {"5m": _candidate_5m_slugs, "15m": _candidate_15m_slugs, "1h": _candidate_1h_slugs}

    prefix = prefix_map.get(tf, {}).get(asset)
    if not prefix:
        return None

    best = None
    for slug in slug_fn[tf](prefix, now):
        market = _fetch_market_by_slug(slug)
        if not market:
            continue
        start_time = market.end_time - interval
        if start_time > now and (best is None or start_time < best.end_time - interval):
            best = market
    return best


def _fetch_raw_book(token_id: str) -> dict:
    """Fetch raw order book for a single token."""
    try:
        resp = requests.get(BOOK_URL, params={"token_id": token_id}, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.warning("BOOK_FETCH_FAIL │ %s │ %s", token_id[:12], e)
        return {}


def _take_snapshot(token_id: str, ts: float) -> dict:
    """Take a snapshot of bid/ask levels for a token."""
    raw = _fetch_raw_book(token_id)
    bids = _parse_levels(raw.get("bids", []))
    asks = _parse_levels(raw.get("asks", []))
    return {
        "timestamp": ts,
        "bids": {round(p, 2): s for p, s in bids},
        "asks": {round(p, 2): s for p, s in asks},
    }


def _collect_snapshots(
    token_ids: list[str],
    duration_sec: int = 60,
    poll_interval: float = 2.5,
) -> dict[str, list[dict]]:
    """Collect snapshots for token_ids over duration_sec."""
    snapshots: dict[str, list[dict]] = {tid: [] for tid in token_ids}
    end_time = time.time() + duration_sec
    poll_count = 0

    while time.time() < end_time:
        ts = time.time()
        for tid in token_ids:
            snap = _take_snapshot(tid, ts)
            snapshots[tid].append(snap)
        poll_count += 1
        remaining = end_time - time.time()
        if remaining > poll_interval:
            time.sleep(poll_interval)

    log.info("Collected %d polls across %d tokens", poll_count, len(token_ids))
    return snapshots


async def _ws_collect(
    token_ids: list[str],
    duration_sec: int = 90,
    boundary: float = 0.0,
) -> dict[str, dict]:
    """Collect full book state via WebSocket price_change events.

    Tracks ALL events (additions AND removals), maintains a full book
    replica, and captures book snapshots every 5 seconds.

    Returns dict keyed by token_id, each containing:
        "events": list of enriched event dicts (ALL deltas)
        "book_snapshots": list of book state snapshots every 5s
    """
    import websockets

    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    SNAP_INTERVAL = 5.0  # book snapshot every 5 seconds

    # Seed baseline sizes from REST so first WS event shows true delta
    prev_size: dict[tuple[str, str], float] = {}
    # Full book state: token_id → side → {price_str: aggregate_size}
    book: dict[str, dict[str, dict[str, float]]] = {}
    for tid in token_ids:
        book[tid] = {"bids": {}, "asks": {}}
        raw = _fetch_raw_book(tid)
        for level in raw.get("bids", []):
            p, s = level.get("price", "0"), float(level.get("size", "0"))
            prev_size[(tid, p)] = s
            book[tid]["bids"][p] = s
        for level in raw.get("asks", []):
            p, s = level.get("price", "0"), float(level.get("size", "0"))
            prev_size[(tid, p)] = s
            book[tid]["asks"][p] = s
    log.info("WS baseline seeded: %d price levels from REST", len(prev_size))

    result: dict[str, dict] = {
        tid: {"events": [], "book_snapshots": []} for tid in token_ids
    }
    token_set = set(token_ids)
    start_time = time.time()
    seq_counter = 0
    next_snap_time = start_time + SNAP_INTERVAL

    def _take_book_snapshot(ts: float) -> None:
        """Capture current book state for all tokens."""
        for tid in token_ids:
            bids = book[tid]["bids"]
            asks = book[tid]["asks"]
            bid_prices = [float(p) for p, s in bids.items() if s > 0]
            ask_prices = [float(p) for p, s in asks.items() if s > 0]
            best_bid = max(bid_prices) if bid_prices else 0.0
            best_ask = min(ask_prices) if ask_prices else 0.0
            spread = round(best_ask - best_bid, 2) if best_bid and best_ask else 0.0
            result[tid]["book_snapshots"].append({
                "offset": round(ts - boundary, 1) if boundary else round(ts - start_time, 1),
                "timestamp": ts,
                "bids": {p: s for p, s in bids.items() if s > 0},
                "asks": {p: s for p, s in asks.items() if s > 0},
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread": spread,
                "total_bid_size": round(sum(s for s in bids.values() if s > 0), 2),
                "total_ask_size": round(sum(s for s in asks.values() if s > 0), 2),
                "bid_levels": len([s for s in bids.values() if s > 0]),
                "ask_levels": len([s for s in asks.values() if s > 0]),
            })

    # Take initial snapshot (baseline)
    _take_book_snapshot(start_time)

    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({"type": "market", "assets_ids": []}))
        await ws.send(json.dumps({"assets_ids": token_ids, "operation": "subscribe"}))
        log.info("WS connected, subscribed to %d tokens", len(token_ids))

        end_time = start_time + duration_sec
        event_count = 0

        while True:
            remaining = end_time - time.time()
            if remaining <= 0:
                break
            try:
                raw_msg = await asyncio.wait_for(ws.recv(), timeout=min(5.0, remaining))
            except asyncio.TimeoutError:
                # Check if snapshot is due even on timeout
                now = time.time()
                if now >= next_snap_time:
                    _take_book_snapshot(now)
                    next_snap_time = now + SNAP_INTERVAL
                continue
            except websockets.ConnectionClosed:
                log.warning("WS connection closed")
                break

            try:
                msg = json.loads(raw_msg)
            except json.JSONDecodeError:
                continue

            if not isinstance(msg, dict) or msg.get("event_type") != "price_change":
                continue

            ts = time.time()
            bucket_idx = int(ts - start_time)  # 1-second buckets
            ws_ts = msg.get("timestamp")
            event_count += 1

            for pc in msg.get("price_changes", []):
                token_id = pc.get("asset_id", "")
                if token_id not in token_set:
                    continue

                side = pc.get("side", "")
                price_str = pc.get("price", "0")
                new_size = float(pc.get("size", "0"))
                price = round(float(price_str), 2)
                order_hash = pc.get("hash", "")
                ws_best_bid = pc.get("best_bid", "")
                ws_best_ask = pc.get("best_ask", "")

                key = (token_id, price_str)
                old_size = prev_size.get(key, 0.0)
                delta = round(new_size - old_size, 2)
                prev_size[key] = new_size

                # Classify event type
                if delta > 0 and old_size == 0.0:
                    event_type = "ADD"
                elif delta > 0:
                    event_type = "INCREASE"
                elif delta < 0 and new_size > 0:
                    event_type = "DECREASE"
                elif delta < 0 and new_size == 0:
                    event_type = "REMOVE"
                else:
                    continue  # delta == 0, skip

                side_label = "bid" if side == "BUY" else "ask"
                side_key = "bids" if side == "BUY" else "asks"

                # Update book state
                if new_size > 0:
                    book[token_id][side_key][price_str] = new_size
                else:
                    book[token_id][side_key].pop(price_str, None)

                seq_counter += 1
                result[token_id]["events"].append({
                    "seq": seq_counter,
                    "ws_ts": ws_ts,
                    "timestamp": ts,
                    "snapshot_idx": bucket_idx,
                    "side": side_label,
                    "price": price,
                    "size_delta": delta,
                    "new_size": new_size,
                    "old_size": round(old_size, 2),
                    "event_type": event_type,
                    "new_level": old_size == 0.0,
                    "order_hash": order_hash,
                    "best_bid": ws_best_bid,
                    "best_ask": ws_best_ask,
                })

            # Periodic book snapshots
            if ts >= next_snap_time:
                _take_book_snapshot(ts)
                next_snap_time = ts + SNAP_INTERVAL

    # Final snapshot
    _take_book_snapshot(time.time())

    total_events = sum(len(v["events"]) for v in result.values())
    total_snaps = sum(len(v["book_snapshots"]) for v in result.values())
    log.info(
        "WS collected %d events (%d snapshots) from %d WS messages across %d tokens in %ds",
        total_events, total_snaps, event_count, len(token_ids), duration_sec,
    )
    return result


def _parse_activity_ts(ts_str: str) -> float:
    """Parse Activity API ISO timestamp to epoch seconds."""
    ts_str = ts_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(ts_str)
    return dt.timestamp()


async def _poll_gabagool_activity(
    proxy_address: str,
    condition_id: str,
    duration_sec: int,
    boundary: float,
) -> list[dict]:
    """Poll gabagool's Activity API concurrently with WS collection.

    Deduplicates by transactionHash, filters to matching condition_id.
    """
    seen_tx: set[str] = set()
    trades: list[dict] = []
    end_time = time.time() + duration_sec
    poll_count = 0

    while time.time() < end_time:
        try:
            resp = await asyncio.to_thread(
                requests.get,
                ACTIVITY_URL,
                params={"user": proxy_address, "limit": 50},
                timeout=10,
            )
            resp.raise_for_status()
            items = resp.json()
            poll_count += 1
        except Exception as exc:
            log.debug("ACTIVITY_POLL_FAIL │ %s", exc)
            await asyncio.sleep(ACTIVITY_POLL_INTERVAL)
            continue

        for item in items:
            tx = item.get("transactionHash", "")
            if not tx or tx in seen_tx:
                continue
            seen_tx.add(tx)

            # Filter to matching condition_id
            item_cid = item.get("conditionId", "")
            if condition_id and item_cid != condition_id:
                continue

            # Filter non-trade events
            side = item.get("side", "")
            outcome = item.get("outcome", "")
            price = float(item.get("price", 0))
            if not side or not outcome or price <= 0:
                continue

            ts_str = str(item.get("timestamp", ""))
            epoch = _parse_activity_ts(ts_str) if ts_str else time.time()

            trades.append({
                "offset": round(epoch - boundary, 1),
                "epoch": epoch,
                "side": side,
                "price": price,
                "size": float(item.get("size", 0)),
                "usdc_size": float(item.get("usdcSize", 0)),
                "outcome": outcome,
                "tx_hash": tx,
            })

        remaining = end_time - time.time()
        if remaining > ACTIVITY_POLL_INTERVAL:
            await asyncio.sleep(ACTIVITY_POLL_INTERVAL)

    log.info(
        "Activity polling: %d polls, %d trades found (%d unique tx)",
        poll_count, len(trades), len(seen_tx),
    )
    return trades


async def _ws_collect_with_activity(
    token_ids: list[str],
    duration_sec: int,
    boundary: float,
    proxy_address: str | None,
    condition_id: str,
) -> tuple[dict[str, dict], list[dict]]:
    """Run WS collection and activity polling concurrently."""
    if proxy_address:
        ws_data, gaba_trades = await asyncio.gather(
            _ws_collect(token_ids, duration_sec, boundary),
            _poll_gabagool_activity(proxy_address, condition_id, duration_sec, boundary),
        )
    else:
        ws_data = await _ws_collect(token_ids, duration_sec, boundary)
        gaba_trades = []
    return ws_data, gaba_trades


async def _extended_activity_poll(
    proxy_address: str,
    condition_id: str,
    extend_sec: int,
    boundary: float,
    existing_trades: list[dict],
) -> list[dict]:
    """Continue polling Activity API for additional time after WS collection ends.

    Deduplicates against already-seen tx_hashes from existing_trades.
    Returns combined list (existing + new).
    """
    seen_tx: set[str] = {t["tx_hash"] for t in existing_trades}
    new_trades: list[dict] = []
    end_time = time.time() + extend_sec
    poll_count = 0

    log.info(
        "Extended activity polling for %ds (already have %d trades)...",
        extend_sec, len(existing_trades),
    )

    while time.time() < end_time:
        try:
            resp = await asyncio.to_thread(
                requests.get,
                ACTIVITY_URL,
                params={"user": proxy_address, "limit": 50},
                timeout=10,
            )
            resp.raise_for_status()
            items = resp.json()
            poll_count += 1
        except Exception as exc:
            log.debug("EXTENDED_POLL_FAIL │ %s", exc)
            await asyncio.sleep(ACTIVITY_POLL_INTERVAL)
            continue

        for item in items:
            tx = item.get("transactionHash", "")
            if not tx or tx in seen_tx:
                continue
            seen_tx.add(tx)

            item_cid = item.get("conditionId", "")
            if condition_id and item_cid != condition_id:
                continue

            side = item.get("side", "")
            outcome = item.get("outcome", "")
            price = float(item.get("price", 0))
            if not side or not outcome or price <= 0:
                continue

            ts_str = str(item.get("timestamp", ""))
            epoch = _parse_activity_ts(ts_str) if ts_str else time.time()

            new_trades.append({
                "offset": round(epoch - boundary, 1),
                "epoch": epoch,
                "side": side,
                "price": price,
                "size": float(item.get("size", 0)),
                "usdc_size": float(item.get("usdcSize", 0)),
                "outcome": outcome,
                "tx_hash": tx,
            })

        remaining = end_time - time.time()
        if remaining > ACTIVITY_POLL_INTERVAL:
            await asyncio.sleep(ACTIVITY_POLL_INTERVAL)

    log.info(
        "Extended polling done: %d polls, %d new trades (total: %d)",
        poll_count, len(new_trades), len(existing_trades) + len(new_trades),
    )
    return existing_trades + new_trades


def _compute_deltas(snapshots: list[dict]) -> list[dict]:
    """Find all size increases between consecutive snapshots.

    Tracks both new levels AND size bumps at existing prices — gabagool adds
    shares to prices that may already have orders from other participants.
    """
    changes = []
    for i in range(1, len(snapshots)):
        ts = snapshots[i]["timestamp"]

        for side_key in ("bids", "asks"):
            side_label = "bid" if side_key == "bids" else "ask"
            prev = snapshots[i - 1][side_key]
            curr = snapshots[i][side_key]

            for price, curr_size in curr.items():
                prev_size = prev.get(price, 0.0)
                delta = round(curr_size - prev_size, 2)
                if delta > 0:
                    changes.append({
                        "snapshot_idx": i,
                        "timestamp": ts,
                        "side": side_label,
                        "price": price,
                        "size_delta": delta,
                        "new_level": price not in prev,
                    })

    return changes


def _find_bursts(changes: list[dict], boundary: float) -> list[dict]:
    """Group changes by snapshot and rank by bid-change count."""
    by_snap: dict[int, list[dict]] = defaultdict(list)
    for c in changes:
        by_snap[c["snapshot_idx"]].append(c)

    bursts = []
    for idx, items in sorted(by_snap.items()):
        bids = [c for c in items if c["side"] == "bid"]
        asks = [c for c in items if c["side"] == "ask"]
        if not bids and not asks:
            continue
        bursts.append({
            "snapshot_idx": idx,
            "timestamp": items[0]["timestamp"],
            "offset": round(items[0]["timestamp"] - boundary, 1),
            "bid_changes": len(bids),
            "ask_changes": len(asks),
            "bids": bids,
            "asks": asks,
        })

    bursts.sort(key=lambda b: b["bid_changes"], reverse=True)
    return bursts


def _analyze_burst(burst: dict, expected_size: int | None) -> dict:
    """Analyze a single burst for gabagool grid fingerprint."""
    bids = burst["bids"]
    if not bids:
        return {"detected": False, "reason": "no bids in burst"}

    # Penny spacing among bid prices
    prices = sorted(b["price"] for b in bids)
    penny_gaps = 0
    if len(prices) >= 2:
        for j in range(1, len(prices)):
            if round(prices[j] - prices[j - 1], 2) == 0.01:
                penny_gaps += 1
    penny_rate = penny_gaps / max(1, len(prices) - 1)

    # Size-delta distribution
    delta_counts: dict[float, int] = defaultdict(int)
    for b in bids:
        delta_counts[b["size_delta"]] += 1

    dominant_delta = max(delta_counts, key=delta_counts.get) if delta_counts else 0
    dominant_count = delta_counts.get(dominant_delta, 0)
    dominance = dominant_count / max(1, len(bids))

    # How many levels match expected gabagool size (within 1 share)?
    expected_count = 0
    if expected_size:
        expected_count = sum(
            1 for b in bids if abs(b["size_delta"] - expected_size) < 1
        )

    detected = len(bids) >= 15 and (penny_rate > 0.4 or dominance > 0.3)

    return {
        "detected": detected,
        "bid_count": len(bids),
        "ask_count": len(burst["asks"]),
        "penny_rate": round(penny_rate, 2),
        "dominant_delta": dominant_delta,
        "dominant_share": round(dominance, 2),
        "expected_size": expected_size,
        "expected_match_count": expected_count,
        "price_range": (prices[0], prices[-1]),
        "new_levels": sum(1 for b in bids if b["new_level"]),
        "size_bumps": sum(1 for b in bids if not b["new_level"]),
        "delta_distribution": dict(sorted(delta_counts.items(), key=lambda x: -x[1])[:10]),
    }


def _summarize_run(run: list[dict], delta: float, boundary: float) -> dict:
    """Summarize a consecutive run of events into a bot descriptor."""
    prices = sorted(set(round(e["price"], 2) for e in run))

    penny_gaps = 0
    if len(prices) >= 2:
        for j in range(1, len(prices)):
            if round(prices[j] - prices[j - 1], 2) == 0.01:
                penny_gaps += 1
    penny_rate = penny_gaps / max(1, len(prices) - 1)

    start_ts = run[0]["timestamp"]
    end_ts = run[-1]["timestamp"]

    return {
        "bot_label": "",  # assigned after sorting
        "delta": delta,
        "event_count": len(run),
        "start_offset": round(start_ts - boundary, 1),
        "end_offset": round(end_ts - boundary, 1),
        "duration": round(end_ts - start_ts, 1),
        "level_count": len(prices),
        "penny_rate": round(penny_rate, 2),
        "prices": prices,
        "is_gabagool": False,  # updated by caller if matched
    }


def _find_bot_runs(
    events: list[dict],
    boundary: float,
    gap_threshold: float = 0.5,
    min_run_length: int = 10,
) -> list[dict]:
    """Cluster consecutive same-delta bid additions into bot runs.

    Events within gap_threshold seconds with the same size_delta are grouped.
    Runs with fewer than min_run_length events are discarded.
    """
    bid_adds = [e for e in events if e["side"] == "bid" and e["size_delta"] > 0]
    if not bid_adds:
        return []

    # Group by size_delta
    by_delta: dict[float, list[dict]] = defaultdict(list)
    for e in bid_adds:
        by_delta[e["size_delta"]].append(e)

    all_runs = []
    for delta, group in by_delta.items():
        group.sort(key=lambda e: e["timestamp"])

        # Find consecutive runs where gap < threshold
        run_start = 0
        for i in range(1, len(group)):
            gap = group[i]["timestamp"] - group[i - 1]["timestamp"]
            if gap >= gap_threshold:
                run = group[run_start:i]
                if len(run) >= min_run_length:
                    all_runs.append(_summarize_run(run, delta, boundary))
                run_start = i
        # Final run
        run = group[run_start:]
        if len(run) >= min_run_length:
            all_runs.append(_summarize_run(run, delta, boundary))

    # Sort by event count descending, assign labels
    all_runs.sort(key=lambda r: -r["event_count"])
    for i, r in enumerate(all_runs):
        r["bot_label"] = chr(ord("A") + i) if i < 26 else f"#{i+1}"

    return all_runs


def _reconstruct_gabagool_grid(
    events: list[dict],
    expected_delta: int,
    boundary: float,
) -> dict | None:
    """Reconstruct gabagool's grid ignoring timing gaps.

    Uses delta fingerprint + penny-grid completeness instead of consecutive
    timing to unify fragmented WS event runs into one grid.
    """
    # Filter: bid additions with matching delta, within [boundary-5, boundary+60]
    candidates = [
        e for e in events
        if e["side"] == "bid"
        and e["size_delta"] > 0
        and abs(e["size_delta"] - expected_delta) <= 1.0
        and (e["timestamp"] - boundary) >= -5.0
        and (e["timestamp"] - boundary) <= 60.0
    ]
    if len(candidates) < 10:
        return None

    # Group by price level
    per_level: dict[float, dict] = {}
    for e in candidates:
        price = round(e["price"], 2)
        if price not in per_level:
            per_level[price] = {
                "first_seen": e["timestamp"] - boundary,
                "total_added": 0.0,
                "event_count": 0,
            }
        per_level[price]["total_added"] += e["size_delta"]
        per_level[price]["event_count"] += 1
        offset = e["timestamp"] - boundary
        if offset < per_level[price]["first_seen"]:
            per_level[price]["first_seen"] = offset

    # Reference penny-grid: $0.01 - $0.99
    reference = {round(i * 0.01, 2) for i in range(1, 100)}
    detected_prices = set(per_level.keys())
    coverage = detected_prices & reference
    missing = sorted(reference - detected_prices)

    # Penny spacing rate among detected levels
    sorted_prices = sorted(detected_prices)
    penny_gaps = 0
    if len(sorted_prices) >= 2:
        for j in range(1, len(sorted_prices)):
            if round(sorted_prices[j] - sorted_prices[j - 1], 2) == 0.01:
                penny_gaps += 1
    penny_rate = penny_gaps / max(1, len(sorted_prices) - 1)

    # Size consistency: how many levels have total_added exactly == expected_delta
    exact_match = sum(
        1 for info in per_level.values()
        if abs(info["total_added"] - expected_delta) < 0.5
    )
    exact_match_rate = exact_match / max(1, len(per_level))

    # Timing
    offsets = [info["first_seen"] for info in per_level.values()]
    first_offset = min(offsets)
    last_offset = max(offsets)

    # Confidence score (0-100)
    coverage_pct = len(coverage) / 99
    score_coverage = min(40, coverage_pct * 40)  # 40 pts
    score_penny = min(30, penny_rate * 30)  # 30 pts
    score_size = min(20, exact_match_rate * 20)  # 20 pts
    # Timing: bonus if posting completes within 45s
    posting_duration = last_offset - first_offset
    timing_factor = max(0, 1 - posting_duration / 45)
    score_timing = min(10, timing_factor * 10)  # 10 pts
    confidence = int(round(score_coverage + score_penny + score_size + score_timing))

    # Size distribution for anomaly reporting
    size_dist: dict[float, int] = defaultdict(int)
    for info in per_level.values():
        size_dist[round(info["total_added"], 1)] += 1

    return {
        "detected": True,
        "confidence": confidence,
        "coverage": len(coverage),
        "coverage_pct": round(coverage_pct * 100, 1),
        "missing_levels": missing,
        "penny_rate": round(penny_rate, 2),
        "exact_match_rate": round(exact_match_rate, 3),
        "size_distribution": dict(sorted(size_dist.items(), key=lambda x: -x[1])),
        "first_event_offset": round(first_offset, 1),
        "last_event_offset": round(last_offset, 1),
        "posting_duration": round(posting_duration, 1),
        "per_level": {
            price: {
                "first_seen": round(info["first_seen"], 1),
                "total_added": round(info["total_added"], 1),
                "event_count": info["event_count"],
            }
            for price, info in sorted(per_level.items())
        },
    }


def _format_book_display(
    snapshot: dict,
    max_levels: int = 10,
    title: str = "",
) -> str:
    """Format a book snapshot for console display (Polymarket-style)."""
    lines = []
    if title:
        lines.append(f"  {title}")
        lines.append("")

    # Parse bids/asks from snapshot (price_str → size)
    bids_raw = snapshot.get("bids", {})
    asks_raw = snapshot.get("asks", {})

    bid_levels = sorted(
        [(float(p), s) for p, s in bids_raw.items() if s > 0],
        key=lambda x: -x[0],
    )[:max_levels]
    ask_levels = sorted(
        [(float(p), s) for p, s in asks_raw.items() if s > 0],
        key=lambda x: x[0],
    )[:max_levels]

    # Asks (ascending from spread, display reversed so highest on top)
    lines.append("  ASKS")
    for price, size in reversed(ask_levels):
        notional = price * size
        lines.append(f"    ${price:.2f}  {size:8.1f} shares  ${notional:8.2f}")

    spread = snapshot.get("spread", 0.0)
    lines.append(f"  {'─' * 10} spread: ${spread:.2f} {'─' * 10}")

    # Bids (descending from spread)
    lines.append("  BIDS")
    for price, size in bid_levels:
        notional = price * size
        lines.append(f"    ${price:.2f}  {size:8.1f} shares  ${notional:8.2f}")

    return "\n".join(lines)


def _print_delta_histogram(events: list[dict], label: str) -> None:
    """Print per-event delta distribution for positive bid additions."""
    bid_adds = [e for e in events if e["side"] == "bid" and e["size_delta"] > 0]
    if not bid_adds:
        print(f"\n--- {label} raw delta histogram (bid additions) ---")
        print("  No positive bid deltas found.")
        return

    delta_counts: dict[float, int] = defaultdict(int)
    for e in bid_adds:
        delta_counts[e["size_delta"]] += 1

    total = len(bid_adds)
    ranked = sorted(delta_counts.items(), key=lambda x: -x[1])
    max_count = ranked[0][1] if ranked else 1

    print(f"\n--- {label} raw delta histogram (bid additions, n={total}) ---")
    print(f"  {'delta':>8}  {'count':>6}  {'pct':>7}")
    for delta, count in ranked[:15]:
        pct = count / total * 100
        bar_len = int(count / max_count * 30)
        bar = "█" * bar_len
        print(f"  {delta:8.1f}  {count:6d}  {pct:6.1f}%  {bar}")


def _print_event_breakdown(events: list[dict], label: str) -> None:
    """Print event type counts (ADD/INCREASE/DECREASE/REMOVE)."""
    type_counts: dict[str, int] = defaultdict(int)
    for e in events:
        type_counts[e.get("event_type", "UNKNOWN")] += 1

    total = len(events)
    print(f"\n--- {label} event breakdown (n={total}) ---")
    for etype in ["ADD", "INCREASE", "DECREASE", "REMOVE"]:
        count = type_counts.get(etype, 0)
        pct = count / max(1, total) * 100
        print(f"  {etype:<12}  {count:5d}  ({pct:5.1f}%)")
    print(f"  {'Total':<12}  {total:5d}")


def _print_hash_clusters(bots: list[dict], label: str, expected_size: int | None) -> None:
    """Print bot detection table from consecutive-run clustering."""
    print(f"\n--- {label} bot detection (consecutive-run clustering) ---")
    if not bots:
        print("  No bot runs detected.")
        return

    print(
        f"  {'Bot':>4}  {'delta':>7}  {'events':>7}  "
        f"{'time range':>22}  {'dur':>6}  {'levels':>7}  {'penny':>6}"
    )
    for bot in bots:
        gaba_flag = ""
        if expected_size and abs(bot["delta"] - expected_size) < 1:
            gaba_flag = "  <-- gabagool?"
            bot["is_gabagool"] = True
        time_range = f"{bot['start_offset']:+.1f}s -> {bot['end_offset']:+.1f}s"
        print(
            f"  {bot['bot_label']:>4}  {bot['delta']:7.1f}  {bot['event_count']:7d}  "
            f"{time_range:>22}  {bot['duration']:5.1f}s  {bot['level_count']:7d}  "
            f"{bot['penny_rate']:5.0%}{gaba_flag}"
        )


def _print_gabagool_grid(grid: dict | None, label: str, expected_delta: int | None) -> None:
    """Print gabagool grid reconstruction results."""
    print(f"\n--- {label} gabagool grid reconstruction ---")
    if grid is None:
        print("  Not enough data to reconstruct grid.")
        return

    print(f"  Confidence:   {grid['confidence']}/100")
    print(f"  Coverage:     {grid['coverage']}/99 levels ({grid['coverage_pct']}%)")
    print(f"  Expected Δ:   {expected_delta} shares")

    # Exact size match count
    per_level = grid["per_level"]
    if expected_delta:
        exact = sum(
            1 for info in per_level.values()
            if abs(info["total_added"] - expected_delta) < 0.5
        )
        print(f"  Size match:   {exact}/{len(per_level)} levels exact ({grid['exact_match_rate']:.1%})")
    print(f"  Penny rate:   {grid['penny_rate']:.0%}")
    print(
        f"  Timing:       {grid['first_event_offset']:+.1f}s -> "
        f"{grid['last_event_offset']:+.1f}s "
        f"({grid['posting_duration']:.1f}s posting duration)"
    )

    # Missing levels
    missing = grid["missing_levels"]
    if missing:
        formatted = " ".join(f"${p:.2f}" for p in missing[:20])
        suffix = f" ... (+{len(missing)-20} more)" if len(missing) > 20 else ""
        print(f"  Missing ({len(missing)}): {formatted}{suffix}")
    else:
        print(f"  Missing: none (full 99-level grid!)")

    # Size anomalies: levels where total_added != expected_delta
    if expected_delta:
        anomalies = [
            (price, info) for price, info in per_level.items()
            if abs(info["total_added"] - expected_delta) >= 0.5
        ]
        if anomalies:
            parts = [
                f"${price:.2f}: {info['total_added']:.0f} total ({info['event_count']} events)"
                for price, info in anomalies[:8]
            ]
            suffix = f" ... (+{len(anomalies)-8} more)" if len(anomalies) > 8 else ""
            print(f"  Size anomalies: {', '.join(parts)}{suffix}")

    # Level timeline (first/last 5 by appearance order)
    by_appearance = sorted(per_level.items(), key=lambda x: x[1]["first_seen"])
    if len(by_appearance) >= 10:
        print(f"  Level timeline (first/last 5 by appearance):")
        for price, info in by_appearance[:5]:
            print(f"    ${price:.2f}  {info['first_seen']:+.1f}s  Δ={info['total_added']:.0f}")
        print(f"    ...")
        for price, info in by_appearance[-5:]:
            print(f"    ${price:.2f}  {info['first_seen']:+.1f}s  Δ={info['total_added']:.0f}")


def _match_fills_to_grid(
    trades: list[dict],
    grid: dict | None,
    label: str,
) -> dict | None:
    """Cross-reference Activity API trades with reconstructed grid levels.

    For each trade, checks if round(price, 2) exists in grid's per_level.
    """
    if grid is None or not trades:
        return None

    per_level = grid["per_level"]
    matched = []
    unmatched = []

    for t in trades:
        price = round(t["price"], 2)
        if price in per_level:
            matched.append(t)
        else:
            unmatched.append(t)

    levels_with_fills = set(round(t["price"], 2) for t in matched)

    return {
        "matched_fills": len(matched),
        "unmatched_fills": len(unmatched),
        "grid_levels_with_fills": len(levels_with_fills),
        "fill_rate": round(len(levels_with_fills) / max(1, len(per_level)) * 100, 1),
        "matched_trades": matched,
        "unmatched_trades": unmatched,
    }


def _print_fill_validation(fill_report: dict | None, label: str) -> None:
    """Print fill validation results."""
    print(f"\n--- {label} fill validation ---")
    if fill_report is None:
        print("  No fill data to validate (grid missing or no trades).")
        return

    print(f"  Matched fills:     {fill_report['matched_fills']}")
    print(f"  Unmatched fills:   {fill_report['unmatched_fills']}")
    print(f"  Grid levels hit:   {fill_report['grid_levels_with_fills']}")
    print(f"  Fill rate:         {fill_report['fill_rate']}% of grid levels")

    if fill_report["unmatched_trades"]:
        print(f"  Unmatched prices:")
        for t in fill_report["unmatched_trades"][:5]:
            print(f"    ${t['price']:.2f}  size={t['size']:.1f}  {t['side']}")


def _print_gabagool_activity(
    trades: list[dict],
    up_bots: list[dict],
    down_bots: list[dict],
) -> None:
    """Print gabagool direct attribution from Activity API."""
    print(f"\n--- GABAGOOL DIRECT ATTRIBUTION (Activity API) ---")
    if not trades:
        print("  No gabagool trades captured during window.")
        return

    buys = [t for t in trades if t["side"] == "BUY"]
    sells = [t for t in trades if t["side"] == "SELL"]
    up_trades = [t for t in trades if t["outcome"] == "Up"]
    down_trades = [t for t in trades if t["outcome"] == "Down"]

    print(f"  Trades: {len(trades)} total ({len(buys)} BUY / {len(sells)} SELL)")
    print(f"  Sides:  {len(up_trades)} Up / {len(down_trades)} Down")

    if trades:
        offsets = [t["offset"] for t in trades]
        print(f"  Window: {min(offsets):+.1f}s to {max(offsets):+.1f}s")
        total_usdc = sum(t["usdc_size"] for t in trades)
        print(f"  Volume: ${total_usdc:.2f}")

    # Timeline
    print(
        f"\n  {'offset':>8}  {'side':>4}  {'outcome':>6}  "
        f"{'price':>6}  {'size':>6}  {'usdc':>8}  tx"
    )
    for t in sorted(trades, key=lambda x: x["epoch"]):
        print(
            f"  {t['offset']:+7.1f}s  {t['side']:>4}  {t['outcome']:>6}  "
            f"${t['price']:.2f}  {t['size']:5.1f}  ${t['usdc_size']:7.2f}  "
            f"{t['tx_hash'][:10]}"
        )

    # Cross-reference with bot clusters
    gaba_up = [b for b in up_bots if b.get("is_gabagool")]
    gaba_down = [b for b in down_bots if b.get("is_gabagool")]
    if gaba_up or gaba_down:
        print(f"\n  Cross-reference with bot clusters:")
        for b in gaba_up:
            print(
                f"    UP Bot {b['bot_label']}: delta={b['delta']}, "
                f"{b['event_count']} events, "
                f"{b['start_offset']:+.1f}s -> {b['end_offset']:+.1f}s"
            )
        for b in gaba_down:
            print(
                f"    DOWN Bot {b['bot_label']}: delta={b['delta']}, "
                f"{b['event_count']} events, "
                f"{b['start_offset']:+.1f}s -> {b['end_offset']:+.1f}s"
            )


def _print_report(
    asset: str,
    tf: str,
    market_slug: str,
    boundary: float,
    up_bursts: list[dict],
    down_bursts: list[dict],
    up_peak: dict | None,
    down_peak: dict | None,
    up_snapshots: list[dict],
    down_snapshots: list[dict],
    up_events: list[dict] | None = None,
    down_events: list[dict] | None = None,
    up_book_snaps: list[dict] | None = None,
    down_book_snaps: list[dict] | None = None,
    up_bots: list[dict] | None = None,
    down_bots: list[dict] | None = None,
    gaba_trades: list[dict] | None = None,
    expected_size: int | None = None,
    up_grid: dict | None = None,
    down_grid: dict | None = None,
    up_fill_report: dict | None = None,
    down_fill_report: dict | None = None,
) -> None:
    """Print burst-focused analysis report."""
    bt = datetime.fromtimestamp(boundary, tz=timezone.utc).strftime("%H:%M:%S UTC")

    print("\n" + "=" * 70)
    print(f"  BOOK ANALYSIS — {asset} {tf}")
    print(f"  Market: {market_slug}")
    print(f"  Market open: {bt}")
    print("=" * 70)

    # Bid-count timeline (total bids per snapshot)
    for label, snaps in [("UP", up_snapshots), ("DOWN", down_snapshots)]:
        print(f"\n--- {label} bid-count timeline ---")
        for s in snaps:
            off = s["timestamp"] - boundary
            n = len(s["bids"])
            bar = "#" * min(n, 99)
            print(f"  {off:+6.1f}s  {n:3d} bids  {bar}")

    # Burst ranking
    for label, bursts, peak in [
        ("UP", up_bursts, up_peak),
        ("DOWN", down_bursts, down_peak),
    ]:
        print(f"\n--- {label} top bursts (by bid-change count) ---")
        for i, b in enumerate(bursts[:5]):
            flag = " <<<" if peak and b["snapshot_idx"] == bursts[0]["snapshot_idx"] and i == 0 else ""
            print(
                f"  #{i+1}  {b['offset']:+.1f}s  "
                f"+{b['bid_changes']} bids  +{b['ask_changes']} asks{flag}"
            )

        if not peak or not peak.get("detected"):
            print(f"  No grid burst detected.")
            continue

        print(f"\n--- {label} peak burst analysis ---")
        print(f"  Grid detected:        {peak['detected']}")
        print(f"  Bid changes:          {peak['bid_count']}  ({peak['new_levels']} new + {peak['size_bumps']} size bumps)")
        print(f"  Ask changes:          {peak['ask_count']}")
        print(f"  Price range:          ${peak['price_range'][0]:.2f} — ${peak['price_range'][1]:.2f}")
        print(f"  Penny spacing rate:   {peak['penny_rate']}")
        print(f"  Dominant delta:       {peak['dominant_delta']} shares ({peak['dominant_share']:.0%})")
        print(f"  Expected gaba size:   {peak['expected_size']}")
        print(f"  Matching levels:      {peak['expected_match_count']}")
        print(f"  Delta distribution:   {peak['delta_distribution']}")

    # WS-specific enriched sections
    if up_events is not None or down_events is not None:
        print("\n" + "=" * 70)
        print("  WS ENRICHED ANALYSIS")
        print("=" * 70)

        for label, events, book_snaps in [
            ("UP", up_events or [], up_book_snaps or []),
            ("DOWN", down_events or [], down_book_snaps or []),
        ]:
            _print_event_breakdown(events, label)
            _print_delta_histogram(events, label)

            if not book_snaps:
                continue

            # Book at boundary (snapshot closest to offset 0)
            boundary_snap = min(book_snaps, key=lambda s: abs(s["offset"]))
            print(f"\n--- {label} book at boundary (offset {boundary_snap['offset']:+.1f}s) ---")
            print(f"  Levels: {boundary_snap['bid_levels']} bids / {boundary_snap['ask_levels']} asks")
            print(f"  Size:   {boundary_snap['total_bid_size']:.0f} bid / {boundary_snap['total_ask_size']:.0f} ask")
            print(f"  Spread: ${boundary_snap['spread']:.2f}")
            print(_format_book_display(boundary_snap, max_levels=10))

            # Book at peak burst (~+15s)
            peak_snap = min(book_snaps, key=lambda s: abs(s["offset"] - 15.0))
            print(f"\n--- {label} book at +15s (offset {peak_snap['offset']:+.1f}s) ---")
            print(f"  Levels: {peak_snap['bid_levels']} bids / {peak_snap['ask_levels']} asks")
            print(f"  Size:   {peak_snap['total_bid_size']:.0f} bid / {peak_snap['total_ask_size']:.0f} ask")
            print(f"  Spread: ${peak_snap['spread']:.2f}")
            print(_format_book_display(peak_snap, max_levels=10))

            # Book diff: boundary → peak
            pre_bids = {float(p): s for p, s in boundary_snap["bids"].items()}
            post_bids = {float(p): s for p, s in peak_snap["bids"].items()}
            all_prices = sorted(set(pre_bids) | set(post_bids))
            new_levels = [p for p in all_prices if p not in pre_bids and p in post_bids]
            removed_levels = [p for p in all_prices if p in pre_bids and p not in post_bids]
            changed_levels = [
                p for p in all_prices
                if p in pre_bids and p in post_bids
                and abs(post_bids[p] - pre_bids[p]) > 0.01
            ]
            print(f"\n--- {label} book diff (boundary → +15s) ---")
            print(f"  New bid levels:      {len(new_levels)}")
            print(f"  Removed bid levels:  {len(removed_levels)}")
            print(f"  Changed bid levels:  {len(changed_levels)}")
            total_size_change = (
                sum(post_bids.get(p, 0) for p in all_prices)
                - sum(pre_bids.get(p, 0) for p in all_prices)
            )
            print(f"  Total bid size Δ:    {total_size_change:+.1f} shares")

    # Bot detection section (WS mode only)
    if up_bots is not None or down_bots is not None:
        print("\n" + "=" * 70)
        print("  BOT DETECTION")
        print("=" * 70)
        _print_hash_clusters(up_bots or [], "UP", expected_size)
        _print_hash_clusters(down_bots or [], "DOWN", expected_size)

    # Gabagool grid reconstruction (WS mode only)
    if up_grid is not None or down_grid is not None:
        print("\n" + "=" * 70)
        print("  GABAGOOL GRID RECONSTRUCTION")
        print("=" * 70)
        _print_gabagool_grid(up_grid, "UP", expected_size)
        _print_gabagool_grid(down_grid, "DOWN", expected_size)

    # Fill validation
    if up_fill_report is not None or down_fill_report is not None:
        print("\n" + "=" * 70)
        print("  FILL VALIDATION")
        print("=" * 70)
        _print_fill_validation(up_fill_report, "UP")
        _print_fill_validation(down_fill_report, "DOWN")

    # Gabagool direct attribution (WS mode + activity polling)
    if gaba_trades is not None:
        print("\n" + "=" * 70)
        print("  GABAGOOL DIRECT ATTRIBUTION")
        print("=" * 70)
        _print_gabagool_activity(gaba_trades, up_bots or [], down_bots or [])

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description="One-time book analysis around market boundary")
    parser.add_argument("--asset", default="bitcoin", choices=["bitcoin", "ethereum"])
    parser.add_argument("--timeframe", default="5m", choices=["5m", "15m", "1h"])
    parser.add_argument("--duration", type=int, default=90, help="Polling duration in seconds")
    parser.add_argument("--interval", type=float, default=2.5, help="Poll interval in seconds")
    parser.add_argument("--lead", type=int, default=60, help="Seconds before market open to start")
    parser.add_argument("--ws", action="store_true", help="Use WebSocket instead of REST polling")
    parser.add_argument("--save", action="store_true", help="Save results to data/analysis/")
    parser.add_argument("--gabagool-address", default=GABAGOOL_PROXY, help="Gabagool proxy address")
    parser.add_argument("--no-activity", action="store_true", help="Skip Activity API polling")
    parser.add_argument("--activity-extend", type=int, default=0, help="Extra seconds to poll Activity API after WS ends")
    args = parser.parse_args()

    expected_size = GABAGOOL_SIZES.get((args.asset, args.timeframe))
    mode = "ws" if args.ws else f"rest (interval={args.interval:.1f}s)"
    log.info(
        "Config: asset=%s tf=%s expected_size=%s duration=%ds mode=%s lead=%ds",
        args.asset, args.timeframe, expected_size, args.duration, mode, args.lead,
    )

    # Find next market to open
    interval = TF_INTERVAL[args.timeframe]
    log.info("Searching for next %s %s market to open...", args.asset, args.timeframe)
    market = _find_next_market(args.asset, args.timeframe)
    if not market:
        log.error("No upcoming market found for %s %s", args.asset, args.timeframe)
        return

    start_time = market.end_time - interval
    log.info("Found market: %s", market.slug)
    log.info("  Up token:   %s", market.up_token_id[:16])
    log.info("  Down token: %s", market.down_token_id[:16])

    # Wait until lead seconds before market OPEN
    boundary = start_time
    wait_until = boundary - args.lead
    now = time.time()
    bt_str = datetime.fromtimestamp(boundary, tz=timezone.utc).strftime("%H:%M:%S UTC")

    if now < wait_until:
        wait_secs = wait_until - now
        log.info("Market opens at %s — waiting %.0fs (starting %ds before)...", bt_str, wait_secs, args.lead)
        time.sleep(wait_secs)
    else:
        log.info("Market opens at %s — already within lead window, starting now", bt_str)

    # Collect data
    token_ids = [market.up_token_id, market.down_token_id]
    up_events: list[dict] | None = None
    down_events: list[dict] | None = None
    up_book_snaps: list[dict] | None = None
    down_book_snaps: list[dict] | None = None
    up_bots: list[dict] | None = None
    down_bots: list[dict] | None = None
    gaba_trades: list[dict] | None = None
    up_grid: dict | None = None
    down_grid: dict | None = None
    up_fill_report: dict | None = None
    down_fill_report: dict | None = None

    if args.ws:
        proxy_addr = None if args.no_activity else args.gabagool_address
        log.info(
            "Starting WebSocket collection for %ds (activity=%s)...",
            args.duration, "off" if proxy_addr is None else proxy_addr[:12],
        )
        ws_data, gaba_trades = asyncio.run(
            _ws_collect_with_activity(
                token_ids, args.duration, boundary,
                proxy_addr, market.condition_id,
            )
        )
        up_data = ws_data[market.up_token_id]
        down_data = ws_data[market.down_token_id]

        # For burst analysis: filter to positive deltas only (backward compat)
        up_changes = [e for e in up_data["events"] if e["size_delta"] > 0]
        down_changes = [e for e in down_data["events"] if e["size_delta"] > 0]

        # Book snapshots for bid-count timeline
        up_snapshots: list[dict] = up_data["book_snapshots"]
        down_snapshots: list[dict] = down_data["book_snapshots"]

        # Full data for enhanced report sections
        up_events = up_data["events"]
        down_events = down_data["events"]
        up_book_snaps = up_data["book_snapshots"]
        down_book_snaps = down_data["book_snapshots"]

        # Bot detection via consecutive-run clustering
        up_bots = _find_bot_runs(up_events, boundary)
        down_bots = _find_bot_runs(down_events, boundary)

        # Grid reconstruction (ignores timing gaps, uses delta fingerprint)
        if expected_size:
            up_grid = _reconstruct_gabagool_grid(up_events, expected_size, boundary)
            down_grid = _reconstruct_gabagool_grid(down_events, expected_size, boundary)

        # Extended activity polling
        if args.activity_extend > 0 and proxy_addr and gaba_trades is not None:
            gaba_trades = asyncio.run(
                _extended_activity_poll(
                    proxy_addr, market.condition_id,
                    args.activity_extend, boundary, gaba_trades,
                )
            )

        # Fill validation: match activity trades to reconstructed grid
        if gaba_trades:
            up_trades = [t for t in gaba_trades if t["outcome"] == "Up"]
            down_trades = [t for t in gaba_trades if t["outcome"] == "Down"]
            up_fill_report = _match_fills_to_grid(up_trades, up_grid, "UP")
            down_fill_report = _match_fills_to_grid(down_trades, down_grid, "DOWN")
    else:
        log.info("Starting REST polling for %ds...", args.duration)
        snapshots = _collect_snapshots(token_ids, args.duration, args.interval)
        up_changes = _compute_deltas(snapshots[market.up_token_id])
        down_changes = _compute_deltas(snapshots[market.down_token_id])
        up_snapshots = snapshots[market.up_token_id]
        down_snapshots = snapshots[market.down_token_id]

    # Analyze via burst detection
    up_bursts = _find_bursts(up_changes, boundary)
    down_bursts = _find_bursts(down_changes, boundary)

    up_peak = _analyze_burst(up_bursts[0], expected_size) if up_bursts else None
    down_peak = _analyze_burst(down_bursts[0], expected_size) if down_bursts else None

    _print_report(
        args.asset, args.timeframe, market.slug, boundary,
        up_bursts, down_bursts, up_peak, down_peak,
        up_snapshots, down_snapshots,
        up_events=up_events,
        down_events=down_events,
        up_book_snaps=up_book_snaps,
        down_book_snaps=down_book_snaps,
        up_bots=up_bots,
        down_bots=down_bots,
        gaba_trades=gaba_trades,
        expected_size=expected_size,
        up_grid=up_grid,
        down_grid=down_grid,
        up_fill_report=up_fill_report,
        down_fill_report=down_fill_report,
    )

    # Optionally save raw data
    if args.save:
        os.makedirs("data/analysis", exist_ok=True)
        ts_tag = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = f"data/analysis/book_analysis_{args.asset}_{args.timeframe}_{ts_tag}.json"
        result = {
            "asset": args.asset,
            "timeframe": args.timeframe,
            "mode": "ws" if args.ws else "rest",
            "market_slug": market.slug,
            "boundary_epoch": boundary,
            "up_peak": up_peak,
            "down_peak": down_peak,
            "up_bursts_summary": [
                {"offset": b["offset"], "bid_changes": b["bid_changes"],
                 "ask_changes": b["ask_changes"]}
                for b in up_bursts[:10]
            ],
            "down_bursts_summary": [
                {"offset": b["offset"], "bid_changes": b["bid_changes"],
                 "ask_changes": b["ask_changes"]}
                for b in down_bursts[:10]
            ],
            "bid_count_timeline": {
                "up": [
                    {"offset": round(s["timestamp"] - boundary, 1),
                     "bid_count": len(s["bids"])}
                    for s in up_snapshots
                ],
                "down": [
                    {"offset": round(s["timestamp"] - boundary, 1),
                     "bid_count": len(s["bids"])}
                    for s in down_snapshots
                ],
            },
        }
        if args.ws:
            result["up_raw_events"] = up_events
            result["down_raw_events"] = down_events
            result["up_book_snapshots"] = up_book_snaps
            result["down_book_snapshots"] = down_book_snaps
            result["up_bots"] = [
                {k: v for k, v in b.items() if k != "prices"}
                for b in (up_bots or [])
            ]
            result["down_bots"] = [
                {k: v for k, v in b.items() if k != "prices"}
                for b in (down_bots or [])
            ]
            result["gabagool_activity"] = gaba_trades or []
            result["up_grid"] = (
                {k: v for k, v in up_grid.items() if k != "per_level"}
                if up_grid else None
            )
            result["down_grid"] = (
                {k: v for k, v in down_grid.items() if k != "per_level"}
                if down_grid else None
            )
            result["up_fill_report"] = (
                {k: v for k, v in up_fill_report.items()
                 if k not in ("matched_trades", "unmatched_trades")}
                if up_fill_report else None
            )
            result["down_fill_report"] = (
                {k: v for k, v in down_fill_report.items()
                 if k not in ("matched_trades", "unmatched_trades")}
                if down_fill_report else None
            )
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        log.info("Saved results to %s", out_path)


if __name__ == "__main__":
    main()
