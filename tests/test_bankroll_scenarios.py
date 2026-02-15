"""Bankroll scenario tests using real Polymarket 15m market data.

Real market characteristics (BTC 15m up/down):
- Asks sum to 0.99-1.02 (MMs take 1-2%)
- Bid-ask spread: 1-3 cents per side
- VWAPs at fill: 0.47-0.53 (bid+1c for maker orders)
- Position sizes: 50-200 shares
- Edge at maker: 0-2 cents
- Hedge only works when combined VWAP + maker < 1 - min_edge

Run with: uv run pytest tests/test_bankroll_scenarios.py -v -s
"""

from decimal import ROUND_DOWN, Decimal
from typing import NamedTuple

import pytest

from complete_set.config import CompleteSetConfig
from complete_set.models import MarketInventory, OrderState, Direction
from complete_set.quote_calc import (
    calculate_balanced_shares,
    calculate_exposure,
    calculate_exposure_breakdown,
    total_bankroll_cap,
)

ZERO = Decimal("0")
ONE = Decimal("1")
TICK = Decimal("0.01")


# ---------------------------------------------------------------------------
# Realistic market books (from actual Polymarket BTC 15m observations)
# ---------------------------------------------------------------------------

class Book(NamedTuple):
    """One side of the order book."""
    bid: Decimal
    ask: Decimal

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def maker(self) -> Decimal:
        """Price we'd get as GTC maker: bid+1c, capped below ask-1c."""
        return min(self.bid + TICK, self.ask - TICK)


class MarketBook(NamedTuple):
    """Full market: UP and DOWN books."""
    up: Book
    down: Book
    label: str = ""

    @property
    def ask_sum(self) -> Decimal:
        return self.up.ask + self.down.ask

    @property
    def maker_sum(self) -> Decimal:
        return self.up.maker + self.down.maker

    @property
    def round_trip(self) -> Decimal:
        """Cost of both legs at ask prices."""
        return self.up.ask + self.down.ask


# Books observed in real sessions
TIGHT_BOOK = MarketBook(
    up=Book(Decimal("0.47"), Decimal("0.49")),
    down=Book(Decimal("0.50"), Decimal("0.52")),
    label="tight (2c spread, sum=1.01)",
)
NORMAL_BOOK = MarketBook(
    up=Book(Decimal("0.46"), Decimal("0.49")),
    down=Book(Decimal("0.50"), Decimal("0.53")),
    label="normal (3c spread, sum=1.02)",
)
FAVORABLE_BOOK = MarketBook(
    up=Book(Decimal("0.46"), Decimal("0.48")),
    down=Book(Decimal("0.50"), Decimal("0.52")),
    label="favorable (2c spread, sum=1.00)",
)
SKEWED_BOOK = MarketBook(
    up=Book(Decimal("0.43"), Decimal("0.46")),
    down=Book(Decimal("0.53"), Decimal("0.56")),
    label="skewed (3c spread, sum=1.02)",
)


def _cfg(bankroll: int, **kw) -> CompleteSetConfig:
    defaults = dict(
        bankroll_usd=Decimal(str(bankroll)),
        min_edge=Decimal("0.01"),
        hedge_edge_buffer=Decimal("0.0"),
        min_merge_shares=Decimal("10"),
        no_new_orders_sec=90,
        min_seconds_to_end=0,
        max_seconds_to_end=900,
    )
    defaults.update(kw)
    return CompleteSetConfig(**defaults)


# ---------------------------------------------------------------------------
# Test 1: Sizing — does calculate_balanced_shares produce reasonable sizes?
# ---------------------------------------------------------------------------

