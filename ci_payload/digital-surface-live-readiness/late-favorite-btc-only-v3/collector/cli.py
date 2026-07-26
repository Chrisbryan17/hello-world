from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Callable, Sequence

from capture_policy import CaptureBoundLifecycleLedger, load_capture_policy
from late_favorite_v3 import load_frozen_policy
from public_collector import PublicHttpClient, RawEvidenceStore, SingleMarketCollector, next_collectable_open
from resolution import SingleMarketResolver


def _combined_source_sha256(root: Path) -> str:
    paths = [
        root / "source/late_favorite_v3.py",
        root / "source/capture_policy.py",
        root / "collector/public_collector.py",
        root / "collector/resolution.py",
    ]
    digest = hashlib.sha256()
    for path in paths:
        raw = path.read_bytes()
        digest.update(path.name.encode("utf-8") + b"\0" + raw)
    return digest.hexdigest()


def _load_policies(root: Path):
    source_sha256 = _combined_source_sha256(root)
    trading = load_frozen_policy(
        root / "CANDIDATE_SPEC.json",
        root / "FREEZE_MANIFEST.json",
        source_sha256=source_sha256,
    )
    capture = load_capture_policy(
        root / "CAPTURE_POLICY.json",
        root / "CAPTURE_FREEZE_MANIFEST.json",
    )
    return trading, capture


def sleep_until_ms(target_ts_ms: int) -> None:
    target = int(target_ts_ms)
    while True:
        remaining = target - time.time_ns() // 1_000_000
        if remaining <= 0:
            return
        time.sleep(min(remaining / 1000.0, 0.25))


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _runtime(
    *,
    root: Path,
    output_dir: Path,
    client: PublicHttpClient | None,
):
    trading, capture = _load_policies(root)
    resolved_client = client or PublicHttpClient()
    ledger = CaptureBoundLifecycleLedger(output_dir / "lifecycle.jsonl", trading, capture)
    evidence = RawEvidenceStore(output_dir / "raw")
    return trading, capture, resolved_client, ledger, evidence


def capture_once(
    *,
    root: str | Path,
    output_dir: str | Path,
    market_open_epoch_seconds: int | None = None,
    now_ms: Callable[[], int] | None = None,
    client: PublicHttpClient | None = None,
    sleep_until_ms: Callable[[int], None] = sleep_until_ms,
) -> dict[str, object]:
    root_path = Path(root).resolve()
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    trading, capture, resolved_client, ledger, evidence = _runtime(
        root=root_path,
        output_dir=output_path,
        client=client,
    )
    if market_open_epoch_seconds is None:
        clock = now_ms or (lambda: time.time_ns() // 1_000_000)
        market_open_epoch_seconds = next_collectable_open(
            int(clock()), capture.valid_market_open_after_epoch_seconds
        )
    opening = int(market_open_epoch_seconds)
    collector = SingleMarketCollector(
        client=resolved_client,
        evidence_store=evidence,
        ledger=ledger,
        trading_policy=trading,
        capture_policy=capture,
        sleep_until_ms=sleep_until_ms,
    )
    result = collector.capture(opening)
    _write_json_atomic(output_path / "last_capture.json", result)
    return dict(result)


def resolve_once(
    *,
    root: str | Path,
    output_dir: str | Path,
    condition_id: str,
    client: PublicHttpClient | None = None,
) -> dict[str, object]:
    root_path = Path(root).resolve()
    output_path = Path(output_dir).resolve()
    trading, capture, resolved_client, ledger, evidence = _runtime(
        root=root_path,
        output_dir=output_path,
        client=client,
    )
    resolver = SingleMarketResolver(
        client=resolved_client,
        evidence_store=evidence,
        ledger=ledger,
        trading_policy=trading,
        capture_policy=capture,
    )
    result = resolver.resolve(str(condition_id))
    _write_json_atomic(output_path / "last_resolution.json", result)
    return dict(result)


def build_parser() -> argparse.ArgumentParser:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Credential-free BTC-only v3 prospective observer"
    )
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture", help="Capture one eligible BTC 5-minute market")
    capture_parser.add_argument("--market-open", type=int)

    resolve_parser = subparsers.add_parser("resolve", help="Resolve one previously captured market")
    resolve_parser.add_argument("--condition-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = PublicHttpClient(timeout_seconds=args.timeout_seconds)
    if args.command == "capture":
        result = capture_once(
            root=args.root,
            output_dir=args.output_dir,
            market_open_epoch_seconds=args.market_open,
            client=client,
        )
    else:
        result = resolve_once(
            root=args.root,
            output_dir=args.output_dir,
            condition_id=args.condition_id,
            client=client,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
