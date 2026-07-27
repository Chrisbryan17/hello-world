from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from observer_cli import (
    MAX_BLOCK_MARKETS,
    ObserverRuntime,
    build_parser,
    collect_block,
)


@dataclass
class FakeCapturePolicy:
    valid_market_open_after_epoch_seconds: int = 1_800_000_100


@dataclass
class FakeLedger:
    operations: list[str]
    head_hash: str = "a" * 64
    records: list[dict[str, object]] = field(default_factory=list)


@dataclass
class FakeEvidence:
    head_hash: str = "b" * 64
    records: list[dict[str, object]] = field(default_factory=list)


class FakeCollector:
    def __init__(self, operations: list[str], ledger: FakeLedger, evidence: FakeEvidence) -> None:
        self.operations = operations
        self.ledger = ledger
        self.evidence = evidence
        self.openings: list[int] = []

    def capture(self, opening: int) -> dict[str, object]:
        self.openings.append(opening)
        self.operations.append(f"capture:{opening}")
        condition = f"condition-{opening}"
        decision = (
            "hypothetical_fok_fill"
            if len(self.openings) == 1
            else "no_signal_below_threshold"
            if len(self.openings) == 2
            else "no_fill_ask_above_limit"
        )
        self.ledger.records.append(
            {
                "condition_id": condition,
                "event_type": "arrival" if decision != "no_signal_below_threshold" else "signal",
            }
        )
        self.evidence.records.append({"opening": opening})
        return {
            "condition_id": condition,
            "market_open_epoch_seconds": opening,
            "decision": decision,
            "hypothetical_fok_fill": decision == "hypothetical_fok_fill",
        }


class FakeResolver:
    def __init__(
        self,
        operations: list[str],
        ledger: FakeLedger,
        evidence: FakeEvidence,
        *,
        failures_before_success: int = 0,
        never_resolve: bool = False,
    ) -> None:
        self.operations = operations
        self.ledger = ledger
        self.evidence = evidence
        self.failures_before_success = failures_before_success
        self.never_resolve = never_resolve
        self.attempts: dict[str, int] = {}

    def resolve(self, condition_id: str) -> dict[str, object]:
        self.operations.append(f"resolve:{condition_id}")
        attempt = self.attempts.get(condition_id, 0) + 1
        self.attempts[condition_id] = attempt
        self.evidence.records.append({"condition_id": condition_id, "attempt": attempt})
        if self.never_resolve or attempt <= self.failures_before_success:
            raise ValueError("Gamma market is not closed")
        self.ledger.records.append(
            {"condition_id": condition_id, "event_type": "resolution"}
        )
        return {
            "condition_id": condition_id,
            "decision": "resolved_fill" if condition_id.endswith("300") else "resolved_no_fill",
            "official_outcome": "Up",
            "pnl_total": "0.45" if condition_id.endswith("300") else None,
        }


def runtime(
    tmp_path: Path,
    *,
    now_ms: int,
    failures_before_success: int = 0,
    never_resolve: bool = False,
) -> tuple[ObserverRuntime, list[str], list[int]]:
    operations: list[str] = []
    sleeps: list[int] = []
    ledger = FakeLedger(operations)
    evidence = FakeEvidence()
    collector = FakeCollector(operations, ledger, evidence)
    resolver = FakeResolver(
        operations,
        ledger,
        evidence,
        failures_before_success=failures_before_success,
        never_resolve=never_resolve,
    )
    return (
        ObserverRuntime(
            project_root=tmp_path,
            state_dir=tmp_path / "state",
            capture_policy=FakeCapturePolicy(),
            ledger=ledger,
            evidence_store=evidence,
            collector=collector,
            resolver=resolver,
            clock_ms=lambda: now_ms,
            sleep_until_ms=sleeps.append,
            source_sha256="c" * 64,
        ),
        operations,
        sleeps,
    )


def test_collect_block_captures_consecutive_windows_before_any_resolution(tmp_path: Path) -> None:
    first_opening = 1_800_000_300
    now_ms = first_opening * 1000 + 500
    rt, operations, sleeps = runtime(tmp_path, now_ms=now_ms, failures_before_success=1)

    summary = collect_block(
        rt,
        markets=3,
        now_ts_ms=now_ms,
        max_resolution_attempts=3,
        retry_delay_ms=10_000,
    )

    openings = [first_opening, first_opening + 300, first_opening + 600]
    assert rt.collector.openings == openings
    first_resolve_index = next(
        index for index, operation in enumerate(operations) if operation.startswith("resolve:")
    )
    assert all(operation.startswith("capture:") for operation in operations[:first_resolve_index])
    assert operations[:3] == [f"capture:{opening}" for opening in openings]
    assert sleeps[:3] == [opening * 1000 + 1_000 for opening in openings]
    assert summary["status"] == "complete"
    assert summary["markets_requested"] == 3
    assert summary["markets_collected"] == 3
    assert summary["conditions_resolved"] == 3
    assert summary["unresolved_condition_ids"] == []
    assert summary["hypothetical_fok_fills"] == 1
    assert summary["capture_decision_counts"] == {
        "hypothetical_fok_fill": 1,
        "no_fill_ask_above_limit": 1,
        "no_signal_below_threshold": 1,
    }
    assert summary["resolution_attempts_by_condition"] == {
        f"condition-{opening}": 2 for opening in openings
    }
    saved = json.loads(
        (
            rt.state_dir
            / "summaries"
            / f"block-{openings[0]}-{openings[-1]}.json"
        ).read_text()
    )
    assert saved == summary


def test_collect_block_records_unresolved_conditions_after_bounded_attempts(tmp_path: Path) -> None:
    opening = 1_800_000_300
    now_ms = opening * 1000 + 500
    rt, operations, sleeps = runtime(tmp_path, now_ms=now_ms, never_resolve=True)

    summary = collect_block(
        rt,
        markets=1,
        now_ts_ms=now_ms,
        max_resolution_attempts=2,
        retry_delay_ms=5_000,
    )

    condition = f"condition-{opening}"
    assert summary["status"] == "unresolved"
    assert summary["conditions_resolved"] == 0
    assert summary["unresolved_condition_ids"] == [condition]
    assert summary["resolution_attempts_by_condition"] == {condition: 2}
    assert operations == [
        f"capture:{opening}",
        f"resolve:{condition}",
        f"resolve:{condition}",
    ]
    assert sleeps == [opening * 1000 + 1_000, now_ms + 5_000]


@pytest.mark.parametrize("markets", [0, -1, MAX_BLOCK_MARKETS + 1])
def test_collect_block_rejects_unbounded_market_counts(tmp_path: Path, markets: int) -> None:
    rt, _, _ = runtime(tmp_path, now_ms=1_800_000_300_500)
    with pytest.raises(ValueError):
        collect_block(rt, markets=markets)


def test_cli_exposes_bounded_collect_block_without_live_commands() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "collect-block",
            "--markets",
            "3",
            "--max-resolution-attempts",
            "120",
            "--retry-delay-ms",
            "10000",
        ]
    )
    assert args.command == "collect-block"
    assert args.markets == 3
    assert args.max_resolution_attempts == 120
    assert args.retry_delay_ms == 10_000
    with pytest.raises(SystemExit):
        parser.parse_args(["submit-block"])
