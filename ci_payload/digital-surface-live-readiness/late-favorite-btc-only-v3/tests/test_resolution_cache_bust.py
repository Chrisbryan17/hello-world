from __future__ import annotations

from types import SimpleNamespace

from resolution import SingleMarketResolver


class FakeClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def request_json(self, method: str, url: str):
        self.urls.append(url)
        return SimpleNamespace(
            payload={
                "conditionId": "c1",
                "slug": "btc-updown-5m-1800000300",
                "closed": True,
                "outcomes": '["Up", "Down"]',
                "outcomePrices": '["1", "0"]',
            },
            response_body_sha256="4" * 64,
            request_completed_ts_ms=1_800_000_600_000,
        )


class FakeEvidenceStore:
    def __init__(self) -> None:
        self.records = [object()] * 7

    def append(self, evidence, *, purpose: str):
        return {"record_hash": "5" * 64}


class FakeLedger:
    def __init__(self) -> None:
        self.records = [
            {
                "condition_id": "c1",
                "market_open_epoch_seconds": 1_800_000_300,
                "event_type": "discovered",
                "payload": {"slug": "btc-updown-5m-1800000300"},
            },
            {
                "condition_id": "c1",
                "market_open_epoch_seconds": 1_800_000_300,
                "event_type": "signal",
                "payload": {"decision": "no_signal_below_threshold", "signal": False},
            },
        ]
        self.appended: list[dict[str, object]] = []

    def append(self, **kwargs) -> None:
        self.appended.append(kwargs)


def test_resolution_request_cache_busts_gamma_slug_url() -> None:
    client = FakeClient()
    resolver = SingleMarketResolver(
        client=client,
        evidence_store=FakeEvidenceStore(),
        ledger=FakeLedger(),
        trading_policy=SimpleNamespace(policy_sha256="1" * 64, source_sha256="2" * 64),
        capture_policy=SimpleNamespace(capture_policy_sha256="3" * 64),
    )

    resolver.resolve("c1")

    assert client.urls == [
        "https://gamma-api.polymarket.com/markets/slug/"
        "btc-updown-5m-1800000300?cache_bust=7"
    ]
