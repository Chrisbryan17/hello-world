from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class TradeIntent:
    condition_id_low: str
    token_id_low_yes: str
    condition_id_high: str
    token_id_high_no: str
    max_low_price: Decimal
    max_high_price: Decimal
    shares: Decimal
    decision_ts_ms: int
    expires_ts_ms: int


@dataclass(frozen=True, slots=True)
class BookQuote:
    token_id: str
    best_ask: Decimal
    ask_size: Decimal
    observed_ts_ms: int


@dataclass(frozen=True, slots=True)
class RiskState:
    feed_heartbeat_ts_ms: int
    daily_pnl: Decimal = Decimal("0")
    unresolved_orders: int = 0
    orphan_exposure: Decimal = Decimal("0")
    ambiguous_pair_state: bool = False


@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class PreparedOrder:
    token_id: str
    side: str
    order_type: str
    price: Decimal
    size: Decimal


@dataclass(frozen=True, slots=True)
class PreparedPair:
    mode: str
    intent: TradeIntent
    low_order: PreparedOrder
    high_order: PreparedOrder
    risk: RiskDecision
