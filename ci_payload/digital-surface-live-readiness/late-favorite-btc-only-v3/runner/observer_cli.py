from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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

MAX_BLOCK_MARKETS = 12
DEFAULT_RESOLUTION_ATTEMPTS = 120
DEFAULT_RETRY_DELAY_MS = 10_000


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


def _collect_opening(runtime: ObserverRuntime, opening: int) -> dict[str, Any]:
    selected_opening = int(opening)
    discovery_target = selected_opening * 1000 + 1_000
    if int(runtime.clock_ms()) < discovery_target:
        runtime.sleep_until_ms(discovery_target)
    result = dict(runtime.collector.capture(selected_opening))
    summary = {
        **result,
        "command": "collect-next",
        "market_open_epoch_seconds": selected_opening,
        "source_sha256": runtime.source_sha256,
        "lifecycle_head_sha256": str(runtime.ledger.head_hash),
        "raw_evidence_head_sha256": _evidence_head(runtime),
        "lifecycle_records": len(getattr(runtime.ledger, "records", [])),
        "raw_evidence_records": len(getattr(runtime.evidence_store, "records", [])),
    }
    return _write_summary(runtime, f"collect-{selected_opening}", summary)


def collect_next(runtime: ObserverRuntime, *, now_ts_ms: int | None = None) -> dict[str, Any]:
    now = int(runtime.clock_ms() if now_ts_ms is None else now_ts_ms)
    opening = next_collectable_open(
        now,
        int(runtime.capture_policy.valid_market_open_after_epoch_seconds),
    )
    return _collect_opening(runtime, opening)


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


def _positive_int(name: str, value: int) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _pnl_total(resolution: dict[str, Any]) -> Decimal:
    value = resolution.get("pnl_total")
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid pnl_total in resolution: {value!r}") from exc


def collect_block(
    runtime: ObserverRuntime,
    *,
    markets: int,
    now_ts_ms: int | None = None,
    max_resolution_attempts: int = DEFAULT_RESOLUTION_ATTEMPTS,
    retry_delay_ms: int = DEFAULT_RETRY_DELAY_MS,
) -> dict[str, Any]:
    market_count = _positive_int("markets", markets)
    if market_count > MAX_BLOCK_MARKETS:
        raise ValueError(f"markets must be <= {MAX_BLOCK_MARKETS}")
    attempt_limit = _positive_int("max_resolution_attempts", max_resolution_attempts)
    retry_delay = _positive_int("retry_delay_ms", retry_delay_ms)

    now = int(runtime.clock_ms() if now_ts_ms is None else now_ts_ms)
    first_opening = next_collectable_open(
        now,
        int(runtime.capture_policy.valid_market_open_after_epoch_seconds),
    )
    openings = [first_opening + 300 * index for index in range(market_count)]

    # Capture every requested consecutive window before making any resolution
    # request. This keeps terminal latency from causing a missed +210s signal.
    captures = [_collect_opening(runtime, opening) for opening in openings]
    condition_ids = [str(capture["condition_id"]) for capture in captures]

    resolutions: list[dict[str, Any]] = []
    unresolved: list[str] = []
    attempts_by_condition: dict[str, int] = {}
    last_errors: dict[str, dict[str, str]] = {}

    for condition in condition_ids:
        resolved: dict[str, Any] | None = None
        for attempt in range(1, attempt_limit + 1):
            attempts_by_condition[condition] = attempt
            try:
                resolved = resolve_condition(runtime, condition)
                break
            except Exception as exc:  # fail closed and preserve the block evidence
                last_errors[condition] = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
                if attempt < attempt_limit:
                    runtime.sleep_until_ms(int(runtime.clock_ms()) + retry_delay)
        if resolved is None:
            unresolved.append(condition)
        else:
            resolutions.append(resolved)
            last_errors.pop(condition, None)

    decision_counts: dict[str, int] = {}
    hypothetical_fok_fills = 0
    for capture in captures:
        decision = str(capture.get("decision", "unknown"))
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        if capture.get("hypothetical_fok_fill") is True or decision == "hypothetical_fok_fill":
            hypothetical_fok_fills += 1

    total_pnl = sum((_pnl_total(resolution) for resolution in resolutions), Decimal("0"))
    summary = {
        "command": "collect-block",
        "status": "complete" if not unresolved else "unresolved",
        "markets_requested": market_count,
        "markets_collected": len(captures),
        "first_market_open_epoch_seconds": openings[0],
        "last_market_open_epoch_seconds": openings[-1],
        "market_open_epoch_seconds": openings,
        "condition_ids": condition_ids,
        "capture_decision_counts": dict(sorted(decision_counts.items())),
        "hypothetical_fok_fills": hypothetical_fok_fills,
        "conditions_resolved": len(resolutions),
        "unresolved_condition_ids": unresolved,
        "resolution_attempts_by_condition": attempts_by_condition,
        "last_resolution_errors": last_errors,
        "resolution_decision_counts": {
            decision: sum(1 for row in resolutions if str(row.get("decision")) == decision)
            for decision in sorted({str(row.get("decision")) for row in resolutions})
        },
        "prospective_pnl_total": format(total_pnl, "f"),
        "source_sha256": runtime.source_sha256,
        "lifecycle_head_sha256": str(runtime.ledger.head_hash),
        "raw_evidence_head_sha256": _evidence_head(runtime),
        "lifecycle_records": len(getattr(runtime.ledger, "records", [])),
        "raw_evidence_records": len(getattr(runtime.evidence_store, "records", [])),
        "credentials_used": 0,
        "authenticated_requests": 0,
        "order_submissions": 0,
        "live_submission": "physically_absent",
        "policy_changes": 0,
    }
    return _write_summary(
        runtime,
        f"block-{openings[0]}-{openings[-1]}",
        summary,
    )


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
    block = commands.add_parser(
        "collect-block",
        help="capture consecutive BTC windows, then resolve the captured queue",
    )
    block.add_argument("--markets", type=int, required=True)
    block.add_argument("--now-ms", type=int)
    block.add_argument(
        "--max-resolution-attempts",
        type=int,
        default=DEFAULT_RESOLUTION_ATTEMPTS,
    )
    block.add_argument("--retry-delay-ms", type=int, default=DEFAULT_RETRY_DELAY_MS)
    resolve = commands.add_parser("resolve", help="resolve one collected condition")
    resolve.add_argument("--condition-id", required=True)
    commands.add_parser("status", help="show ledger and unresolved-condition status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = build_runtime(args.project_root, args.state_dir)
    if args.command == "collect-next":
        output = collect_next(runtime, now_ts_ms=args.now_ms)
    elif args.command == "collect-block":
        output = collect_block(
            runtime,
            markets=args.markets,
            now_ts_ms=args.now_ms,
            max_resolution_attempts=args.max_resolution_attempts,
            retry_delay_ms=args.retry_delay_ms,
        )
    elif args.command == "resolve":
        output = resolve_condition(runtime, args.condition_id)
    elif args.command == "status":
        output = runtime_status(runtime)
    else:  # pragma: no cover
        raise RuntimeError(f"unsupported command: {args.command}")
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output.get("status") != "unresolved" else 2


if __name__ == "__main__":
    raise SystemExit(main())
