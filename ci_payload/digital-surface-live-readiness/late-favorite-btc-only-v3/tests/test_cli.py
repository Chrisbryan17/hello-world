from __future__ import annotations

import json
from pathlib import Path

from cli import capture_once, resolve_once
from public_collector import PublicHttpClient


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.content = json.dumps(payload, separators=(",", ":")).encode()
        self.status_code = 200


class FakeRequester:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def __call__(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


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


def terminal_payload(opening: int) -> dict[str, object]:
    return {
        "conditionId": "condition-1",
        "slug": f"btc-updown-5m-{opening}",
        "closed": True,
        "outcomes": json.dumps(["Up", "Down"]),
        "outcomePrices": json.dumps(["1", "0"]),
    }


def book(token: str, ask: str, timestamp_ms: int) -> dict[str, object]:
    return {
        "market": "condition-1",
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


def test_capture_and_resolve_persist_complete_lifecycle(tmp_path: Path) -> None:
    opening = 1_800_000_300
    signal_target = opening * 1000 + 210_000
    arrival_target = opening * 1000 + 211_000
    requester = FakeRequester([
        FakeResponse(market_payload(opening)),
        FakeResponse([
            book("token-up", "0.90", signal_target),
            book("token-down", "0.12", signal_target),
        ]),
        FakeResponse([book("token-up", "0.90", arrival_target)]),
        FakeResponse(terminal_payload(opening)),
    ])
    times = iter([
        opening * 1000 + 1_000, opening * 1000 + 1_020,
        signal_target, signal_target + 100,
        arrival_target, arrival_target + 100,
        opening * 1000 + 301_000, opening * 1000 + 301_050,
    ])
    client = PublicHttpClient(requester=requester, clock_ms=lambda: next(times))
    slept: list[int] = []
    root = Path(__file__).parents[1]

    capture = capture_once(
        root=root,
        output_dir=tmp_path,
        market_open_epoch_seconds=opening,
        client=client,
        sleep_until_ms=slept.append,
    )
    assert capture["decision"] == "hypothetical_fok_fill"
    assert capture["condition_id"] == "condition-1"
    assert slept == [signal_target, arrival_target]
    assert (tmp_path / "lifecycle.jsonl").is_file()
    assert (tmp_path / "raw" / "manifest.jsonl").is_file()
    assert json.loads((tmp_path / "last_capture.json").read_text())["decision"] == "hypothetical_fok_fill"

    resolution = resolve_once(
        root=root,
        output_dir=tmp_path,
        condition_id="condition-1",
        client=client,
    )
    assert resolution["decision"] == "resolved_fill"
    assert resolution["official_outcome"] == "Up"
    assert resolution["official_won"] is True
    assert json.loads((tmp_path / "last_resolution.json").read_text())["decision"] == "resolved_fill"
    rows = [json.loads(line) for line in (tmp_path / "lifecycle.jsonl").read_text().splitlines()]
    assert [row["event_type"] for row in rows] == ["discovered", "signal", "arrival", "resolution"]


def test_capture_selects_next_eligible_window_when_opening_is_omitted(tmp_path: Path) -> None:
    now_ms = 1_800_000_300_000 + 210_001
    opening = 1_800_000_600
    signal_target = opening * 1000 + 210_000
    requester = FakeRequester([
        FakeResponse(market_payload(opening)),
        FakeResponse([
            book("token-up", "0.84", signal_target),
            book("token-down", "0.18", signal_target),
        ]),
    ])
    times = iter([
        opening * 1000 + 1_000, opening * 1000 + 1_020,
        signal_target, signal_target + 100,
    ])
    client = PublicHttpClient(requester=requester, clock_ms=lambda: next(times))
    root = Path(__file__).parents[1]
    result = capture_once(
        root=root,
        output_dir=tmp_path,
        market_open_epoch_seconds=None,
        now_ms=lambda: now_ms,
        client=client,
        sleep_until_ms=lambda _: None,
    )
    assert result["market_open_epoch_seconds"] == opening
    assert result["decision"] == "no_signal_below_threshold"
