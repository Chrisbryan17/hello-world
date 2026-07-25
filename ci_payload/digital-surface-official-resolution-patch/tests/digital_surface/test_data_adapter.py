from pathlib import Path
import hashlib
import json

import pytest

from research.digital_surface.data import download_verified


def test_download_verified_rejects_hash_mismatch(tmp_path, monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_content(self, size): yield b"bad"
    monkeypatch.setattr("research.digital_surface.data.requests.get", lambda *a, **k: Response())
    spec = {"repo": "x", "source_revision": "r", "resolution_source": "o", "files": {"slots": {"url": "https://example.invalid", "sha256": "0" * 64}}}
    with pytest.raises(RuntimeError, match="hash mismatch"):
        download_verified(spec, tmp_path)


def test_download_verified_writes_manifest(tmp_path, monkeypatch):
    payload = b"good"
    digest = hashlib.sha256(payload).hexdigest()
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_content(self, size): yield payload
    monkeypatch.setattr("research.digital_surface.data.requests.get", lambda *a, **k: Response())
    spec = {"repo": "x", "source_revision": "r", "resolution_source": "o", "files": {"slots": {"url": "https://example.invalid", "sha256": digest}}}
    paths = download_verified(spec, tmp_path)
    assert paths["slots"].read_bytes() == payload
    manifest = json.loads((tmp_path / "SOURCE_MANIFEST.json").read_text())
    assert manifest["files"]["slots"]["sha256"] == digest

import pandas as pd

from research.digital_surface.data import (
    assign_hybrid_week_labels,
    git_blob_sha1_bytes,
    load_official_resolution_snapshot,
    normalize_obadiaha_source,
)


def test_git_blob_sha1_matches_git_object_definition():
    payload = b"hello\n"
    assert git_blob_sha1_bytes(payload) == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_lfs_download_records_pointer_identity_separately_from_payload_hash(tmp_path, monkeypatch):
    from research.digital_surface.data import download_git_blob_verified

    payload = b"parquet-payload"

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_content(self, size): yield payload

    monkeypatch.setattr("research.digital_surface.data.requests.get", lambda *a, **k: Response())
    spec = {
        "repo": "owner/dataset",
        "revision": "a" * 40,
        "files": [{
            "path": "data/file.parquet",
            "size": len(payload),
            "git_blob_sha1": "b" * 40,
        }],
    }
    paths = download_git_blob_verified(spec, tmp_path)
    assert paths["data/file.parquet"].read_bytes() == payload
    manifest = json.loads((tmp_path / "SOURCE_MANIFEST.json").read_text())
    row = manifest["files"]["data/file.parquet"]
    assert row["repository_git_blob_sha1"] == "b" * 40
    assert row["sha256"] == hashlib.sha256(payload).hexdigest()
    assert row["bytes"] == len(payload)


def test_gamma_historical_lookup_batches_exact_condition_ids_and_includes_closed(tmp_path, monkeypatch):
    from research.digital_surface.data import fetch_gamma_token_map

    markets = pd.DataFrame([
        {
            "condition_id": "c1",
            "slug": "btc-updown-5m-1",
            "start_time": pd.Timestamp("2026-03-06T00:05:00Z"),
            "end_time": pd.Timestamp("2026-03-06T00:05:00Z"),
        },
        {
            "condition_id": "c2",
            "slug": "btc-updown-15m-1",
            "start_time": pd.Timestamp("2026-03-06T00:15:00Z"),
            "end_time": pd.Timestamp("2026-03-06T00:15:00Z"),
        },
    ])
    calls = []

    def fake_request(url, *, params):
        calls.append(params)
        assert params["closed"] == "true"
        assert params["condition_ids"] == ["c1", "c2"]
        return [
            {"id": "1", "conditionId": "c1", "slug": "btc-updown-5m-1", "outcomes": '["Yes","No"]', "clobTokenIds": '["yes1","no1"]'},
            {"id": "2", "conditionId": "c2", "slug": "btc-updown-15m-1", "outcomes": '["Yes","No"]', "clobTokenIds": '["yes2","no2"]'},
        ]

    monkeypatch.setattr("research.digital_surface.data._request_json", fake_request)
    result = fetch_gamma_token_map(markets, tmp_path / "gamma.json").set_index("condition_id")
    assert result.loc["c1", "yes_token_id"] == "yes1"
    assert result.loc["c2", "no_token_id"] == "no2"
    assert len(calls) == 1


def test_resumable_download_retries_from_exact_partial_offset(tmp_path, monkeypatch):
    import requests
    from research.digital_surface.data import _download_resumable

    payload = b"abcdefghij"
    calls = []

    class FakeResponse:
        def __init__(self, status_code, blocks):
            self.status_code = status_code
            self.blocks = blocks

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, _chunk_size):
            for block in self.blocks:
                if isinstance(block, Exception):
                    raise block
                yield block

    responses = [
        FakeResponse(200, [payload[:4], requests.exceptions.ChunkedEncodingError("broken")]),
        FakeResponse(206, [payload[4:]]),
    ]

    def fake_get(url, *, stream, timeout, headers):
        calls.append(dict(headers))
        return responses.pop(0)

    monkeypatch.setattr("research.digital_surface.data.requests.get", fake_get)
    monkeypatch.setattr("research.digital_surface.data.time.sleep", lambda _seconds: None)
    target = tmp_path / "payload.part"
    _download_resumable("https://example.invalid/file", target, len(payload), attempts=2)
    assert target.read_bytes() == payload
    assert calls == [{}, {"Range": "bytes=4-"}]


