import json

import pytest

from research.digital_surface.binance_public import BTCMarketState
from research.digital_surface.spot_ledger import SpotStateIntegrityError, SpotStateLedger


def state():
    return BTCMarketState(
        symbol="BTCUSDT",
        server_time_ms=2_000,
        observed_ts_ms=2_100,
        spot=__import__("decimal").Decimal("100.50"),
        vol_30s=0.001,
        vol_120s=0.002,
        strikes={1_800_000: __import__("decimal").Decimal("99.00")},
        closed_one_second_bars=121,
        raw_response_sha256={
            "server_time": "a" * 64,
            "one_second_klines": "b" * 64,
            "strike:1800000": "c" * 64,
        },
    )


def test_appends_state_bound_to_policy_source_and_prospective_head(tmp_path):
    path = tmp_path / "btc_state.jsonl"
    ledger = SpotStateLedger(path)
    first = ledger.append(
        state(),
        policy_sha256="1" * 64,
        source_sha256="2" * 64,
        prospective_head_sha256="3" * 64,
    )
    assert first["previous_hash"] == "0" * 64
    assert first["state"]["spot"] == "100.50"
    assert first["state"]["strikes"] == {"1800000": "99.00"}
    assert len(first["state_sha256"]) == 64

    reloaded = SpotStateLedger(path)
    assert reloaded.head_hash == first["record_hash"]
    assert len(reloaded.rows) == 1


def test_detects_state_or_digest_tampering(tmp_path):
    path = tmp_path / "btc_state.jsonl"
    ledger = SpotStateLedger(path)
    ledger.append(
        state(),
        policy_sha256="1" * 64,
        source_sha256="2" * 64,
        prospective_head_sha256="3" * 64,
    )
    row = json.loads(path.read_text())
    row["state"]["spot"] = "999999"
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(SpotStateIntegrityError, match="record hash mismatch|state hash mismatch"):
        SpotStateLedger(path)


def test_rejects_duplicate_snapshot_identity(tmp_path):
    path = tmp_path / "btc_state.jsonl"
    ledger = SpotStateLedger(path)
    kwargs = {
        "policy_sha256": "1" * 64,
        "source_sha256": "2" * 64,
        "prospective_head_sha256": "3" * 64,
    }
    ledger.append(state(), **kwargs)
    with pytest.raises(ValueError, match="duplicate BTC state snapshot"):
        ledger.append(state(), **kwargs)