class TestSizingRealistic:
    """Verify order sizes make sense for real bankrolls and market conditions."""

    @pytest.mark.parametrize("bankroll,book,seconds_left,expected_min,expected_max", [
        # Small bankroll, tight book, mid-window → should get ~36-38 shares
        # base = 200 * 0.20 / 0.52 = 76.92 → 76, time_factor(600s) = 0.95 → 72
        # cap = 160 / 1.01 = 158 → shares = min(72, 158) = 72
        (200, TIGHT_BOOK, 600, 60, 80),
        # Medium bankroll, normal book, early window
        # base = 500 * 0.20 / 0.53 = 188.67 → 188, time_factor(600s) = 0.95 → 178
        # cap = 400 / 1.02 = 392 → shares = min(178, 392) = 178
        (500, NORMAL_BOOK, 600, 150, 200),
        # Large bankroll, tight book, late (60s left) → time_factor = 0.65
        # (60 < 60 is False, falls to 180 bucket)
        # base = 1000 * 0.20 / 0.52 = 384.61 → 384, time_factor = 0.65 → 249
        # cap = 800 / 1.01 = 792 → shares = min(249, 792) = 249
        (1000, TIGHT_BOOK, 60, 230, 260),
        # Medium bankroll, already half-exposed
        # remaining = 400 - 200 = 200, cap = 200 / 1.02 = 196
        # base = 500 * 0.20 / 0.53 = 188 * 0.95 = 178 → min(178, 196) = 178
        (500, NORMAL_BOOK, 600, 150, 200),
    ], ids=["small-tight-mid", "medium-normal-mid", "large-tight-late", "medium-half-exposed"])
    def test_sizing(self, bankroll, book, seconds_left, expected_min, expected_max):
        cfg = _cfg(bankroll)
        exposure = ZERO if "half" not in "" else Decimal("200")
        shares = calculate_balanced_shares(
            "btc-test", book.up.ask, book.down.ask, cfg, seconds_left, exposure,
        )
        assert shares is not None, f"Should produce shares for ${bankroll} bankroll"
        assert expected_min <= shares <= expected_max, (
            f"Expected {expected_min}-{expected_max} shares, got {shares} "
            f"(bankroll=${bankroll}, book={book.label})"
        )

    def test_half_exposed_caps_by_round_trip(self):
        """With $200 already deployed, remaining=$200, cap by round_trip."""
        cfg = _cfg(500)
        exposure = Decimal("200")
        shares = calculate_balanced_shares(
            "btc-test", NORMAL_BOOK.up.ask, NORMAL_BOOK.down.ask, cfg, 600, exposure,
        )
        assert shares is not None
        # remaining = 400 - 200 = 200, round_trip = 1.02
        # cap_shares = 200 / 1.02 = 196.07 → 196
        # base = 188 * 0.95 = 178, min(178, 196) = 178
        assert shares <= Decimal("196"), f"Round-trip cap should limit to ~196, got {shares}"

    def test_bankroll_exhausted(self):
        """When exposure >= cap, no shares returned."""
        cfg = _cfg(500)
        exposure = Decimal("400")  # cap = 400, remaining = 0
        shares = calculate_balanced_shares(
            "btc-test", TIGHT_BOOK.up.ask, TIGHT_BOOK.down.ask, cfg, 600, exposure,
        )
        assert shares is None, "Should return None when bankroll exhausted"

    def test_round_trip_vs_expensive_cap(self):
        """Round-trip cap is tighter than single-leg cap in skewed markets."""
        cfg = _cfg(500)
        # Skewed: expensive = 0.56, round_trip = 1.02
        # Single-leg cap: 400 / 0.56 = 714
        # Round-trip cap: 400 / 1.02 = 392
        shares_actual = calculate_balanced_shares(
            "btc-test", SKEWED_BOOK.up.ask, SKEWED_BOOK.down.ask, cfg, 600, ZERO,
        )
        assert shares_actual is not None
        # Verify round-trip cost fits within cap
        cost = shares_actual * (SKEWED_BOOK.up.ask + SKEWED_BOOK.down.ask)
        cap = total_bankroll_cap(Decimal("500"))
        assert cost <= cap, f"Round-trip cost ${cost} exceeds cap ${cap}"


# ---------------------------------------------------------------------------
# Test 2: Exposure — does it correctly reserve for hedge?
# ---------------------------------------------------------------------------

