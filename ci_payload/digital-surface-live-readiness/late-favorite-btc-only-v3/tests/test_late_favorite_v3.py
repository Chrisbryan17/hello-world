from __future__ import annotations

import json
from decimal import Decimal

import pytest

from late_favorite_v3 import (
    FreezeViolation,
    FrozenPolicy,
    LedgerIntegrityError,
    LifecycleError,
    ProspectiveLifecycleLedger,
    evaluate_arrival,
    evaluate_signal,
    settle_fill,
)


def policy() -> FrozenPolicy:
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


def book(condition_id: str, token_id: str, asks: list[tuple[str, str]]) -> dict[str, object]:
    return {
        "market": condition_id,
        "asset_id": token_id,
        "timestamp": "1800000210000",
        "hash": f"book-{token_id}",
        "bids": [{"price": "0.10", "size": "10"}],
        "asks": [{"price": price, "size": size} for price, size in asks],
        "min_order_size": "1",
        "tick_size": "0.01",
        "neg_risk": False,
        "last_trade_price": "0.50",
    }


def test_market_must_open_strictly_after_freeze() -> None:
    with pytest.raises(FreezeViolation):
        evaluate_signal(
            policy(),
            condition_id="c1",
            market_open_epoch_seconds=1_800_000_000,
            up_token_id="up",
            down_token_id="down",
            up_book=book("c1", "up", [("0.90", "10")]),
            down_book=book("c1", "down", [("0.12", "10")]),
            observed_ts_ms=1_800_000_210_000,
        )


def test_signal_selects_higher_executable_ask_as_favorite() -> None:
    result = evaluate_signal(
        policy(),
        condition_id="c1",
        market_open_epoch_seconds=1_800_000_300,
        up_token_id="up",
        down_token_id="down",
        up_book=book("c1", "up", [("0.90", "10")]),
        down_book=book("c1", "down", [("0.12", "10")]),
        observed_ts_ms=1_800_000_510_000,
    )
    assert result["decision"] == "signal"
    assert result["selected_side"] == "Up"
    assert result["selected_token_id"] == "up"
    assert result["signal_ask"] == "0.90"
    assert result["signal"] is True
    assert len(result["up_book_sha256"]) == 64
    assert len(result["down_book_sha256"]) == 64


def test_tied_or_subthreshold_favorite_fails_closed() -> None:
    tied = evaluate_signal(
        policy(),
        condition_id="c1",
        market_open_epoch_seconds=1_800_000_300,
        up_token_id="up",
        down_token_id="down",
        up_book=book("c1", "up", [("0.50", "10")]),
        down_book=book("c1", "down", [("0.50", "10")]),
        observed_ts_ms=1_800_000_510_000,
    )
    assert tied["decision"] == "no_signal_tied_favorite"

    below = evaluate_signal(
        policy(),
        condition_id="c2",
        market_open_epoch_seconds=1_800_000_300,
        up_token_id="up2",
        down_token_id="down2",
        up_book=book("c2", "up2", [("0.84", "10")]),
        down_book=book("c2", "down2", [("0.18", "10")]),
        observed_ts_ms=1_800_000_510_000,
    )
    assert below["decision"] == "no_signal_below_threshold"


def test_arrival_cancels_toxic_improvement_and_rejects_price_above_limit() -> None:
    signal = evaluate_signal(
        policy(),
        condition_id="c1",
        market_open_epoch_seconds=1_800_000_300,
        up_token_id="up",
        down_token_id="down",
        up_book=book("c1", "up", [("0.90", "10")]),
        down_book=book("c1", "down", [("0.12", "10")]),
        observed_ts_ms=1_800_000_510_000,
    )
    toxic = evaluate_arrival(
        policy(), signal, book("c1", "up", [("0.88", "10")]), observed_ts_ms=1_800_000_511_000
    )
    assert toxic["decision"] == "cancel_adverse_move"

    above = evaluate_arrival(
        policy(), signal, book("c1", "up", [("0.91", "10")]), observed_ts_ms=1_800_000_511_000
    )
    assert above["decision"] == "no_fill_ask_above_limit"


