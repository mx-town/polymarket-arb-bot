"""Late-entry strategy for 15m Up/Down markets.

Buy the favorite side in the last 4 minutes before resolution.
Uses Gamma outcome prices as the signal (probability that side wins).
"""

import logging
import math
from datetime import UTC, datetime

log = logging.getLogger("strategy")


def should_enter(market: dict, prices: dict, config: dict) -> dict | None:
    """
    Check if we should enter a late-entry position.

    Uses Gamma outcome prices (0-1 probability) to determine favorite.
    Returns signal dict {side, token_id, price, size} or None.
    """
    now = datetime.now(UTC)
    end_date = market["end_date"]
    secs_left = (end_date - now).total_seconds()

    entry_window = config["entry_window_sec"]
    exit_buffer = config["exit_buffer_sec"]

    slug = market["slug"]
    mins, secs = divmod(int(secs_left), 60)
    time_str = f"{mins}m{secs:02d}s"

    # Must be in the entry window (last N minutes) but not too close to end
    if secs_left > entry_window:
        log.debug(f"  SKIP {slug[:40]} │ too early ({time_str} left, window={entry_window}s)")
        return None
    if secs_left < exit_buffer:
        log.debug(f"  SKIP {slug[:40]} │ too late ({time_str} left, buffer={exit_buffer}s)")
        return None

    up_price = prices["up_price"]
    down_price = prices["down_price"]

    # Determine favorite by Gamma outcome price (probability)
    if up_price > down_price:
        fav_side, fav_token, fav_price = "up", market["up_token"], up_price
    else:
        fav_side, fav_token, fav_price = "down", market["down_token"], down_price

    # Favorite must lead by min spread
    spread = abs(up_price - down_price)
    if spread < config["min_favorite_spread"]:
        log.info(
            f"  SKIP {slug[:40]} │ spread too low "
            f"({spread:.2%} < {config['min_favorite_spread']:.0%})"
        )
        return None

    # Don't overpay
    if fav_price > config["max_favorite_price"]:
        log.info(f"  SKIP {slug[:40]} │ price too high ({fav_price:.4f} > {config['max_favorite_price']})")
        return None

    # Position sizing: how many shares can we buy
    max_size = config.get("max_position_size", 8)
    size = math.floor(max_size / fav_price)
    if size < 1:
        log.info(f"  SKIP {slug[:40]} │ size=0 (max_pos=${max_size} / price={fav_price:.4f})")
        return None

    log.info(
        f"  SIGNAL {slug[:40]} │ {fav_side.upper()} @ {fav_price:.4f} "
        f"spread={spread:.2%} size={size} {time_str} left"
    )

    return {
        "side": fav_side,
        "token_id": fav_token,
        "price": fav_price,
        "size": size,
        "market_slug": market["slug"],
    }


def should_exit(position: dict, prices: dict, config: dict) -> dict | None:
    """
    Check if we should exit an existing position.

    Uses Gamma outcome price for the position's side as current value.
    Returns signal dict {token_id, price, size, reason} or None.
    """
    now = datetime.now(UTC)
    end_date = position["end_date"]
    secs_left = (end_date - now).total_seconds()

    side = position["side"]
    token_id = position["token_id"]
    entry_price = position["entry_price"]
    size = position["size"]

    # Current Gamma price for our side
    current_price = prices["up_price"] if side == "up" else prices["down_price"]

    # Take profit
    profit_pct = (current_price - entry_price) / entry_price
    if profit_pct >= config["take_profit_pct"]:
        log.info(f"  EXIT_TAKE_PROFIT {position['market_slug']} profit={profit_pct:.2%}")
        return {"token_id": token_id, "price": current_price, "size": size, "reason": "take_profit"}

    # Exit before resolution buffer
    if secs_left <= config["exit_buffer_sec"]:
        log.info(f"  EXIT_BUFFER {position['market_slug']} secs_left={secs_left:.0f}")
        return {"token_id": token_id, "price": current_price, "size": size, "reason": "buffer_exit"}

    return None