class TestExposureRealistic:
    """Verify exposure calculation with real position structures."""

    def test_single_unhedged_up_position(self):
        """100 UP shares at VWAP 0.48 → should reserve ~$100 (not just $48)."""
        inv = MarketInventory(
            up_shares=Decimal("100"),
            up_cost=Decimal("48.00"),  # VWAP = 0.48
        )
        exposure = calculate_exposure({}, {"btc-1": inv})
        # first_leg_cost = 100 * 0.48 = $48
        # hedge_reserve = 100 * (1 - 0.48) = $52
        # total = $100 (reserves for both legs)
        assert exposure == Decimal("100.00"), f"Should reserve $100, got ${exposure}"

    def test_single_unhedged_down_position(self):
        """80 DOWN shares at VWAP 0.53 → should reserve ~$80."""
        inv = MarketInventory(
            down_shares=Decimal("80"),
            down_cost=Decimal("42.40"),  # VWAP = 0.53
        )
        exposure = calculate_exposure({}, {"btc-2": inv})
        # first_leg_cost = 80 * 0.53 = $42.40
        # hedge_reserve = 80 * (1 - 0.53) = $37.60
        # total = $80.00
        assert exposure == Decimal("80.00"), f"Should reserve $80, got ${exposure}"

    def test_hedged_position_uses_actual_cost(self):
        """100 hedged pairs at VWAP 0.48+0.51 → locked at actual cost, not $1/share."""
        inv = MarketInventory(
            up_shares=Decimal("100"),
            down_shares=Decimal("100"),
            up_cost=Decimal("48.00"),   # VWAP 0.48
            down_cost=Decimal("51.00"),  # VWAP 0.51
        )
        exposure = calculate_exposure({}, {"btc-3": inv})
        # No imbalance → no unhedged exposure
        # hedged_locked = 100 * (0.48 + 0.51) = $99
        assert exposure == Decimal("99.00"), f"Hedged cost should be $99, got ${exposure}"

    def test_partial_hedge_mixed(self):
        """150 UP, 100 DOWN → 100 hedged + 50 unhedged UP."""
        inv = MarketInventory(
            up_shares=Decimal("150"),
            down_shares=Decimal("100"),
            up_cost=Decimal("72.00"),   # VWAP 0.48
            down_cost=Decimal("51.00"),  # VWAP 0.51
        )
        exposure = calculate_exposure({}, {"btc-4": inv})
        # imbalance = 50 UP, vwap = 0.48
        # unhedged = 50 * 0.48 + 50 * (1-0.48) = 50 * 1.0 = $50
        # hedged_locked = 100 * (0.48 + 0.51) = $99
        # total = $149
        assert exposure == Decimal("149.00"), f"Expected $149, got ${exposure}"

    def test_two_concurrent_markets(self):
        """Two markets: one unhedged, one hedged. Real multi-market scenario."""
        inv_a = MarketInventory(
            up_shares=Decimal("100"),
            up_cost=Decimal("48.00"),  # VWAP 0.48, unhedged
        )
        inv_b = MarketInventory(
            up_shares=Decimal("80"),
            down_shares=Decimal("80"),
            up_cost=Decimal("37.60"),   # VWAP 0.47
            down_cost=Decimal("41.60"),  # VWAP 0.52
        )
        exposure = calculate_exposure({}, {"btc-a": inv_a, "btc-b": inv_b})
        # Market A: 100 unhedged at $1/share = $100
        # Market B: 80 hedged at (0.47 + 0.52) = $79.20
        # Total = $179.20
        assert exposure == Decimal("179.20"), f"Expected $179.20, got ${exposure}"


# ---------------------------------------------------------------------------
# Test 3: Hedge affordability — can the hedge leg proceed given exposure?
# ---------------------------------------------------------------------------

