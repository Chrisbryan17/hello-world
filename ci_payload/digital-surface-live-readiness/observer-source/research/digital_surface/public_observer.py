from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from .diagnostic_filter import DiagnosticBloomFilter
from .market_discovery import GammaMarketRecord, discover_target_markets
from .prospective import ProspectiveLedger


GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"


def fetch_gamma_page(params: Mapping[str, object], *, timeout_seconds: float = 15.0) -> Sequence[Mapping[str, Any]]:
    """Fetch a public Gamma page. No credentials or authenticated endpoint is used."""
    import requests

    response = requests.get(GAMMA_MARKETS_URL, params=dict(params), timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("Gamma markets response must be a list")
    return payload


def _metadata(record: GammaMarketRecord) -> dict[str, object]:
    return {
        "duration_seconds": int(record.duration_seconds),
        "end_date": record.end_date,
        "no_token_id": record.no_token_id,
        "open_epoch_seconds": int(record.open_epoch_seconds),
        "question": record.question,
        "slug": record.slug,
        "tick_size": str(record.tick_size),
        "yes_token_id": record.yes_token_id,
    }


def observe_markets(
    markets: Sequence[GammaMarketRecord],
    *,
    ledger: ProspectiveLedger,
    observed_ts_ms: int,
    policy_sha256: str,
    source_sha256: str,
) -> dict[str, object]:
    counters = {
        "discovered": len(markets),
        "appended": 0,
        "skipped_diagnostic": 0,
        "skipped_existing": 0,
    }
    appended: list[str] = []
    for market in markets:
        condition_id = str(market.condition_id)
        if condition_id in ledger.diagnostic_market_ids:
            counters["skipped_diagnostic"] += 1
            continue
        if condition_id in ledger.market_ids:
            counters["skipped_existing"] += 1
            continue
        ledger.append_observation(
            market_id=condition_id,
            first_seen_ts_ms=int(observed_ts_ms),
            policy_sha256=policy_sha256,
            source_sha256=source_sha256,
            metadata=_metadata(market),
        )
        appended.append(condition_id)
        counters["appended"] += 1
    return {
        **counters,
        "appended_condition_ids": appended,
        "ledger_head_sha256": ledger.head_hash,
        "markets_total_in_ledger": len(ledger.market_ids),
        "observed_ts_ms": int(observed_ts_ms),
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Observe public BTC 5m/15m Polymarket markets without credentials")
    parser.add_argument("--diagnostic-filter", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=20)
    args = parser.parse_args(argv)

    bloom = DiagnosticBloomFilter.from_path(args.diagnostic_filter)
    policy_sha256 = _sha256_file(args.policy)
    source_sha256 = _sha256_file(args.source_manifest)
    ledger = ProspectiveLedger(args.ledger, diagnostic_market_ids=bloom)
    markets = discover_target_markets(
        lambda params: fetch_gamma_page(params),
        page_size=args.page_size,
        max_pages=args.max_pages,
    )
    summary = observe_markets(
        markets,
        ledger=ledger,
        observed_ts_ms=int(time.time() * 1000),
        policy_sha256=policy_sha256,
        source_sha256=source_sha256,
    )
    summary.update({
        "diagnostic_filter_source_sha256": bloom.source_sha256,
        "policy_sha256": policy_sha256,
        "source_sha256": source_sha256,
        "trading_mode": "observation_only",
        "authenticated_requests": 0,
        "order_submissions": 0,
    })
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