def test_normalize_obadiaha_uses_official_token_order_and_causal_open_strike():
    markets = pd.DataFrame([
        {
            "market_id": "btc-updown-5m-1772755200",
            "asset": "BTC",
            "condition_id": "c5",
            "question": "Bitcoin Up or Down",
            "start_time": pd.Timestamp("2026-03-06T00:05:00Z"),
            "end_time": pd.Timestamp("2026-03-06T00:05:00Z"),
            "market_type": "crypto_5m",
            "slug": "btc-updown-5m-1772755200",
        },
        {
            "market_id": "btc-updown-15m-1772755200",
            "asset": "BTC",
            "condition_id": "c15",
            "question": "Bitcoin Up or Down",
            "start_time": pd.Timestamp("2026-03-06T00:15:00Z"),
            "end_time": pd.Timestamp("2026-03-06T00:15:00Z"),
            "market_type": "crypto_15m",
            "slug": "btc-updown-15m-1772755200",
        },
    ])
    resolutions = pd.DataFrame([
        {"condition_id": "c5", "outcome": "Up"},
        {"condition_id": "c15", "outcome": "Down"},
    ])
    gamma = pd.DataFrame([
        {"condition_id": "c5", "yes_token_id": "yes5", "no_token_id": "no5"},
        {"condition_id": "c15", "yes_token_id": "yes15", "no_token_id": "no15"},
    ])
    spot = pd.DataFrame([
        {"timestamp": pd.Timestamp("2026-03-06T00:00:00Z"), "asset": "BTC", "open": 100.0, "close": 100.5},
        {"timestamp": pd.Timestamp("2026-03-06T00:04:00Z"), "asset": "BTC", "open": 101.0, "close": 99.5},
        {"timestamp": pd.Timestamp("2026-03-06T00:14:00Z"), "asset": "BTC", "open": 99.5, "close": 99.0},
    ])
    raw_books = pd.DataFrame([
        {"timestamp": pd.Timestamp("2026-03-06T00:03:00Z"), "asset": "BTC", "market_id": "btc-updown-5m-1772755200", "condition_id": "c5", "token_id": "yes5", "best_bid": .40, "best_ask": .41, "bid_levels": '[{"price":0.4,"size":7}]', "ask_levels": '[{"price":0.41,"size":8}]'},
        {"timestamp": pd.Timestamp("2026-03-06T00:03:00Z"), "asset": "BTC", "market_id": "btc-updown-5m-1772755200", "condition_id": "c5", "token_id": "no5", "best_bid": .59, "best_ask": .60, "bid_levels": '[{"price":0.59,"size":9}]', "ask_levels": '[{"price":0.6,"size":10}]'},
        {"timestamp": pd.Timestamp("2026-03-06T00:13:00Z"), "asset": "BTC", "market_id": "btc-updown-15m-1772755200", "condition_id": "c15", "token_id": "yes15", "best_bid": .30, "best_ask": .31, "bid_levels": '[{"price":0.3,"size":11}]', "ask_levels": '[{"price":0.31,"size":12}]'},
        {"timestamp": pd.Timestamp("2026-03-06T00:13:00Z"), "asset": "BTC", "market_id": "btc-updown-15m-1772755200", "condition_id": "c15", "token_id": "no15", "best_bid": .69, "best_ask": .70, "bid_levels": '[{"price":0.69,"size":13}]', "ask_levels": '[{"price":0.7,"size":14}]'},
    ])
    raw_trades = pd.DataFrame([
        {"timestamp": pd.Timestamp("2026-03-06T00:03:01Z"), "asset": "BTC", "condition_id": "c5", "token_id": "yes5", "side": "BUY", "price": .41, "size": 5.0},
        {"timestamp": pd.Timestamp("2026-03-06T00:03:01Z"), "asset": "BTC", "condition_id": "c5", "token_id": "no5", "side": "SELL", "price": .59, "size": 2.0},
    ])

    official = pd.DataFrame([
        {"condition_id": "c5", "official_outcome": "Up", "url": "https://gamma.example/c5", "payload_sha256": "1" * 64},
        {"condition_id": "c15", "official_outcome": "Down", "url": "https://gamma.example/c15", "payload_sha256": "2" * 64},
    ])

    slots, books, trades, audit = normalize_obadiaha_source(
        markets, resolutions, gamma, spot, raw_books, raw_trades, official_resolutions=official
    )

    by_condition = slots.set_index("condition_id")
    assert by_condition.loc["c5", "open_ts"] == 1772755200
    assert by_condition.loc["c5", "close_ts"] == 1772755500
    assert by_condition.loc["c15", "close_ts"] == 1772756100
    assert by_condition.loc["c5", "strike"] == 100.0
    assert slots.set_index("condition_id").loc["c5", "yes_token_id"] == "yes5"
    assert slots.set_index("condition_id").loc["c15", "no_token_id"] == "no15"
    assert slots.set_index("condition_id").loc["c5", "resolved_side"] == "Yes"
    assert slots.set_index("condition_id").loc["c15", "resolved_side"] == "No"
    assert audit["official_resolution_coverage"] == 1.0
    assert audit["official_resolution_agreement"] == 1.0
    assert audit["binance_direction_agreement_diagnostic"] == 0.5
    b5 = books.set_index("condition_id").loc["c5"]
    assert b5["yes_ask_size"] == 8.0
    assert b5["no_ask_size"] == 10.0
    assert b5["spot"] == 100.0  # backward minute open, never the future 00:04 bar
    assert trades.loc[0, "taker_buy"]
    assert not trades.loc[1, "taker_buy"]
    pinned = load_official_resolution_snapshot()
    assert len(pinned) == 5228
    assert pinned["official_outcome"].isin(["Up", "Down"]).all()