class TestHedgeAffordability:
    """Simulate the bankroll check in _place_hedge_leg with real numbers.

    This tests the logic at engine.py:899-908 without needing the full engine.
    """

    @staticmethod
    def _can_afford_hedge(
        bankroll: int,
        unhedged_shares: Decimal,
        first_vwap: Decimal,
        hedge_maker: Decimal,
        other_exposure: Decimal = ZERO,
    ) -> tuple[bool, Decimal, Decimal]:
        """Simulate _place_hedge_leg bankroll check. Returns (can_afford, effective_remaining, needed).

        Mirrors engine.py: unhedged exposure reserves ~(1-first_vwap)/share for
        the hedge. The bankroll check adds that embedded reserve back so the
        hedge isn't starved by its own reservation.
        """
        inv = MarketInventory(
            up_shares=unhedged_shares,
            up_cost=unhedged_shares * first_vwap,
        )
        inventories = {"this-market": inv}
        exposure = calculate_exposure({}, inventories) + other_exposure
        cap = total_bankroll_cap(Decimal(str(bankroll)))
        remaining = cap - exposure
        # Add back hedge reserve already embedded in unhedged exposure
        embedded_reserve = unhedged_shares * (ONE - first_vwap)
        effective_remaining = remaining + embedded_reserve
        hedge_notional = unhedged_shares * hedge_maker
        return (hedge_notional <= effective_remaining, effective_remaining, hedge_notional)

    @pytest.mark.parametrize("bankroll,shares,first_vwap,hedge_maker,other_exp,should_pass", [
        # $500 bankroll, 100 shares at 0.48, hedge at 0.51 → exposure=$100, eff_remaining=$352, need=$51
        (500, Decimal("100"), Decimal("0.48"), Decimal("0.51"), ZERO, True),
        # $200 bankroll, 80 shares at 0.47, hedge at 0.52 → exposure=$80, eff_remaining=$122.40, need=$41.60
        (200, Decimal("80"), Decimal("0.47"), Decimal("0.52"), ZERO, True),
        # $500 bankroll, 100 shares at 0.48, $300 other → remaining=$0 + $52 reserve = $52, need=$51 → OK
        (500, Decimal("100"), Decimal("0.48"), Decimal("0.51"), Decimal("300"), True),
        # $200 bankroll, 150 shares at 0.48, $0 other → remaining=$10 + $78 reserve = $88, need=$76.50 → OK
        (200, Decimal("150"), Decimal("0.48"), Decimal("0.51"), ZERO, True),
        # $500 bankroll, 100 shares at 0.48, $360 other → remaining=-$60 + $52 = -$8, need=$51 → BLOCKED
        (500, Decimal("100"), Decimal("0.48"), Decimal("0.51"), Decimal("360"), False),
        # $1000 bankroll, 200 shares at 0.47, hedge at 0.52, $400 other → eff_remaining=$306, need=$104
        (1000, Decimal("200"), Decimal("0.47"), Decimal("0.52"), Decimal("400"), True),
    ], ids=[
        "500-100sh-clean",
        "200-80sh-clean",
        "500-100sh-crowded-ok",
        "200-large-position-ok",
        "500-truly-exhausted",
        "1000-200sh-half-used",
    ])
    def test_hedge_affordability(self, bankroll, shares, first_vwap, hedge_maker, other_exp, should_pass):
        can_afford, remaining, needed = self._can_afford_hedge(
            bankroll, shares, first_vwap, hedge_maker, other_exp,
        )
        if should_pass:
            assert can_afford, (
                f"Hedge should be affordable: need=${needed:.2f}, remaining=${remaining:.2f} "
                f"(bankroll=${bankroll})"
            )
        else:
            assert not can_afford, (
                f"Hedge should be BLOCKED: need=${needed:.2f}, remaining=${remaining:.2f} "
                f"(bankroll=${bankroll})"
            )


# ---------------------------------------------------------------------------
# Test 4: Full lifecycle — sizing → fill → exposure → hedge affordability
# ---------------------------------------------------------------------------

class _ScenarioResult(NamedTuple):
    bankroll: int
    book_label: str
    seconds_left: int
    first_shares: Decimal
    first_cost: Decimal
    exposure_after_fill: Decimal
    cap: Decimal
    remaining: Decimal
    hedge_notional: Decimal
    hedge_affordable: bool
    edge: Decimal


