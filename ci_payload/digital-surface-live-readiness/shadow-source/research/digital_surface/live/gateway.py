from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
from typing import Any

from .config import TradingConfig
from .risk import evaluate_pair_risk
from .types import BookQuote, PreparedOrder, PreparedPair, RiskState, TradeIntent


def quantize_down(value: Decimal, tick: Decimal) -> Decimal:
    if tick <= 0:
        raise ValueError("tick must be positive")
    units = (value / tick).to_integral_value(rounding=ROUND_DOWN)
    return units * tick


class ShadowGateway:
    """Prepare auditable FOK parameters without signing or sending a request."""

    def __init__(self, config: TradingConfig, transport: Any | None = None) -> None:
        if config.mode != "shadow":
            raise ValueError("ShadowGateway requires shadow mode")
        self.config = config
        self._transport = transport
        self.prepared: list[PreparedPair] = []

    def prepare_pair(
        self,
        *,
        intent: TradeIntent,
        low_book: BookQuote,
        high_book: BookQuote,
        state: RiskState,
        now_ms: int,
    ) -> PreparedPair:
        risk = evaluate_pair_risk(
            intent=intent,
            low_book=low_book,
            high_book=high_book,
            state=state,
            config=self.config,
            now_ms=now_ms,
        )
        if not risk.allowed:
            raise RuntimeError(f"risk rejected pair: {risk.reason}")
        low_price = quantize_down(min(low_book.best_ask, intent.max_low_price), self.config.tick_size)
        high_price = quantize_down(min(high_book.best_ask, intent.max_high_price), self.config.tick_size)
        pair = PreparedPair(
            mode="shadow",
            intent=intent,
            low_order=PreparedOrder(
                token_id=intent.token_id_low_yes,
                side="BUY",
                order_type="FOK",
                price=low_price,
                size=intent.shares,
            ),
            high_order=PreparedOrder(
                token_id=intent.token_id_high_no,
                side="BUY",
                order_type="FOK",
                price=high_price,
                size=intent.shares,
            ),
            risk=risk,
        )
        self.prepared.append(pair)
        # No method on the supplied transport is invoked. The object exists only
        # so the test can prove preparation has zero network side effects.
        return pair

    def submit_pair(self, pair: PreparedPair) -> None:
        raise RuntimeError("network submission is not implemented in this shadow-only checkpoint")
