from __future__ import annotations

import json
from decimal import Decimal

import pytest

from capture_policy import CaptureBoundLifecycleLedger, CapturePolicy
from late_favorite_v3 import FrozenPolicy
from public_collector import (
    PublicEndpointViolation,
    PublicHttpClient,
    RawEvidenceStore,
    SingleMarketCollector,
    next_collectable_open,
    parse_btc_five_minute_market,
)


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.content = json.dumps(payload, separators=(",", ":")).encode()
        self.status_code = status_code


class FakeRequester:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def __call__(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
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


def market_payload(opening: int) -> dict[str, object]:
    return {
        "conditionId": "condition-1",
        "slug": f"btc-updown-5m-{opening}",
        "active": True,
        "closed": False,
        "enableOrderBook": True,
        "outcomes": json.dumps(["Up", "Down"]),
        "clobTokenIds": json.dumps(["token-up", "token-down"]),
    }


def book(condition: str, token: str, ask: str, timestamp_ms: int) -> dict[str, object]:
    return {
        "market": condition,
        "asset_id": token,
        "timestamp": str(timestamp_ms),
        "hash": f"hash-{token}-{timestamp_ms}",
        "bids": [{"price": "0.10", "size": "10"}],
        "asks": [{"price": ask, "size": "10"}],
        "min_order_size": "1",
        "tick_size": "0.01",
        "neg_risk": False,
        "last_trade_price": "0.50",
    }


def test_parse_market_maps_up_and_down_tokens() -> None:
    market = parse_btc_five_minute_market(market_payload(1_800_000_300), 1_800_000_300)
    assert market.condition_id == "condition-1"
    assert market.up_token_id == "token-up"
    assert market.down_token_id == "token-down"


def test_public_http_client_allows_only_read_only_public_endpoints() -> None:
    requester = FakeRequester([FakeResponse({"ok": True})])
    clock = iter([1000, 1025])
    client = PublicHttpClient(requester=requester, clock_ms=lambda: next(clock))
    evidence = client.request_json(
        "GET", "https://gamma-api.polymarket.com/markets/slug/test"
    )
    assert evidence.status_code == 200
    call = requester.calls[0]
    assert "Authorization" not in call["headers"]
    assert not any(str(key).startswith("POLY_") for key in call["headers"])
    with pytest.raises(PublicEndpointViolation):
        client.request_json("POST", "https://clob.polymarket.com/order", json_body={})


def test_raw_evidence_store_is_hash_chained_and_tamper_evident(tmp_path) -> None:
    requester = FakeRequester([FakeResponse({"value": 1})])
    clock = iter([1000, 1010])
    evidence = PublicHttpClient(requester=requester, clock_ms=lambda: next(clock)).request_json(
        "GET", "https://gamma-api.polymarket.com/markets/slug/test"
    )
    store = RawEvidenceStore(tmp_path)
    row = store.append(evidence, purpose="market_discovery")
    assert len(row["record_hash"]) == 64
    assert RawEvidenceStore(tmp_path).head_hash == row["record_hash"]
    body = tmp_path / row["body_path"]
    body.write_bytes(b"tampered")
    with pytest.raises(RuntimeError):
        RawEvidenceStore(tmp_path)


def test_next_collectable_open_uses_current_window_only_before_signal_target() -> None:
    opening = 1_800_000_300
    assert next_collectable_open(opening * 1000 + 209_000, 1_800_000_100) == opening
    assert next_collectable_open(opening * 1000 + 210_001, 1_800_000_100) == opening + 300


def test_single_market_collector_records_discovery_signal_and_arrival(tmp_path) -> None:
    opening = 1_800_000_300
    signal_target = opening * 1000 + 210_000
    arrival_target = opening * 1000 + 211_000
    responses = [
        FakeResponse(market_payload(opening)),
        FakeResponse([
            book("condition-1", "token-up", "0.90", signal_target + 10),
            book("condition-1", "token-down", "0.12", signal_target + 10),
        ]),
        FakeResponse([book("condition-1", "token-up", "0.90", arrival_target + 10)]),
    ]
    times = iter([
        opening * 1000 + 1_000, opening * 1000 + 1_020,
        signal_target + 20, signal_target + 100,
        arrival_target + 20, arrival_target + 100,
    ])
    requester = FakeRequester(responses)
    client = PublicHttpClient(requester=requester, clock_ms=lambda: next(times))
    ledger = CaptureBoundLifecycleLedger(
        tmp_path / "lifecycle.jsonl", trading_policy(), capture_policy()
    )
    store = RawEvidenceStore(tmp_path / "raw")
    slept: list[int] = []
    collector = SingleMarketCollector(
        client=client,
        evidence_store=store,
        ledger=ledger,
        trading_policy=trading_policy(),
        capture_policy=capture_policy(),
        sleep_until_ms=slept.append,
    )
    result = collector.capture(opening)
    assert result["decision"] == "hypothetical_fok_fill"
    assert [row["event_type"] for row in ledger.records] == ["discovered", "signal", "arrival"]
    assert slept == [signal_target, arrival_target]
    assert len(store.records) == 3
    assert requester.calls[1]["method"] == "POST"
    assert requester.calls[1]["url"] == "https://clob.polymarket.com/books"
    assert requester.calls[1]["json"] == [
        {"token_id": "token-up"}, {"token_id": "token-down"}
    ]
