from __future__ import annotations

import argparse
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping


class ProspectiveAggregateError(RuntimeError):
    pass


class DuplicateMarketError(ProspectiveAggregateError):
    pass


class PolicyMismatchError(ProspectiveAggregateError):
    pass


class SafetyViolationError(ProspectiveAggregateError):
    pass


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProspectiveAggregateError(f"missing checkpoint file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProspectiveAggregateError(f"invalid checkpoint JSON: {path}") from exc


def _decimal(value: object | None, *, field: str) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProspectiveAggregateError(f"invalid decimal for {field}: {value!r}") from exc
    if not number.is_finite():
        raise ProspectiveAggregateError(f"non-finite decimal for {field}")
    return number


def _int(value: object, *, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ProspectiveAggregateError(f"invalid integer for {field}: {value!r}") from exc
    return number


def _source_sha256(verification: Mapping[str, Any], checkpoint: Path) -> str:
    run = verification.get("run")
    if not isinstance(run, Mapping):
        raise ProspectiveAggregateError(f"missing run metadata: {checkpoint}")
    source = str(run.get("runtime_source_sha256") or "")
    if len(source) != 64:
        raise ProspectiveAggregateError(f"invalid runtime source SHA-256: {checkpoint}")
    return source


def _policy_identity(
    verification: Mapping[str, Any],
    checkpoint: Path,
) -> tuple[str, str]:
    candidate = str(verification.get("candidate_policy_sha256") or "")
    capture = str(verification.get("capture_policy_sha256") or "")
    if len(candidate) != 64 or len(capture) != 64:
        raise ProspectiveAggregateError(f"invalid policy identity: {checkpoint}")
    return candidate, capture


def _check_safety(payload: Mapping[str, Any], checkpoint: Path) -> None:
    for field in (
        "credentials_used",
        "authenticated_requests",
        "order_submissions",
        "historical_admission_credit",
    ):
        if _int(payload.get(field, 0), field=f"{checkpoint.name}.{field}") != 0:
            raise SafetyViolationError(f"nonzero {field} in {checkpoint}")


def _normalize_market(
    *,
    checkpoint_name: str,
    source_sha256: str,
    opening: object,
    condition_id: object,
    decision: object,
    official_outcome: object | None,
    pnl_total: object | None,
) -> dict[str, Any]:
    opening_int = _int(opening, field="market_open_epoch_seconds")
    condition = str(condition_id or "")
    if opening_int < 0 or not condition:
        raise ProspectiveAggregateError(f"invalid market identity in {checkpoint_name}")
    decision_text = str(decision or "unknown")
    outcome = None if official_outcome is None else str(official_outcome)
    if outcome not in {None, "Up", "Down"}:
        raise ProspectiveAggregateError(f"invalid official outcome in {checkpoint_name}: {outcome}")
    pnl = _decimal(pnl_total, field=f"{checkpoint_name}.pnl_total")
    return {
        "checkpoint": checkpoint_name,
        "runtime_source_sha256": source_sha256,
        "market_open_epoch_seconds": opening_int,
        "condition_id": condition,
        "capture_decision": decision_text,
        "official_outcome": outcome,
        "hypothetical_fok_fill": decision_text == "hypothetical_fok_fill",
        "pnl_total": format(pnl, "f") if pnl_total is not None else None,
    }


def _load_one_shot(checkpoint: Path, source_sha256: str) -> list[dict[str, Any]]:
    payload = _read_json(checkpoint / "PROSPECTIVE_RUN.json")
    if not isinstance(payload, Mapping):
        raise ProspectiveAggregateError(f"one-shot checkpoint must be an object: {checkpoint}")
    _check_safety(payload, checkpoint)
    resolution = payload.get("resolution")
    terminal = payload.get("resolution_status") == "terminal" and isinstance(resolution, Mapping)
    official_outcome = resolution.get("official_outcome") if terminal else None
    pnl_total = resolution.get("pnl_total") if terminal else None
    return [
        _normalize_market(
            checkpoint_name=checkpoint.name,
            source_sha256=source_sha256,
            opening=payload.get("market_open_epoch_seconds"),
            condition_id=payload.get("condition_id"),
            decision=payload.get("capture_decision"),
            official_outcome=official_outcome,
            pnl_total=pnl_total,
        )
    ]


def _load_block(checkpoint: Path, source_sha256: str) -> list[dict[str, Any]]:
    summary = _read_json(checkpoint / "BLOCK_SUMMARY.json")
    raw_markets = _read_json(checkpoint / "MARKETS.json")
    if not isinstance(summary, Mapping) or not isinstance(raw_markets, list):
        raise ProspectiveAggregateError(f"invalid block checkpoint structure: {checkpoint}")
    _check_safety(summary, checkpoint)
    markets: list[dict[str, Any]] = []
    for row in raw_markets:
        if not isinstance(row, Mapping):
            raise ProspectiveAggregateError(f"market row must be an object: {checkpoint}")
        markets.append(
            _normalize_market(
                checkpoint_name=checkpoint.name,
                source_sha256=source_sha256,
                opening=row.get("market_open_epoch_seconds"),
                condition_id=row.get("condition_id"),
                decision=row.get("decision"),
                official_outcome=row.get("official_outcome"),
                pnl_total=row.get("pnl_total"),
            )
        )
    if _int(summary.get("markets_collected"), field="markets_collected") != len(markets):
        raise ProspectiveAggregateError(f"market count mismatch: {checkpoint}")
    computed_fills = sum(int(row["hypothetical_fok_fill"]) for row in markets)
    if _int(summary.get("hypothetical_fok_fills"), field="hypothetical_fok_fills") != computed_fills:
        raise ProspectiveAggregateError(f"fill count mismatch: {checkpoint}")
    computed_pnl = sum(
        (_decimal(row["pnl_total"], field="pnl_total") for row in markets),
        Decimal("0"),
    )
    summary_pnl = _decimal(summary.get("prospective_pnl_total"), field="prospective_pnl_total")
    if computed_pnl != summary_pnl:
        raise ProspectiveAggregateError(f"P&L mismatch: {checkpoint}")
    return markets


def _checkpoint_directories(root: Path) -> Iterable[Path]:
    yield from sorted(root.glob("prospective-run-v*"))
    yield from sorted(root.glob("prospective-block-v*"))


def build_aggregate(root: str | Path) -> dict[str, Any]:
    checkpoint_root = Path(root)
    candidate_sha: str | None = None
    capture_sha: str | None = None
    all_markets: list[dict[str, Any]] = []

    for checkpoint in _checkpoint_directories(checkpoint_root):
        if not checkpoint.is_dir():
            continue
        verification = _read_json(checkpoint / "VERIFICATION.json")
        if not isinstance(verification, Mapping):
            raise ProspectiveAggregateError(f"verification must be an object: {checkpoint}")
        current_candidate, current_capture = _policy_identity(verification, checkpoint)
        if candidate_sha is None:
            candidate_sha, capture_sha = current_candidate, current_capture
        elif (candidate_sha, capture_sha) != (current_candidate, current_capture):
            raise PolicyMismatchError(f"policy mismatch at {checkpoint}")
        source_sha = _source_sha256(verification, checkpoint)
        if checkpoint.name.startswith("prospective-run-v"):
            all_markets.extend(_load_one_shot(checkpoint, source_sha))
        elif checkpoint.name.startswith("prospective-block-v"):
            all_markets.extend(_load_block(checkpoint, source_sha))

    if candidate_sha is None or capture_sha is None:
        raise ProspectiveAggregateError("no prospective checkpoints found")

    by_opening: dict[int, dict[str, Any]] = {}
    by_condition: dict[str, dict[str, Any]] = {}
    for market in all_markets:
        opening = int(market["market_open_epoch_seconds"])
        condition = str(market["condition_id"])
        if opening in by_opening:
            raise DuplicateMarketError(f"duplicate market opening: {opening}")
        if condition in by_condition:
            raise DuplicateMarketError(f"duplicate condition ID: {condition}")
        by_opening[opening] = market
        by_condition[condition] = market

    markets = [by_opening[opening] for opening in sorted(by_opening)]
    observed = len(markets)
    official = sum(market["official_outcome"] in {"Up", "Down"} for market in markets)
    fills = sum(bool(market["hypothetical_fok_fill"]) for market in markets)
    pnl_total = sum(
        (_decimal(market["pnl_total"], field="pnl_total") for market in markets),
        Decimal("0"),
    )
    unresolved = sorted(
        market["condition_id"]
        for market in markets
        if market["official_outcome"] not in {"Up", "Down"}
    )
    decision_counts = Counter(str(market["capture_decision"]) for market in markets)
    outcome_counts = Counter(
        str(market["official_outcome"])
        for market in markets
        if market["official_outcome"] in {"Up", "Down"}
    )
    source_epochs = Counter(str(market["runtime_source_sha256"]) for market in markets)

    return {
        "candidate": "late_favorite_btc_only_v3_prospective_shadow",
        "candidate_policy_sha256": candidate_sha,
        "capture_policy_sha256": capture_sha,
        "prospective_markets_observed": observed,
        "official_outcomes_available": official,
        "official_outcome_coverage": 0.0 if observed == 0 else official / observed,
        "hypothetical_fok_fills": fills,
        "prospective_pnl_total": format(pnl_total, "f"),
        "unresolved_condition_ids": unresolved,
        "capture_decision_counts": dict(sorted(decision_counts.items())),
        "official_outcome_counts": dict(sorted(outcome_counts.items())),
        "runtime_source_epochs": dict(sorted(source_epochs.items())),
        "markets": markets,
        "safety": {
            "authenticated_requests": 0,
            "credentials_used": 0,
            "historical_admission_credit": 0,
            "order_submissions": 0,
        },
        "status": "prospective_shadow_only_not_admitted",
    }


def write_aggregate(root: str | Path, destination: str | Path) -> dict[str, Any]:
    report = build_aggregate(root)
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recompute BTC-only prospective evidence totals")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = write_aggregate(args.root, args.output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
