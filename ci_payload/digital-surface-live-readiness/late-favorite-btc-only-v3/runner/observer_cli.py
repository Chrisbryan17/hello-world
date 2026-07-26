from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from capture_policy import CaptureBoundLifecycleLedger, load_capture_policy
from late_favorite_v3 import load_frozen_policy
from public_collector import (
    PublicHttpClient,
    RawEvidenceStore,
    SingleMarketCollector,
    next_collectable_open,
)
from resolution import SingleMarketResolver

_RUNTIME_SOURCE_PATHS = (
    "source/late_favorite_v3.py",
    "source/capture_policy.py",
    "collector/public_collector.py",
    "collector/resolution.py",
    "runner/observer_cli.py",
)


@dataclass(slots=True)
class ObserverRuntime:
    project_root: Path
    state_dir: Path
    capture_policy: Any
    ledger: Any
    evidence_store: Any
    collector: Any
    resolver: Any
    clock_ms: Callable[[], int]
    sleep_until_ms: Callable[[int], None]
    source_sha256: str
    trading_policy: Any = None
    client: Any = None


def compute_combined_source_sha256(project_root: str | Path) -> str:
    root = Path(project_root)
    digest = hashlib.sha256()
    for relative in _RUNTIME_SOURCE_PATHS:
        path = root / relative
        raw = path.read_bytes()
        digest.update(relative.encode("utf-8") + b"\0" + raw)
    return digest.hexdigest()


def _real_clock_ms() -> int:
    return time.time_ns() // 1_000_000


def make_sleep_until_ms(
    clock_ms: Callable[[], int],
    sleeper: Callable[[float], None] = time.sleep,
) -> Callable[[int], None]:
    def sleep_until(target_ts_ms: int) -> None:
        target = int(target_ts_ms)
        while True:
            remaining_ms = target - int(clock_ms())
            if remaining_ms <= 0:
                return
            sleeper(min(remaining_ms / 1000.0, 0.25))

    return sleep_until


def build_runtime(
    project_root: str | Path,
    state_dir: str | Path,
    *,
    clock_ms: Callable[[], int] | None = None,
    sleep_until_ms: Callable[[int], None] | None = None,
    requester: Callable[..., Any] | None = None,
) -> ObserverRuntime:
    root = Path(project_root).resolve()
    state = Path(state_dir).resolve()
    source_sha256 = compute_combined_source_sha256(root)
    trading_policy = load_frozen_policy(
        root / "CANDIDATE_SPEC.json",
        root / "FREEZE_MANIFEST.json",
        source_sha256=source_sha256,
    )
    capture_policy = load_capture_policy(
        root / "CAPTURE_POLICY.json",
        root / "CAPTURE_FREEZE_MANIFEST.json",
    )
    clock = clock_ms or _real_clock_ms
    sleep_until = sleep_until_ms or make_sleep_until_ms(clock)
    ledger = CaptureBoundLifecycleLedger(
        state / "lifecycle.jsonl",
        trading_policy,
        capture_policy,
    )
    evidence = RawEvidenceStore(state / "raw_evidence")
    client_kwargs: dict[str, Any] = {"clock_ms": clock}
    if requester is not None:
        client_kwargs["requester"] = requester
    client = PublicHttpClient(**client_kwargs)
    collector = SingleMarketCollector(
        client=client,
        evidence_store=evidence,
        ledger=ledger,
        trading_policy=trading_policy,
        capture_policy=capture_policy,
        sleep_until_ms=sleep_until,
    )
    resolver = SingleMarketResolver(
        client=client,
        evidence_store=evidence,
        ledger=ledger,
        trading_policy=trading_policy,
        capture_policy=capture_policy,
    )
    return ObserverRuntime(
        project_root=root,
        state_dir=state,
        capture_policy=capture_policy,
        ledger=ledger,
        evidence_store=evidence,
        collector=collector,
        resolver=resolver,
        clock_ms=clock,
        sleep_until_ms=sleep_until,
        source_sha256=source_sha256,
        trading_policy=trading_policy,
        client=client,
    )