def test_assign_hybrid_week_labels_orders_validation_before_four_transfer_tests():
    frame = pd.DataFrame({
        "source": ["obadiaha", "obadiaha", "kinzik", "kinzik", "kinzik", "kinzik"],
        "close_ts": [
            int(pd.Timestamp("2026-03-07T00:00:00Z").timestamp()),
            int(pd.Timestamp("2026-03-14T00:00:00Z").timestamp()),
            int(pd.Timestamp("2026-05-28T00:00:00Z").timestamp()),
            int(pd.Timestamp("2026-06-04T00:00:00Z").timestamp()),
            int(pd.Timestamp("2026-06-11T00:00:00Z").timestamp()),
            int(pd.Timestamp("2026-06-18T00:00:00Z").timestamp()),
        ],
    })
    out = assign_hybrid_week_labels(frame)
    assert out["week"].tolist() == [
        "00-obadiaha-2026-03-06_12",
        "01-obadiaha-2026-03-13_19",
        "02-kinzik-2026-05-26_06-01",
        "03-kinzik-2026-06-02_06-08",
        "04-kinzik-2026-06-09_06-15",
        "05-kinzik-2026-06-16_06-22",
    ]

from research.digital_surface.data import combine_hybrid_panels


def test_combine_hybrid_panels_preserves_two_validation_and_four_transfer_blocks():
    def panel(source, closes):
        registry = pd.DataFrame({
            "condition_id": [f"{source}-{i}" for i in range(len(closes))],
            "close_ts": closes,
            "source": source,
        })
        state = registry.copy()
        state["ts_ms"] = state["close_ts"] * 1000 - 1000
        books = pd.DataFrame({"condition_id": registry["condition_id"], "ts_ms": state["ts_ms"], "source": source})
        trades = pd.DataFrame({"token_id": [f"t-{source}-{i}" for i in range(len(closes))], "ts_ms": state["ts_ms"], "source": source})
        return registry, state, books, trades

    ob_closes = [
        int(pd.Timestamp("2026-03-07T00:00:00Z").timestamp()),
        int(pd.Timestamp("2026-03-14T00:00:00Z").timestamp()),
    ]
    kin_closes = [
        int(pd.Timestamp("2026-05-28T00:00:00Z").timestamp()),
        int(pd.Timestamp("2026-06-04T00:00:00Z").timestamp()),
        int(pd.Timestamp("2026-06-11T00:00:00Z").timestamp()),
        int(pd.Timestamp("2026-06-18T00:00:00Z").timestamp()),
    ]
    registry, state, books, trades = combine_hybrid_panels(panel("obadiaha", ob_closes), panel("kinzik", kin_closes))
    assert state["week"].nunique() == 6
    assert sorted(state["week"].unique())[:2] == [
        "00-obadiaha-2026-03-06_12",
        "01-obadiaha-2026-03-13_19",
    ]
    assert all(label.startswith(("00-", "01-")) for label in registry[registry.source == "obadiaha"].week)
    assert len(books) == 6
    assert len(trades) == 6
