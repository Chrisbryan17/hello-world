from __future__ import annotations

import json
from pathlib import Path

import pytest

from prospective_aggregate import (
    DuplicateMarketError,
    PolicyMismatchError,
    build_aggregate,
    write_aggregate,
)

CANDIDATE_SHA = "1" * 64
CAPTURE_SHA = "2" * 64


def dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def add_one_shot(root: Path, *, opening: int = 1000, source_sha: str = "a" * 64) -> None:
    checkpoint = root / "prospective-run-v1"
    dump(
        checkpoint / "VERIFICATION.json",
        {
            "candidate_policy_sha256": CANDIDATE_SHA,
            "capture_policy_sha256": CAPTURE_SHA,
            "run": {"runtime_source_sha256": source_sha},
            "status": "valid_prospective_observation_not_admission",
        },
    )
    dump(
        checkpoint / "PROSPECTIVE_RUN.json",
        {
            "market_open_epoch_seconds": opening,
            "condition_id": "condition-one",
            "capture_decision": "no_fill_ask_above_limit",
            "resolution_status": "terminal",
            "resolution": {
                "decision": "resolved_no_fill",
                "official_outcome": "Up",
                "pnl_total": None,
            },
            "credentials_used": 0,
            "authenticated_requests": 0,
            "order_submissions": 0,
            "historical_admission_credit": 0,
        },
    )


def add_block(
    root: Path,
    *,
    openings: tuple[int, int] = (1300, 1600),
    source_sha: str = "b" * 64,
) -> None:
    checkpoint = root / "prospective-block-v1"
    dump(
        checkpoint / "VERIFICATION.json",
        {
            "candidate_policy_sha256": CANDIDATE_SHA,
            "capture_policy_sha256": CAPTURE_SHA,
            "run": {"runtime_source_sha256": source_sha},
            "status": "valid_complete_prospective_block_not_admission",
        },
    )
    dump(
        checkpoint / "BLOCK_SUMMARY.json",
        {
            "status": "complete",
            "markets_collected": 2,
            "conditions_resolved": 2,
            "hypothetical_fok_fills": 1,
            "prospective_pnl_total": "0.25",
            "unresolved_condition_ids": [],
            "credentials_used": 0,
            "authenticated_requests": 0,
            "order_submissions": 0,
        },
    )
    dump(
        checkpoint / "MARKETS.json",
        [
            {
                "market_open_epoch_seconds": openings[0],
                "condition_id": "condition-two",
                "decision": "hypothetical_fok_fill",
                "official_outcome": "Down",
                "pnl_total": "0.25",
            },
            {
                "market_open_epoch_seconds": openings[1],
                "condition_id": "condition-three",
                "decision": "no_signal_below_threshold",
                "official_outcome": "Up",
                "pnl_total": None,
            },
        ],
    )


def test_build_aggregate_recomputes_all_counters_from_market_records(tmp_path: Path) -> None:
    root = tmp_path / "late-favorite-btc-only-v3"
    add_one_shot(root)
    add_block(root)

    report = build_aggregate(root)

    assert report["candidate_policy_sha256"] == CANDIDATE_SHA
    assert report["capture_policy_sha256"] == CAPTURE_SHA
    assert report["prospective_markets_observed"] == 3
    assert report["official_outcomes_available"] == 3
    assert report["official_outcome_coverage"] == 1.0
    assert report["hypothetical_fok_fills"] == 1
    assert report["prospective_pnl_total"] == "0.25"
    assert report["unresolved_condition_ids"] == []
    assert report["capture_decision_counts"] == {
        "hypothetical_fok_fill": 1,
        "no_fill_ask_above_limit": 1,
        "no_signal_below_threshold": 1,
    }
    assert report["official_outcome_counts"] == {"Down": 1, "Up": 2}
    assert report["runtime_source_epochs"] == {
        "a" * 64: 1,
        "b" * 64: 2,
    }
    assert [row["market_open_epoch_seconds"] for row in report["markets"]] == [1000, 1300, 1600]
    assert report["safety"] == {
        "authenticated_requests": 0,
        "credentials_used": 0,
        "historical_admission_credit": 0,
        "order_submissions": 0,
    }
    assert report["status"] == "prospective_shadow_only_not_admitted"


def test_duplicate_market_opening_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "late-favorite-btc-only-v3"
    add_one_shot(root, opening=1000)
    add_block(root, openings=(1000, 1600))

    with pytest.raises(DuplicateMarketError):
        build_aggregate(root)


def test_policy_mismatch_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "late-favorite-btc-only-v3"
    add_one_shot(root)
    add_block(root)
    verification = root / "prospective-block-v1" / "VERIFICATION.json"
    payload = json.loads(verification.read_text())
    payload["candidate_policy_sha256"] = "f" * 64
    dump(verification, payload)

    with pytest.raises(PolicyMismatchError):
        build_aggregate(root)


def test_unresolved_or_missing_official_outcome_is_not_counted_as_coverage(tmp_path: Path) -> None:
    root = tmp_path / "late-favorite-btc-only-v3"
    add_one_shot(root)
    run_path = root / "prospective-run-v1" / "PROSPECTIVE_RUN.json"
    payload = json.loads(run_path.read_text())
    payload["resolution_status"] = "unresolved"
    payload["resolution"] = None
    dump(run_path, payload)

    report = build_aggregate(root)

    assert report["prospective_markets_observed"] == 1
    assert report["official_outcomes_available"] == 0
    assert report["official_outcome_coverage"] == 0.0
    assert report["unresolved_condition_ids"] == ["condition-one"]


def test_write_aggregate_is_deterministic_and_refuses_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "late-favorite-btc-only-v3"
    add_one_shot(root)
    destination = tmp_path / "aggregate.json"

    first = write_aggregate(root, destination)
    assert json.loads(destination.read_text()) == first
    with pytest.raises(FileExistsError):
        write_aggregate(root, destination)
