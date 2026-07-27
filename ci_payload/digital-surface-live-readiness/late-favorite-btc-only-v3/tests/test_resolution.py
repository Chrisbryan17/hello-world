from __future__ import annotations

import json
from decimal import Decimal

import pytest

from capture_policy import CaptureBoundLifecycleLedger, CapturePolicy
from late_favorite_v3 import FrozenPolicy
from public_collector import PublicHttpClient, RawEvidenceStore, SingleMarketCollector
from resolution import SingleMarketResolver, parse_terminal_outcome


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.content = json.dumps(payload, separators=(",", ":")).encode()
        self.status_code = 200


class FakeRequester:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)

    def __call__(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        return self.responses.pop(0)


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


def terminal_payload(opening: int, *, winner: str = "Up") -> dict[str, object]:
    prices = ["1", "0"] if winner == "Up" else ["0", "1"]
    return {
        "conditionId": "condition-1",
        "slug": f"btc-updown-5m-{opening}",
        "closed": True,
        "outcomes": json.dumps(["Up", "Down"]),
        "outcomePrices": json.dumps(prices),
    }


def test_parse_terminal_outcome_requires_closed_binary_terminal_prices() -> None:
    opening = 1_800_000_300
    assert parse_terminal_outcome(terminal_payload(opening, winner="Down"), opening, "condition-1") == "Down"
    not_closed = terminal_payload(opening)
    not_closed["closed"] = False
    with pytest.raises(ValueError):
        parse_terminal_outcome(not_closed, opening, "condition-1")
    ambiguous = terminal_payload(opening)
    ambiguous["outcomePrices"] = json.dumps(["0.5", "0.5"])
    with pytest.raises(ValueError):
        parse_terminal_outcome(ambiguous, opening, "condition-1")


def test_resolver_appends_official_fill_settlement(tmp_path) -> None:
    opening = 1_800_000_300
    signal_target = opening * 1000 + 210_000
    arrival_target = opening * 1000 + 211_000
    market = {
        "conditionId": "condition-1", "slug": f"btc-updown-5m-{opening}",
        "active": True, "closed": False, "enableOrderBook": True,
        "outcomes": json.dumps(["Up", "Down"]),
        "clobTokenIds": json.dumps(["token-up", "token-down"]),
    }
    def book(token: str, ask: str, timestamp: int) -> dict[str, object]:
        return {
            "market": "condition-1", "asset_id": token, "timestamp": str(timestamp),
            "hash": f"hash-{token}", "bids": [{"price": "0.10", "size": "10"}],
            "asks": [{"price": ask, "size": "10"}], "min_order_size": "1",
            "tick_size": "0.01", "neg_risk": False, "last_trade_price": "0.50",
        }
    responses = [
        FakeResponse(market),
        FakeResponse([book("token-up", "0.90", signal_target), book("token-down", "0.12", signal_target)]),
        FakeResponse([book("token-up", "0.90", arrival_target)]),
        FakeResponse(terminal_payload(opening, winner="Up")),
    ]
    times = iter([
        opening * 1000 + 1000, opening * 1000 + 1020,
        signal_target, signal_target + 100,
        arrival_target, arrival_target + 100,
        opening * 1000 + 301_000, opening * 1000 + 301_050,
    ])
    client = PublicHttpClient(requester=FakeRequester(responses), clock_ms=lambda: next(times))
    ledger = CaptureBoundLifecycleLedger(tmp_path / "ledger.jsonl", trading_policy(), capture_policy())
    store = RawEvidenceStore(tmp_path / "raw")
    collector = SingleMarketCollector(
        client=client, evidence_store=store, ledger=ledger,
        trading_policy=trading_policy(), capture_policy=capture_policy(),
        sleep_until_ms=lambda _: None,
    )
    assert collector.capture(opening)["decision"] == "hypothetical_fok_fill"
    resolver = SingleMarketResolver(
        client=client, evidence_store=store, ledger=ledger,
        trading_policy=trading_policy(), capture_policy=capture_policy(),
    )
    resolution = resolver.resolve("condition-1")
    assert resolution["official_outcome"] == "Up"
    assert resolution["official_won"] is True
    assert Decimal(resolution["pnl_total"]) > 0
    assert ledger.records[-1]["event_type"] == "resolution"
    assert len(store.records) == 4


def test_resolver_closes_no_signal_market_without_pnl(tmp_path) -> None:
    opening = 1_800_000_300
    ledger = CaptureBoundLifecycleLedger(tmp_path / "ledger.jsonl", trading_policy(), capture_policy())
    ledger.append(
        condition_id="condition-1", market_open_epoch_seconds=opening,
        event_type="discovered", observed_ts_ms=opening * 1000 + 1000,
        payload={"slug": f"btc-updown-5m-{opening}"},
    )
    ledger.append(
        condition_id="condition-1", market_open_epoch_seconds=opening,
        event_type="signal", observed_ts_ms=opening * 1000 + 210_000,
        payload={"decision": "no_signal_below_threshold", "signal": False},
    )
    times = iter([opening * 1000 + 301_000, opening * 1000 + 301_050])
    client = PublicHttpClient(
        requester=FakeRequester([FakeResponse(terminal_payload(opening, winner="Down"))]),
        clock_ms=lambda: next(times),
    )
    resolver = SingleMarketResolver(
        client=client, evidence_store=RawEvidenceStore(tmp_path / "raw"), ledger=ledger,
        trading_policy=trading_policy(), capture_policy=capture_policy(),
    )
    resolution = resolver.resolve("condition-1")
    assert resolution["decision"] == "resolved_no_fill"
    assert resolution["official_outcome"] == "Down"
    assert resolution["pnl_total"] is None
