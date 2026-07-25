import json

import pytest

from research.digital_surface.prospective import (
    ProspectiveContaminationError,
    ProspectiveIntegrityError,
    ProspectiveLedger,
)


def test_rejects_diagnostic_markets_and_appends_new_observations_with_hash_chain(tmp_path):
    path = tmp_path / "prospective.jsonl"
    ledger = ProspectiveLedger(path, diagnostic_market_ids={"known"})

    with pytest.raises(ProspectiveContaminationError, match="known"):
        ledger.append_observation(
            market_id="known",
            first_seen_ts_ms=100,
            policy_sha256="1" * 64,
            source_sha256="2" * 64,
        )

    first = ledger.append_observation(
        market_id="new-1",
        first_seen_ts_ms=101,
        policy_sha256="1" * 64,
        source_sha256="2" * 64,
    )
    second = ledger.append_observation(
        market_id="new-2",
        first_seen_ts_ms=102,
        policy_sha256="1" * 64,
        source_sha256="2" * 64,
    )

    assert first["previous_hash"] == "0" * 64
    assert second["previous_hash"] == first["record_hash"]
    assert ledger.market_ids == {"new-1", "new-2"}

    reloaded = ProspectiveLedger(path, diagnostic_market_ids={"known"})
    assert reloaded.market_ids == ledger.market_ids
    assert reloaded.head_hash == second["record_hash"]


def test_rejects_duplicate_market_ids_and_noncanonical_hashes(tmp_path):
    path = tmp_path / "prospective.jsonl"
    ledger = ProspectiveLedger(path, diagnostic_market_ids=set())
    ledger.append_observation(
        market_id="new-1",
        first_seen_ts_ms=101,
        policy_sha256="1" * 64,
        source_sha256="2" * 64,
    )

    with pytest.raises(ProspectiveContaminationError, match="already observed"):
        ledger.append_observation(
            market_id="new-1",
            first_seen_ts_ms=102,
            policy_sha256="1" * 64,
            source_sha256="2" * 64,
        )

    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["market_id"] = "tampered"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    with pytest.raises(ProspectiveIntegrityError, match="record hash mismatch"):
        ProspectiveLedger(path, diagnostic_market_ids=set())


def test_requires_fixed_length_source_and_policy_hashes(tmp_path):
    ledger = ProspectiveLedger(tmp_path / "prospective.jsonl", diagnostic_market_ids=set())
    with pytest.raises(ValueError, match="policy_sha256"):
        ledger.append_observation(
            market_id="new",
            first_seen_ts_ms=1,
            policy_sha256="short",
            source_sha256="2" * 64,
        )
