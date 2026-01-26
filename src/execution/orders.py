"""
Order execution via CLOB API.
"""

from typing import Optional
from dataclasses import dataclass
from enum import Enum

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, BookParams
from py_clob_client.order_builder.constants import BUY, SELL

from src.config import CLOB_HOST, CHAIN_ID, TradingConfig
from src.strategy.signals import ArbOpportunity
from src.utils.logging import get_logger

logger = get_logger("orders")


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class OrderResult:
    """Result of an order attempt"""

    success: bool
    order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_size: float = 0.0
    filled_price: float = 0.0
    error: Optional[str] = None


class OrderExecutor:
    """Handles order execution via CLOB API"""

    def __init__(
        self,
        config: TradingConfig,
        private_key: Optional[str] = None,
        funder_address: Optional[str] = None,
    ):
        self.config = config
        self.client: Optional[ClobClient] = None

        if not config.dry_run:
            if not private_key or not funder_address:
                raise ValueError(
                    "POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER_ADDRESS required for live trading"
                )

            self.client = ClobClient(
                CLOB_HOST,
                key=private_key,
                chain_id=CHAIN_ID,
                signature_type=1,
                funder=funder_address,
            )
            self.client.set_api_creds(self.client.create_or_derive_api_creds())
            logger.info("INIT", "Authenticated CLOB client ready")
        else:
            self.client = ClobClient(CLOB_HOST)
            logger.info("INIT", "Read-only CLOB client (DRY RUN)")

    def get_order_book(self, token_id: str) -> Optional[dict]:
        """Fetch order book for a token"""
        try:
            book = self.client.get_order_book(token_id)
            return {
                "bids": getattr(book, "bids", []),
                "asks": getattr(book, "asks", []),
            }
        except Exception as e:
            logger.error("BOOK_ERROR", f"token={token_id} error={e}")
            return None

    def get_order_books_batch(self, token_ids: list[str]) -> dict[str, dict]:
        """Fetch order books for multiple tokens"""
        params = [BookParams(token_id=tid) for tid in token_ids]
        book_map = {}

        try:
            books = self.client.get_order_books(params)
            for book in books:
                asset_id = getattr(book, "asset_id", None)
                if asset_id:
                    book_map[asset_id] = {
                        "bids": getattr(book, "bids", []),
                        "asks": getattr(book, "asks", []),
                    }
        except Exception as e:
            logger.error("BATCH_BOOK_ERROR", f"error={e}")

        return book_map

    def place_order(
        self,
        token_id: str,
        side: OrderSide,
        price: float,
        size: float,
    ) -> OrderResult:
        """Place a single order"""
        if self.config.dry_run:
            logger.info(
                "DRY_ORDER",
                f"token={token_id[:16]}... side={side.value} price={price:.4f} size={size:.2f}",
            )
            return OrderResult(
                success=True,
                status=OrderStatus.FILLED,
                filled_size=size,
                filled_price=price,
            )

        try:
            order_side = BUY if side == OrderSide.BUY else SELL
            order = self.client.create_order(
                OrderArgs(
                    token_id=token_id,
                    price=price,
                    size=size,
                    side=order_side,
                )
            )
            response = self.client.post_order(order)

            logger.info(
                "ORDER_PLACED",
                f"token={token_id[:16]}... side={side.value} price={price:.4f} size={size:.2f}",
            )

            return OrderResult(
                success=True,
                order_id=getattr(response, "order_id", None),
                status=OrderStatus.PENDING,
                filled_size=size,
                filled_price=price,
            )

        except Exception as e:
            logger.error("ORDER_ERROR", f"token={token_id[:16]}... error={e}")
            return OrderResult(success=False, error=str(e), status=OrderStatus.FAILED)

    def execute_arb_entry(self, opp: ArbOpportunity, position_size: float) -> tuple[OrderResult, OrderResult]:
        """
        Execute arbitrage entry: buy both UP and DOWN.

        Args:
            opp: ArbOpportunity with prices
            position_size: Total USDC to spend

        Returns:
            Tuple of (up_result, down_result)
        """
        shares = position_size / opp.total_cost

        logger.info(
            "ARB_ENTRY",
            f"market={opp.slug} shares={shares:.2f} "
            f"up={opp.up_price:.4f} down={opp.down_price:.4f}",
        )

        up_result = self.place_order(
            opp.up_token_id,
            OrderSide.BUY,
            opp.up_price,
            shares,
        )

        down_result = self.place_order(
            opp.down_token_id,
            OrderSide.BUY,
            opp.down_price,
            shares,
        )

        return up_result, down_result

    def execute_arb_exit(
        self,
        up_token_id: str,
        down_token_id: str,
        up_bid: float,
        down_bid: float,
        shares: float,
    ) -> tuple[OrderResult, OrderResult]:
        """
        Execute arbitrage exit: sell both sides.

        Args:
            up_token_id: UP token ID
            down_token_id: DOWN token ID
            up_bid: Current best bid for UP
            down_bid: Current best bid for DOWN
            shares: Number of shares to sell

        Returns:
            Tuple of (up_result, down_result)
        """
        logger.info(
            "ARB_EXIT",
            f"shares={shares:.2f} up_bid={up_bid:.4f} down_bid={down_bid:.4f}",
        )

        up_result = self.place_order(
            up_token_id,
            OrderSide.SELL,
            up_bid,
            shares,
        )

        down_result = self.place_order(
            down_token_id,
            OrderSide.SELL,
            down_bid,
            shares,
        )

        return up_result, down_result