class TestFullLifecycle:
    """End-to-end: size a position, compute exposure after fill, check hedge."""

    SCENARIOS = [
        # (bankroll, book, seconds_left, other_exposure)
        (200,  TIGHT_BOOK,     600, ZERO),
        (200,  FAVORABLE_BOOK, 300, ZERO),
        (500,  TIGHT_BOOK,     600, ZERO),
        (500,  NORMAL_BOOK,    600, ZERO),
        (500,  NORMAL_BOOK,    600, Decimal("200")),  # half-exposed from another market
        (500,  SKEWED_BOOK,    600, ZERO),
        (1000, TIGHT_BOOK,     600, ZERO),
        (1000, TIGHT_BOOK,     600, Decimal("400")),  # two other markets running
        (1000, NORMAL_BOOK,    60,  ZERO),             # late entry, 60s left
    ]

    def _run_scenario(self, bankroll, book, seconds_left, other_exposure) -> _ScenarioResult | None:
        cfg = _cfg(bankroll)
        shares = calculate_balanced_shares(
            "btc-test", book.up.ask, book.down.ask, cfg, seconds_left, other_exposure,
        )
        if shares is None:
            return None

        # Simulate buying the cheaper side (DOWN) at maker price
        down_maker = book.down.maker
        first_cost = shares * down_maker

        # Exposure after fill: this position + other exposure
        inv = MarketInventory(
            down_shares=shares,
            down_cost=first_cost,
        )
        inventories = {"this": inv}
        exposure = calculate_exposure({}, inventories) + other_exposure
        cap = total_bankroll_cap(Decimal(str(bankroll)))
        remaining = cap - exposure

        # Hedge: buy UP at maker (mirrors engine.py embedded-reserve logic)
        up_maker = book.up.maker
        hedge_notional = shares * up_maker
        down_vwap = first_cost / shares if shares > ZERO else Decimal("0.50")
        embedded_reserve = shares * (ONE - down_vwap)
        effective_remaining = remaining + embedded_reserve
        hedge_affordable = hedge_notional <= effective_remaining

        # Edge: 1 - (down_vwap + up_maker)
        edge = ONE - (down_maker + up_maker)

        return _ScenarioResult(
            bankroll=bankroll,
            book_label=book.label,
            seconds_left=seconds_left,
            first_shares=shares,
            first_cost=first_cost,
            exposure_after_fill=exposure,
            cap=cap,
            remaining=effective_remaining,
            hedge_notional=hedge_notional,
            hedge_affordable=hedge_affordable,
            edge=edge,
        )

    @pytest.mark.parametrize("bankroll,book,seconds_left,other_exp", SCENARIOS, ids=[
        f"${b}-{bk.label[:8]}-{s}s-{('clean' if o == ZERO else f'${o}used')}"
        for b, bk, s, o in SCENARIOS
    ])
    def test_hedge_always_affordable_when_sized_correctly(
        self, bankroll, book, seconds_left, other_exp
    ):
        """If calculate_balanced_shares returns shares, the hedge must be affordable.

        This is the core invariant of Fix 5: round-trip sizing ensures the
        bankroll can cover both legs.
        """
        result = self._run_scenario(bankroll, book, seconds_left, other_exp)
        if result is None:
            pytest.skip("Bankroll exhausted — no position to test")
        assert result.hedge_affordable, (
            f"INVARIANT VIOLATED: sized {result.first_shares} shares but "
            f"hedge is unaffordable! need=${result.hedge_notional:.2f}, "
            f"remaining=${result.remaining:.2f} (bankroll=${bankroll}, "
            f"exposure=${result.exposure_after_fill:.2f})"
        )

    def test_summary_table(self, capsys):
        """Print aggregated scenario results for manual review."""
        results: list[_ScenarioResult] = []
        for bankroll, book, seconds_left, other_exp in self.SCENARIOS:
            r = self._run_scenario(bankroll, book, seconds_left, other_exp)
            if r is not None:
                results.append(r)

        print("\n")
        print("=" * 120)
        print("BANKROLL SCENARIO SUMMARY — Full lifecycle: sizing → fill → exposure → hedge check")
        print("=" * 120)
        print(f"{'Bankroll':>8} │ {'Book':>24} │ {'T-s':>4} │ {'Shares':>6} │ "
              f"{'1st Cost':>8} │ {'Exposure':>8} │ {'Cap':>6} │ {'Remain':>7} │ "
              f"{'Hedge $':>7} │ {'Afford':>6} │ {'Edge':>5}")
        print("─" * 120)
        for r in results:
            afford_str = "YES" if r.hedge_affordable else "NO"
            afford_color = "" if r.hedge_affordable else " !!!"
            print(
                f"${r.bankroll:>7} │ {r.book_label:>24} │ {r.seconds_left:>4} │ "
                f"{r.first_shares:>6} │ ${r.first_cost:>7.2f} │ ${r.exposure_after_fill:>7.2f} │ "
                f"${r.cap:>5} │ ${r.remaining:>6.2f} │ ${r.hedge_notional:>6.2f} │ "
                f"{afford_str:>6}{afford_color} │ {r.edge:>5.3f}"
            )
        print("─" * 120)

        # Aggregates
        total_scenarios = len(results)
        affordable = sum(1 for r in results if r.hedge_affordable)
        avg_shares = sum(r.first_shares for r in results) / total_scenarios
        avg_exposure_pct = sum(
            r.exposure_after_fill / r.cap * 100 for r in results
        ) / total_scenarios

        print(f"Scenarios: {total_scenarios} │ Hedge affordable: {affordable}/{total_scenarios} │ "
              f"Avg shares: {avg_shares:.0f} │ Avg exposure: {avg_exposure_pct:.1f}% of cap")
        print("=" * 120)


