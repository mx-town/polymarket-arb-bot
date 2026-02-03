#!/usr/bin/env python3
"""
Test signal detection in isolation.

Simulates Binance trades to verify momentum-based direction signals work.
"""

import time
from datetime import datetime
from trading.config import LagArbConfig
from trading.data.price_tracker import PriceTracker, DirectionSignal, Direction
from trading.data.binance_ws import AggTrade


def on_signal(signal: DirectionSignal):
    """Callback when signal is emitted"""
    print(f"\n🚨 SIGNAL DETECTED!")
    print(f"   Symbol:     {signal.symbol}")
    print(f"   Direction:  {signal.direction.value}")
    print(f"   Momentum:   {signal.momentum*100:.4f}%")
    print(f"   Move:       {signal.move_from_open*100:.4f}%")
    print(f"   Confidence: {signal.confidence:.2f}")
    print(f"   Significant: {signal.is_significant}")


def simulate_price_move(tracker: PriceTracker, symbol: str, start_price: float, move_pct: float, steps: int = 20):
    """Simulate a price movement over time"""
    end_price = start_price * (1 + move_pct)
    price_step = (end_price - start_price) / steps

    print(f"\n📊 Simulating {symbol}: {start_price:.2f} → {end_price:.2f} ({move_pct*100:+.2f}%)")

    for i in range(steps):
        price = start_price + (price_step * (i + 1))
        trade = AggTrade(
            symbol=symbol,
            price=price,
            quantity=0.1,
            trade_time=int(datetime.now().timestamp() * 1000),
            is_buyer_maker=False,
        )
        tracker.on_trade(trade)
        time.sleep(0.1)  # 100ms between trades

        # Check current state
        signal = tracker.get_signal(symbol)
        if signal:
            mom = signal.momentum * 100
            move = signal.move_from_open * 100
            print(f"   Step {i+1:2d}: price={price:.2f} momentum={mom:+.4f}% move={move:+.4f}% dir={signal.direction.value}")


def main():
    print("=" * 60)
    print("Signal Detection Test")
    print("=" * 60)

    config = LagArbConfig(
        candle_interval="1h",
        spot_momentum_window_sec=10.0,
        spot_move_threshold_pct=0.002,  # 0.2% for candle confirmation
        momentum_trigger_threshold_pct=0.001,  # 0.1% momentum trigger
    )

    print(f"\nConfig:")
    print(f"  Momentum window:    {config.spot_momentum_window_sec}s")
    print(f"  Momentum threshold: {config.momentum_trigger_threshold_pct*100}%")
    print(f"  Move threshold:     {config.spot_move_threshold_pct*100}%")

    tracker = PriceTracker(config, on_signal=on_signal)
    tracker.initialize()

    # Get actual candle opens from tracker
    btc_open = tracker.get_candle_open("BTCUSDT")
    eth_open = tracker.get_candle_open("ETHUSDT")

    print(f"\nCurrent candle opens:")
    print(f"  BTC: ${btc_open:.2f}" if btc_open else "  BTC: N/A")
    print(f"  ETH: ${eth_open:.2f}" if eth_open else "  ETH: N/A")

    # Test 1: Small move (below threshold) - should NOT trigger
    print("\n" + "=" * 60)
    print("TEST 1: Small move (0.05%) - should NOT trigger signal")
    print("=" * 60)
    if btc_open:
        simulate_price_move(tracker, "BTCUSDT", btc_open, 0.0005, steps=10)

    time.sleep(2)  # Clear momentum window

    # Test 2: Larger move UP (above threshold) - SHOULD trigger
    print("\n" + "=" * 60)
    print("TEST 2: Larger move UP (0.2%) - SHOULD trigger signal")
    print("=" * 60)
    if btc_open:
        simulate_price_move(tracker, "BTCUSDT", btc_open, 0.002, steps=15)

    time.sleep(2)

    # Test 3: Move DOWN - SHOULD trigger
    print("\n" + "=" * 60)
    print("TEST 3: Move DOWN (-0.2%) - SHOULD trigger signal")
    print("=" * 60)
    if eth_open:
        simulate_price_move(tracker, "ETHUSDT", eth_open, -0.002, steps=15)

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
