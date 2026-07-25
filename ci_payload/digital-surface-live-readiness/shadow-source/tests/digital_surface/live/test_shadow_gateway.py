from decimal import Decimal

import pytest

from research.digital_surface.live import (
    BookQuote,
    LiveTradingDisabledError,
    RiskState,
    ShadowGateway,
    TradeIntent,
    load_config,
)


class ExplodingTransport:
    def __getattr__(self, name):
        raise AssertionError(f"shadow path attempted network transport method {name}")


def intent() -> TradeIntent:
    return TradeIntent(
        condition_id_low="low",
        token_id_low_yes="yes-low",
        condition_id_high="high",
        token_id_high_no="no-high",
        max_low_price=Decimal("0.51"),
        max_high_price=Decimal("0.51"),
        shares=Decimal("5"),
        decision_ts_ms=1_000,
        expires_ts_ms=10_000,
    )


def books(now=2_000):
    return (
        BookQuote("yes-low", Decimal("0.5039"), Decimal("10"), now),
        BookQuote("no-high", Decimal("0.4979"), Decimal("10"), now),
    )


def state(now=2_000):
    return RiskState(feed_heartbeat_ts_ms=now)


def test_defaults_to_shadow_and_live_is_physically_disabled_even_with_credentials():
    assert load_config({}).mode == "shadow"
    with pytest.raises(LiveTradingDisabledError):
        load_config({
            "TRADING_MODE": "live",
            "POLYMARKET_API_KEY": "present",
            "POLYMARKET_PRIVATE_KEY": "present",
            "LIVE_ARM_TOKEN": "present",
        })


def test_shadow_prepare_quantizes_exactly_and_never_calls_transport():
    config = load_config({"TICK_SIZE": "0.01"})
    gateway = ShadowGateway(config, transport=ExplodingTransport())
    low, high = books()
    pair = gateway.prepare_pair(intent=intent(), low_book=low, high_book=high, state=state(), now_ms=2_000)
    assert pair.mode == "shadow"
    assert pair.low_order.price == Decimal("0.50")
    assert pair.high_order.price == Decimal("0.49")
    assert pair.low_order.order_type == pair.high_order.order_type == "FOK"
    assert len(gateway.prepared) == 1


def test_stale_feed_books_and_unresolved_exposure_fail_closed():
    gateway = ShadowGateway(load_config({}))
    low, high = books(now=1_000)
    with pytest.raises(RuntimeError, match="stale_feed"):
        gateway.prepare_pair(intent=intent(), low_book=low, high_book=high, state=state(now=0), now_ms=6_000)
    low, high = books(now=0)
    with pytest.raises(RuntimeError, match="stale_low_book"):
        gateway.prepare_pair(intent=intent(), low_book=low, high_book=high, state=state(now=6_000), now_ms=6_000)
    low, high = books(now=2_000)
    with pytest.raises(RuntimeError, match="unresolved_prior_orders"):
        gateway.prepare_pair(
            intent=intent(), low_book=low, high_book=high,
            state=RiskState(feed_heartbeat_ts_ms=2_000, unresolved_orders=1), now_ms=2_000,
        )
    with pytest.raises(RuntimeError, match="orphan_exposure"):
        gateway.prepare_pair(
            intent=intent(), low_book=low, high_book=high,
            state=RiskState(feed_heartbeat_ts_ms=2_000, orphan_exposure=Decimal("0.01")), now_ms=2_000,
        )


def test_ambiguous_pair_state_blocks_and_submit_is_unavailable():
    gateway = ShadowGateway(load_config({}))
    low, high = books()
    with pytest.raises(RuntimeError, match="ambiguous_pair_state"):
        gateway.prepare_pair(
            intent=intent(), low_book=low, high_book=high,
            state=RiskState(feed_heartbeat_ts_ms=2_000, ambiguous_pair_state=True), now_ms=2_000,
        )
    pair = gateway.prepare_pair(intent=intent(), low_book=low, high_book=high, state=state(), now_ms=2_000)
    with pytest.raises(RuntimeError, match="not implemented"):
        gateway.submit_pair(pair)