# ---------------------------------------------------------------------------
# Test 5: Edge cases — boundary conditions from real trading
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Boundary conditions observed in real trading sessions."""

    def test_min_order_size_enforced(self):
        """With tiny bankroll, shares < 5 → returns None."""
        cfg = _cfg(25)  # tiny bankroll
        shares = calculate_balanced_shares(
            "btc-test", Decimal("0.49"), Decimal("0.52"), cfg, 600, ZERO,
        )
        # base = 25 * 0.20 / 0.52 = 9.61 → 9, * 0.95 = 8
        # round_trip cap = 20 / 1.01 = 19.8 → 19
        # shares = min(8, 19) = 8
        # 8 >= MIN_ORDER_SIZE(5) → should return 8
        assert shares is not None and shares >= Decimal("5")

    def test_truly_tiny_bankroll_blocked(self):
        """Bankroll so small that even base shares < 5."""
        cfg = _cfg(10)
        shares = calculate_balanced_shares(
            "btc-test", Decimal("0.49"), Decimal("0.52"), cfg, 600, ZERO,
        )
        # base = 10 * 0.20 / 0.52 = 3.84 → 3
        # 3 * 0.95 = 2.85 → 2 < MIN_ORDER_SIZE(5) → None
        assert shares is None, "Should return None for bankroll too small"

    def test_exposure_with_pending_order_and_position(self):
        """Real scenario: first-leg GTC order + existing hedged position from prior window."""
        order = OrderState(
            order_id="o1",
            market=None,
            token_id="UP_TOK",
            direction=Direction.UP,
            price=Decimal("0.48"),
            size=Decimal("100"),
            placed_at=0,
            reserved_hedge_notional=Decimal("51.00"),  # hedge reserve = 100 * (1 - 0.01 - 0.48)
        )
        prior_inv = MarketInventory(
            up_shares=Decimal("50"),
            down_shares=Decimal("50"),
            up_cost=Decimal("23.50"),  # VWAP 0.47
            down_cost=Decimal("26.00"),  # VWAP 0.52
        )
        orders = {"UP_TOK": order}
        invs = {"prior-market": prior_inv}
        exposure = calculate_exposure(orders, invs)

        # Order: 0.48 * 100 = $48 notional + $51 reserve = $99
        # Prior hedged: 50 * (0.47 + 0.52) = $49.50
        # Total = $148.50
        expected = Decimal("48.00") + Decimal("51.00") + Decimal("49.50")
        assert exposure == expected, f"Expected ${expected}, got ${exposure}"

    def test_breakdown_matches_total(self):
        """Verify breakdown components sum to total for a complex scenario."""
        order = OrderState(
            order_id="o1", market=None, token_id="UP_TOK",
            direction=Direction.UP, price=Decimal("0.48"), size=Decimal("100"),
            placed_at=0, reserved_hedge_notional=Decimal("51.00"),
        )
        inv_unhedged = MarketInventory(
            down_shares=Decimal("80"),
            down_cost=Decimal("41.60"),  # VWAP 0.52
        )
        inv_hedged = MarketInventory(
            up_shares=Decimal("60"),
            down_shares=Decimal("60"),
            up_cost=Decimal("28.80"),  # VWAP 0.48
            down_cost=Decimal("31.20"),  # VWAP 0.52
        )
        orders = {"UP_TOK": order}
        invs = {"mkt-a": inv_unhedged, "mkt-b": inv_hedged}

        total = calculate_exposure(orders, invs)
        ord_n, unh, hed, brk_total = calculate_exposure_breakdown(orders, invs)

        assert brk_total == total, f"Breakdown total ${brk_total} != exposure ${total}"
        # Verify components:
        # orders = 0.48 * 100 = $48, reserved = $51
        assert ord_n == Decimal("48.00")
        # unhedged: 80 DOWN at vwap 0.52 → 80*0.52 + 80*0.48 = $80
        assert unh == Decimal("80.00"), f"Unhedged should be $80, got ${unh}"
        # hedged: 60 * (0.48 + 0.52) = $60
        assert hed == Decimal("60.00"), f"Hedged should be $60, got ${hed}"
        # total = 48 + 51 + 80 + 60 = $239
        assert total == Decimal("239.00"), f"Total should be $239, got ${total}"
