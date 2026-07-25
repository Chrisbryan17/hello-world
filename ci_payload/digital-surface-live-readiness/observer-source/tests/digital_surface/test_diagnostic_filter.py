import json

import pytest

from research.digital_surface.diagnostic_filter import DiagnosticBloomFilter, build_diagnostic_bloom
from research.digital_surface.prospective import ProspectiveContaminationError, ProspectiveLedger


def test_bloom_round_trip_has_no_false_negatives_for_supplied_ids(tmp_path):
    ids = [f"0x{index:064x}" for index in range(100)]
    payload = build_diagnostic_bloom(ids, source_sha256="a" * 64, m_bits=4096, k_hashes=5)
    path = tmp_path / "filter.json"
    path.write_text(json.dumps(payload))
    loaded = DiagnosticBloomFilter.from_path(path)
    assert all(value in loaded for value in ids)
    assert loaded.item_count == 100
    assert loaded.source_sha256 == "a" * 64


def test_bloom_can_enforce_prospective_contamination_rejection(tmp_path):
    known = "0x" + "1" * 64
    payload = build_diagnostic_bloom([known], source_sha256="a" * 64, m_bits=1024, k_hashes=4)
    bloom = DiagnosticBloomFilter.from_payload(payload)
    ledger = ProspectiveLedger(tmp_path / "ledger.jsonl", diagnostic_market_ids=bloom)
    with pytest.raises(ProspectiveContaminationError, match="appeared in diagnostic data"):
        ledger.append_observation(
            market_id=known,
            first_seen_ts_ms=1,
            policy_sha256="b" * 64,
            source_sha256="c" * 64,
        )


def test_rejects_corrupt_filter_bitset():
    payload = build_diagnostic_bloom(["known"], source_sha256="a" * 64, m_bits=1024, k_hashes=4)
    payload["bitset_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="bitset SHA-256 mismatch"):
        DiagnosticBloomFilter.from_payload(payload)
