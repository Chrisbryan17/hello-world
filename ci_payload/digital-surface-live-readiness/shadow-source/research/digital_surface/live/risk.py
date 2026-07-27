from __future__ import annotations

from decimal import Decimal

from .config import TradingConfig
from .types import BookQuote, RiskDecision, RiskState, TradeIntent


def evaluate_pair_risk(
    *,
    intent: TradeIntent,
    low_book: BookQuote,
    high_book: BookQuote,
    state: RiskState,
    config: TradingConfig,
    now_ms: int,
) -> RiskDecision:
    if now_ms >= intent.expires_ts_ms:
        return RiskDecision(False, "intent_expired")
    if state.ambiguous_pair_state:
        return RiskDecision(False, "ambiguous_pair_state")
    if state.unresolved_orders:
        return RiskDecision(False, "unresolved_prior_orders")
    if state.orphan_exposure > config.max_orphan_exposure:
        return RiskDecision(False, "orphan_exposure")
    if state.daily_pnl <= -abs(config.max_daily_loss):
        return RiskDecision(False, "daily_loss_limit")
    if now_ms - state.feed_heartbeat_ts_ms > config.max_feed_age_ms:
        return RiskDecision(False, "stale_feed")
    if now_ms - low_book.observed_ts_ms > config.max_book_age_ms:
        return RiskDecision(False, "stale_low_book")
    if now_ms - high_book.observed_ts_ms > config.max_book_age_ms:
        return RiskDecision(False, "stale_high_book")
    if low_book.token_id != intent.token_id_low_yes:
        return RiskDecision(False, "low_token_mismatch")
    if high_book.token_id != intent.token_id_high_no:
        return RiskDecision(False, "high_token_mismatch")
    if low_book.best_ask > intent.max_low_price:
        return RiskDecision(False, "low_ask_above_limit")
    if high_book.best_ask > intent.max_high_price:
        return RiskDecision(False, "high_ask_above_limit")
    if low_book.ask_size < intent.shares:
        return RiskDecision(False, "low_depth_insufficient")
    if high_book.ask_size < intent.shares:
        return RiskDecision(False, "high_depth_insufficient")
    if intent.shares <= Decimal("0"):
        return RiskDecision(False, "invalid_size")
    return RiskDecision(True, "allowed")
