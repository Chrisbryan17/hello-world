import json

from research.digital_surface.diagnostic_filter import DiagnosticBloomFilter, build_diagnostic_bloom
from research.digital_surface.market_discovery import GammaMarketRecord
from research.digital_surface.prospective import ProspectiveLedger
from research.digital_surface.public_observer import observe_markets


def record(condition, *, duration=300, epoch=1774450800):
    return GammaMarketRecord(
        condition_id=condition,
        slug=f"btc-updown-{duration // 60}m-{epoch}",
        question="Bitcoin Up or Down",
        yes_token_id=f"yes-{condition}",
        no_token_id=f"no-{condition}",
        duration_seconds=duration,
        open_epoch_seconds=epoch,
        end_date="2026-07-25T15:00:00Z",
        tick_size=__import__("decimal").Decimal("0.01"),
    )


def test_observer_rejects_historical_and_appends_full_new_market_metadata(tmp_path):
    known = "known"
    bloom = DiagnosticBloomFilter.from_payload(
        build_diagnostic_bloom([known], source_sha256="a" * 64, m_bits=1024, k_hashes=4)
    )
    ledger = ProspectiveLedger(tmp_path / "ledger.jsonl", diagnostic_market_ids=bloom)
    summary = observe_markets(
        [record(known), record("fresh")],
        ledger=ledger,
        observed_ts_ms=123,
        policy_sha256="b" * 64,
        source_sha256="c" * 64,
    )
    assert summary["discovered"] == 2
    assert summary["appended"] == 1
    assert summary["skipped_diagnostic"] == 1
    row = json.loads((tmp_path / "ledger.jsonl").read_text())
    assert row["market_id"] == "fresh"
    assert row["metadata"]["yes_token_id"] == "yes-fresh"
    assert row["metadata"]["no_token_id"] == "no-fresh"
    assert row["metadata"]["duration_seconds"] == 300
    assert row["metadata"]["tick_size"] == "0.01"


def test_observer_is_idempotent_for_already_observed_markets(tmp_path):
    bloom = DiagnosticBloomFilter.from_payload(
        build_diagnostic_bloom([], source_sha256="a" * 64, m_bits=1024, k_hashes=4)
    )
    ledger = ProspectiveLedger(tmp_path / "ledger.jsonl", diagnostic_market_ids=bloom)
    first = observe_markets(
        [record("fresh")], ledger=ledger, observed_ts_ms=123,
        policy_sha256="b" * 64, source_sha256="c" * 64,
    )
    second = observe_markets(
        [record("fresh")], ledger=ledger, observed_ts_ms=124,
        policy_sha256="b" * 64, source_sha256="c" * 64,
    )
    assert first["appended"] == 1
    assert second["appended"] == 0
    assert second["skipped_existing"] == 1
    assert len((tmp_path / "ledger.jsonl").read_text().splitlines()) == 1
