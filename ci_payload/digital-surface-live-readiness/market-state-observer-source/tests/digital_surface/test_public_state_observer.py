from decimal import Decimal

from research.digital_surface.binance_public import BTCMarketState
from research.digital_surface.market_discovery import GammaMarketRecord
from research.digital_surface.public_state_observer import observe_public_btc_state
from research.digital_surface.spot_ledger import SpotStateLedger


def market(condition: str, epoch: int, duration: int = 300) -> GammaMarketRecord:
    return GammaMarketRecord(
        condition_id=condition,
        slug=f"btc-updown-{duration // 60}m-{epoch}",
        question="Bitcoin Up or Down",
        yes_token_id=f"yes-{condition}",
        no_token_id=f"no-{condition}",
        duration_seconds=duration,
        open_epoch_seconds=epoch,
        end_date="2030-01-01T00:00:00Z",
        tick_size=Decimal("0.01"),
    )


def test_collects_unique_boundaries_only_for_registered_prospective_markets(tmp_path):
    markets = [
        market("registered-5", 1_800),
        market("registered-15", 1_800, duration=900),
        market("unregistered", 2_100),
    ]
    calls = []

    def collect(boundaries, *, observed_ts_ms):
        calls.append((list(boundaries), observed_ts_ms))
        return BTCMarketState(
            symbol="BTCUSDT",
            server_time_ms=5_000,
            observed_ts_ms=observed_ts_ms,
            spot=Decimal("100.50"),
            vol_30s=0.001,
            vol_120s=0.002,
            strikes={1_800_000: Decimal("99.00")},
            closed_one_second_bars=121,
            raw_response_sha256={
                "server_time": "a" * 64,
                "one_second_klines": "b" * 64,
                "strike:1800000": "c" * 64,
            },
        )

    ledger = SpotStateLedger(tmp_path / "btc_state.jsonl")
    summary = observe_public_btc_state(
        markets,
        prospective_market_ids={"registered-5", "registered-15"},
        prospective_head_sha256="3" * 64,
        ledger=ledger,
        observed_ts_ms=5_100,
        policy_sha256="1" * 64,
        source_sha256="2" * 64,
        collect=collect,
    )

    assert calls == [([1_800_000], 5_100)]
    assert summary["markets_registered"] == 2
    assert summary["markets_skipped_unregistered"] == 1
    assert summary["strike_boundaries"] == [1_800_000]
    assert summary["spot_state_head_sha256"] == ledger.head_hash
    assert summary["authenticated_requests"] == 0
    assert summary["order_submissions"] == 0


def test_empty_registered_set_still_records_causal_spot_without_strikes(tmp_path):
    calls = []

    def collect(boundaries, *, observed_ts_ms):
        calls.append(list(boundaries))
        return BTCMarketState(
            symbol="BTCUSDT",
            server_time_ms=5_000,
            observed_ts_ms=observed_ts_ms,
            spot=Decimal("100.50"),
            vol_30s=0.001,
            vol_120s=0.002,
            strikes={},
            closed_one_second_bars=121,
            raw_response_sha256={
                "server_time": "a" * 64,
                "one_second_klines": "b" * 64,
            },
        )

    ledger = SpotStateLedger(tmp_path / "btc_state.jsonl")
    summary = observe_public_btc_state(
        [market("unregistered", 2_100)],
        prospective_market_ids=set(),
        prospective_head_sha256="3" * 64,
        ledger=ledger,
        observed_ts_ms=5_100,
        policy_sha256="1" * 64,
        source_sha256="2" * 64,
        collect=collect,
    )
    assert calls == [[]]
    assert summary["markets_registered"] == 0
    assert summary["strike_boundaries"] == []
    assert len(ledger.rows) == 1