def _summary_path(runtime: ObserverRuntime, name: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("._")
    if not safe:
        raise ValueError("summary name is empty after sanitization")
    return runtime.state_dir / "summaries" / f"{safe}.json"


def _write_summary(runtime: ObserverRuntime, name: str, summary: dict[str, Any]) -> dict[str, Any]:
    path = _summary_path(runtime, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return summary


def _evidence_head(runtime: ObserverRuntime) -> str:
    return str(getattr(runtime.evidence_store, "head_hash", "0" * 64))


def collect_next(runtime: ObserverRuntime, *, now_ts_ms: int | None = None) -> dict[str, Any]:
    now = int(runtime.clock_ms() if now_ts_ms is None else now_ts_ms)
    opening = next_collectable_open(
        now,
        int(runtime.capture_policy.valid_market_open_after_epoch_seconds),
    )
    discovery_target = opening * 1000 + 1_000
    if now < discovery_target:
        runtime.sleep_until_ms(discovery_target)
    result = dict(runtime.collector.capture(opening))
    summary = {
        **result,
        "command": "collect-next",
        "market_open_epoch_seconds": opening,
        "source_sha256": runtime.source_sha256,
        "lifecycle_head_sha256": str(runtime.ledger.head_hash),
        "raw_evidence_head_sha256": _evidence_head(runtime),
        "lifecycle_records": len(getattr(runtime.ledger, "records", [])),
        "raw_evidence_records": len(getattr(runtime.evidence_store, "records", [])),
    }
    return _write_summary(runtime, f"collect-{opening}", summary)


def resolve_condition(runtime: ObserverRuntime, condition_id: str) -> dict[str, Any]:
    condition = str(condition_id).strip()
    if not condition:
        raise ValueError("condition_id must be non-empty")
    result = dict(runtime.resolver.resolve(condition))
    summary = {
        **result,
        "command": "resolve",
        "source_sha256": runtime.source_sha256,
        "lifecycle_head_sha256": str(runtime.ledger.head_hash),
        "raw_evidence_head_sha256": _evidence_head(runtime),
        "lifecycle_records": len(getattr(runtime.ledger, "records", [])),
        "raw_evidence_records": len(getattr(runtime.evidence_store, "records", [])),
    }
    return _write_summary(runtime, f"resolve-{condition}", summary)


def runtime_status(runtime: ObserverRuntime) -> dict[str, Any]:
    condition_ids: set[str] = set()
    resolved: set[str] = set()
    event_counts: dict[str, int] = {}
    for record in getattr(runtime.ledger, "records", []):
        condition = str(record.get("condition_id", ""))
        event_type = str(record.get("event_type", ""))
        if condition:
            condition_ids.add(condition)
            if event_type == "resolution":
                resolved.add(condition)
        event_counts[event_type] = event_counts.get(event_type, 0) + 1
    return {
        "command": "status",
        "conditions_seen": len(condition_ids),
        "conditions_resolved": len(resolved),
        "unresolved_condition_ids": sorted(condition_ids - resolved),
        "event_counts": dict(sorted(event_counts.items())),
        "source_sha256": runtime.source_sha256,
        "lifecycle_head_sha256": str(runtime.ledger.head_hash),
        "raw_evidence_head_sha256": _evidence_head(runtime),
        "lifecycle_records": len(getattr(runtime.ledger, "records", [])),
        "raw_evidence_records": len(getattr(runtime.evidence_store, "records", [])),
    }


def build_parser() -> argparse.ArgumentParser:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Credential-free BTC-only v3 prospective shadow runner"
    )
    parser.add_argument("--project-root", type=Path, default=default_root)
    parser.add_argument("--state-dir", type=Path, default=Path(".prospective/btc-only-v3"))
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect-next", help="collect the next eligible BTC window")
    collect.add_argument("--now-ms", type=int)
    resolve = commands.add_parser("resolve", help="resolve one collected condition")
    resolve.add_argument("--condition-id", required=True)
    commands.add_parser("status", help="show ledger and unresolved-condition status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = build_runtime(args.project_root, args.state_dir)
    if args.command == "collect-next":
        output = collect_next(runtime, now_ts_ms=args.now_ms)
    elif args.command == "resolve":
        output = resolve_condition(runtime, args.condition_id)
    elif args.command == "status":
        output = runtime_status(runtime)
    else:  # pragma: no cover
        raise RuntimeError(f"unsupported command: {args.command}")
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
