from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from observer_cli import (
    ObserverRuntime,
    build_parser,
    collect_next,
    compute_combined_source_sha256,
    resolve_condition,
    runtime_status,
)


@dataclass
class FakeCapturePolicy:
    valid_market_open_after_epoch_seconds: int = 1_800_000_100


class FakeCollector:
    def __init__(self) -> None:
        self.openings: list[int] = []

    def capture(self, opening: int) -> dict[str, object]:
        self.openings.append(opening)
        return {
            "condition_id": f"condition-{opening}",
            "market_open_epoch_seconds": opening,
            "decision": "hypothetical_fok_fill",
        }


class FakeResolver:
    def __init__(self) -> None:
        self.conditions: list[str] = []

    def resolve(self, condition_id: str) -> dict[str, object]:
        self.conditions.append(condition_id)
        return {
            "condition_id": condition_id,
            "decision": "resolved_fill",
            "official_outcome": "Up",
            "pnl_total": "0.45",
        }


class FakeLedger:
    def __init__(self) -> None:
        self.head_hash = "a" * 64
        self.records = [
            {
                "condition_id": "resolved",
                "event_type": "resolution",
                "record_hash": "1" * 64,
            },
            {
                "condition_id": "unresolved",
                "event_type": "signal",
                "record_hash": "2" * 64,
            },
        ]


class FakeEvidence:
    head_hash = "b" * 64
    records = [{"record_hash": "3" * 64}]


def runtime(tmp_path: Path, *, now_ms: int, sleeps: list[int]) -> ObserverRuntime:
    return ObserverRuntime(
        project_root=tmp_path,
        state_dir=tmp_path / "state",
        capture_policy=FakeCapturePolicy(),
        ledger=FakeLedger(),
        evidence_store=FakeEvidence(),
        collector=FakeCollector(),
        resolver=FakeResolver(),
        clock_ms=lambda: now_ms,
        sleep_until_ms=sleeps.append,
        source_sha256="c" * 64,
    )


def test_combined_source_hash_binds_all_runtime_modules(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    (root / "source").mkdir(parents=True)
    (root / "collector").mkdir(parents=True)
    files = {
        root / "source/late_favorite_v3.py": b"core\n",
        root / "source/capture_policy.py": b"capture\n",
        root / "collector/public_collector.py": b"collector\n",
        root / "collector/resolution.py": b"resolution\n",
        root / "runner/observer_cli.py": b"runner\n",
    }
    (root / "runner").mkdir(parents=True)
    for path, content in files.items():
        path.write_bytes(content)
    first = compute_combined_source_sha256(root)
    assert len(first) == 64
    files[root / "runner/observer_cli.py"] = b"runner changed\n"
    (root / "runner/observer_cli.py").write_bytes(files[root / "runner/observer_cli.py"])
    assert compute_combined_source_sha256(root) != first


def test_collect_next_selects_future_window_and_persists_summary(tmp_path: Path) -> None:
    opening = 1_800_000_300
    now_ms = opening * 1000 + 210_001
    sleeps: list[int] = []
    rt = runtime(tmp_path, now_ms=now_ms, sleeps=sleeps)
    summary = collect_next(rt, now_ts_ms=now_ms)
    selected = opening + 300
    assert rt.collector.openings == [selected]
    assert sleeps == [selected * 1000 + 1_000]
    assert summary["condition_id"] == f"condition-{selected}"
    assert summary["lifecycle_head_sha256"] == "a" * 64
    assert summary["raw_evidence_head_sha256"] == "b" * 64
    saved = json.loads((rt.state_dir / "summaries" / f"collect-{selected}.json").read_text())
    assert saved == summary
    with pytest.raises(FileExistsError):
        collect_next(rt, now_ts_ms=now_ms)


def test_resolve_condition_persists_official_summary(tmp_path: Path) -> None:
    rt = runtime(tmp_path, now_ms=1_800_000_000_000, sleeps=[])
    summary = resolve_condition(rt, "condition-1")
    assert rt.resolver.conditions == ["condition-1"]
    assert summary["official_outcome"] == "Up"
    path = rt.state_dir / "summaries" / "resolve-condition-1.json"
    assert json.loads(path.read_text()) == summary


def test_runtime_status_lists_unresolved_conditions(tmp_path: Path) -> None:
    status = runtime_status(runtime(tmp_path, now_ms=0, sleeps=[]))
    assert status["conditions_seen"] == 2
    assert status["conditions_resolved"] == 1
    assert status["unresolved_condition_ids"] == ["unresolved"]
    assert status["lifecycle_head_sha256"] == "a" * 64


def test_cli_exposes_only_collect_resolve_and_status() -> None:
    parser = build_parser()
    assert parser.parse_args(["collect-next"]).command == "collect-next"
    assert parser.parse_args(["resolve", "--condition-id", "c1"]).condition_id == "c1"
    assert parser.parse_args(["status"]).command == "status"
    with pytest.raises(SystemExit):
        parser.parse_args(["live"])
    with pytest.raises(SystemExit):
        parser.parse_args(["submit-order"])
