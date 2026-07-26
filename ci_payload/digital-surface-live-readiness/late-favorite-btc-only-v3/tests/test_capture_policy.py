from __future__ import annotations

from decimal import Decimal

import pytest

from capture_policy import (
    CaptureBoundLifecycleLedger,
    CapturePolicy,
    CaptureWindowError,
    evaluate_arrival_capture,
    evaluate_signal_capture,
)
from late_favorite_v3 import FrozenPolicy


def trading_policy() -> FrozenPolicy:
    return FrozenPolicy(
        policy_sha256="1" * 64,
        source_sha256="2" * 64,
        valid_market_open_after_epoch_seconds=1_800_000_000,
        signal_ask_min=Decimal("0.85"),
        entry_second=210,
        latency_seconds=1,
        shares=Decimal("5"),
        adverse_move_cancel=Decimal("0.01"),
        fee_rate=Decimal("0.07"),
    )


def capture_policy() -> CapturePolicy:
    return CapturePolicy(
        capture_policy_sha256="3" * 64,
        valid_market_open_after_epoch_seconds=1_800_000_100,
        signal_target_offset_ms=210_000,
        arrival_target_offset_ms=211_000,
        max_request_start_lateness_ms=250,
        max_request_duration_ms=1_000,
        max_book_age_at_request_completion_ms=2_000,
        max_book_future_skew_ms=1_000,
    )


def book(condition_id: str, token_id: str, ask: str, *, timestamp_ms: int) -> dict[str, object]:
    return {
        "market": condition_id,
        "asset_id": token_id,
        "timestamp": str(timestamp_ms),
        "hash": f"book-{token_id}-{timestamp_ms}",
        "bids": [{"price": "0.10", "size": "10"}],
        "asks": [{"price": ask, "size": "10"}],
        "min_order_size": "1",
        "tick_size": "0.01",
        "neg_risk": False,
        "last_trade_price": "0.50",
    }


def test_signal_capture_rejects_pre_target_request() -> None:
    opening = 1_800_000_300
    target = opening * 1000 + 210_000
    with pytest.raises(CaptureWindowError):
        evaluate_signal_capture(
            trading_policy(), capture_policy(), condition_id="c1",
            market_open_epoch_seconds=opening, up_token_id="up", down_token_id="down",
            up_book=book("c1", "up", "0.90", timestamp_ms=target),
            down_book=book("c1", "down", "0.12", timestamp_ms=target),
            request_started_ts_ms=target - 1, request_completed_ts_ms=target + 20,
            response_payload_sha256="4" * 64,
        )


def test_signal_capture_records_late_and_stale_fail_closed() -> None:
    opening = 1_800_000_300
    target = opening * 1000 + 210_000
    late = evaluate_signal_capture(
        trading_policy(), capture_policy(), condition_id="c1",
        market_open_epoch_seconds=opening, up_token_id="up", down_token_id="down",
        up_book=book("c1", "up", "0.90", timestamp_ms=target),
        down_book=book("c1", "down", "0.12", timestamp_ms=target),
        request_started_ts_ms=target + 251, request_completed_ts_ms=target + 300,
        response_payload_sha256="4" * 64,
    )
    assert late["decision"] == "missed_signal_window"
    assert late["signal"] is False
    stale = evaluate_signal_capture(
        trading_policy(), capture_policy(), condition_id="c1",
        market_open_epoch_seconds=opening, up_token_id="up", down_token_id="down",
        up_book=book("c1", "up", "0.90", timestamp_ms=target - 2_001),
        down_book=book("c1", "down", "0.12", timestamp_ms=target),
        request_started_ts_ms=target, request_completed_ts_ms=target + 100,
        response_payload_sha256="4" * 64,
    )
    assert stale["decision"] == "no_signal_stale_book"
    assert stale["signal"] is False


def test_valid_signal_capture_preserves_target_and_transport_evidence() -> None:
    opening = 1_800_000_300
    target = opening * 1000 + 210_000
    result = evaluate_signal_capture(
        trading_policy(), capture_policy(), condition_id="c1",
        market_open_epoch_seconds=opening, up_token_id="up", down_token_id="down",
        up_book=book("c1", "up", "0.90", timestamp_ms=target + 10),
        down_book=book("c1", "down", "0.12", timestamp_ms=target + 10),
        request_started_ts_ms=target + 25, request_completed_ts_ms=target + 100,
        response_payload_sha256="4" * 64,
    )
    assert result["decision"] == "signal"
    assert result["observed_ts_ms"] == target
    assert result["target_ts_ms"] == target
    assert result["request_started_ts_ms"] == target + 25
    assert result["request_completed_ts_ms"] == target + 100
    assert result["capture_policy_sha256"] == "3" * 64
    assert result["response_payload_sha256"] == "4" * 64


def test_arrival_target_is_market_open_plus_211_seconds() -> None:
    opening = 1_800_000_300
    signal_target = opening * 1000 + 210_000
    arrival_target = opening * 1000 + 211_000
    signal = evaluate_signal_capture(
        trading_policy(), capture_policy(), condition_id="c1",
        market_open_epoch_seconds=opening, up_token_id="up", down_token_id="down",
        up_book=book("c1", "up", "0.90", timestamp_ms=signal_target),
        down_book=book("c1", "down", "0.12", timestamp_ms=signal_target),
        request_started_ts_ms=signal_target + 200, request_completed_ts_ms=signal_target + 900,
        response_payload_sha256="4" * 64,
    )
    arrival = evaluate_arrival_capture(
        trading_policy(), capture_policy(), signal,
        book("c1", "up", "0.90", timestamp_ms=arrival_target),
        request_started_ts_ms=arrival_target, request_completed_ts_ms=arrival_target + 100,
        response_payload_sha256="5" * 64,
    )
    assert arrival["decision"] == "hypothetical_fok_fill"
    assert arrival["target_ts_ms"] == arrival_target
    assert arrival["observed_ts_ms"] == arrival_target


def test_lifecycle_record_binds_capture_policy_hash(tmp_path) -> None:
    ledger = CaptureBoundLifecycleLedger(
        tmp_path / "ledger.jsonl", trading_policy(), capture_policy()
    )
    row = ledger.append(
        condition_id="c1", market_open_epoch_seconds=1_800_000_300,
        event_type="discovered", observed_ts_ms=1_800_000_301_000,
        payload={"slug": "btc-updown-5m-1800000300"},
    )
    assert row["capture_policy_sha256"] == "3" * 64
    reloaded = CaptureBoundLifecycleLedger(
        tmp_path / "ledger.jsonl", trading_policy(), capture_policy()
    )
    assert reloaded.head_hash == ledger.head_hash