def test_arrival_uses_full_depth_vwap_and_level_fees() -> None:
    signal = evaluate_signal(
        policy(),
        condition_id="c1",
        market_open_epoch_seconds=1_800_000_300,
        up_token_id="up",
        down_token_id="down",
        up_book=book("c1", "up", [("0.90", "10")]),
        down_book=book("c1", "down", [("0.12", "10")]),
        observed_ts_ms=1_800_000_510_000,
    )
    fill = evaluate_arrival(
        policy(),
        signal,
        book("c1", "up", [("0.89", "2"), ("0.90", "3"), ("0.91", "100")]),
        observed_ts_ms=1_800_000_511_000,
    )
    assert fill["decision"] == "hypothetical_fok_fill"
    assert fill["filled_shares"] == "5"
    assert fill["execution_vwap"] == "0.896"
    expected_fee = (
        Decimal("2") * Decimal("0.07") * Decimal("0.89") * Decimal("0.11")
        + Decimal("3") * Decimal("0.07") * Decimal("0.90") * Decimal("0.10")
    ) / Decimal("5")
    assert Decimal(fill["fee_per_share"]) == expected_fee
    assert fill["execution_levels"] == [
        {"price": "0.89", "size": "2"},
        {"price": "0.90", "size": "3"},
    ]


def test_arrival_requires_exact_latency_and_sufficient_depth() -> None:
    signal = evaluate_signal(
        policy(),
        condition_id="c1",
        market_open_epoch_seconds=1_800_000_300,
        up_token_id="up",
        down_token_id="down",
        up_book=book("c1", "up", [("0.90", "10")]),
        down_book=book("c1", "down", [("0.12", "10")]),
        observed_ts_ms=1_800_000_510_000,
    )
    with pytest.raises(LifecycleError):
        evaluate_arrival(
            policy(), signal, book("c1", "up", [("0.90", "10")]), observed_ts_ms=1_800_000_512_000
        )
    shallow = evaluate_arrival(
        policy(), signal, book("c1", "up", [("0.90", "4.99")]), observed_ts_ms=1_800_000_511_000
    )
    assert shallow["decision"] == "no_fill_insufficient_depth"


def test_official_settlement_uses_frozen_fill_economics() -> None:
    signal = evaluate_signal(
        policy(),
        condition_id="c1",
        market_open_epoch_seconds=1_800_000_300,
        up_token_id="up",
        down_token_id="down",
        up_book=book("c1", "up", [("0.90", "10")]),
        down_book=book("c1", "down", [("0.12", "10")]),
        observed_ts_ms=1_800_000_510_000,
    )
    fill = evaluate_arrival(
        policy(), signal, book("c1", "up", [("0.90", "5")]), observed_ts_ms=1_800_000_511_000
    )
    win = settle_fill(fill, official_outcome="Up", resolution_payload_sha256="3" * 64)
    loss = settle_fill(fill, official_outcome="Down", resolution_payload_sha256="4" * 64)
    assert Decimal(win["pnl_per_share"]) > 0
    assert Decimal(loss["pnl_per_share"]) < Decimal("-0.90")
    assert win["official_won"] is True
    assert loss["official_won"] is False


def test_lifecycle_ledger_is_append_only_and_enforces_order(tmp_path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = ProspectiveLifecycleLedger(path, policy())
    discovered = ledger.append(
        condition_id="c1",
        market_open_epoch_seconds=1_800_000_300,
        event_type="discovered",
        observed_ts_ms=1_800_000_301_000,
        payload={"slug": "btc-updown-5m-1800000300"},
    )
    assert discovered["previous_hash"] == "0" * 64
    with pytest.raises(LifecycleError):
        ledger.append(
            condition_id="c2",
            market_open_epoch_seconds=1_800_000_300,
            event_type="arrival",
            observed_ts_ms=1_800_000_511_000,
            payload={"decision": "no_fill"},
        )
    ledger.append(
        condition_id="c1",
        market_open_epoch_seconds=1_800_000_300,
        event_type="signal",
        observed_ts_ms=1_800_000_510_000,
        payload={"decision": "signal"},
    )
    with pytest.raises(LifecycleError):
        ledger.append(
            condition_id="c1",
            market_open_epoch_seconds=1_800_000_300,
            event_type="signal",
            observed_ts_ms=1_800_000_510_001,
            payload={"decision": "signal"},
        )
    reloaded = ProspectiveLifecycleLedger(path, policy())
    assert reloaded.head_hash == ledger.head_hash
    assert len(reloaded.records) == 2


def test_lifecycle_ledger_detects_tampering(tmp_path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = ProspectiveLifecycleLedger(path, policy())
    ledger.append(
        condition_id="c1",
        market_open_epoch_seconds=1_800_000_300,
        event_type="discovered",
        observed_ts_ms=1_800_000_301_000,
        payload={"slug": "btc-updown-5m-1800000300"},
    )
    row = json.loads(path.read_text())
    row["payload"]["slug"] = "tampered"
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(LedgerIntegrityError):
        ProspectiveLifecycleLedger(path, policy())
