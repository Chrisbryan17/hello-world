from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Callable, Sequence

from .binance_public import BTCMarketState, BINANCE_MARKET_DATA_BASE, collect_btc_market_state
from .diagnostic_filter import DiagnosticBloomFilter
from .market_discovery import GammaMarketRecord, discover_target_markets
from .prospective import ProspectiveLedger
from .public_observer import fetch_gamma_page
from .spot_ledger import SpotStateLedger


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observe_public_btc_state(
    markets: Sequence[GammaMarketRecord],
    *,
    prospective_market_ids: set[str],
    prospective_head_sha256: str,
    ledger: SpotStateLedger,
    observed_ts_ms: int,
    policy_sha256: str,
    source_sha256: str,
    collect: Callable[..., BTCMarketState] = collect_btc_market_state,
) -> dict[str, object]:
    registered = [market for market in markets if market.condition_id in prospective_market_ids]
    boundaries = sorted({int(market.open_epoch_seconds) * 1_000 for market in registered})
    state = collect(boundaries, observed_ts_ms=int(observed_ts_ms))
    if set(state.strikes) != set(boundaries):
        raise ValueError(
            f"BTC state strike set does not match registered market boundaries: "
            f"{sorted(state.strikes)} != {boundaries}"
        )
    record = ledger.append(
        state,
        policy_sha256=policy_sha256,
        source_sha256=source_sha256,
        prospective_head_sha256=prospective_head_sha256,
    )
    return {
        "markets_discovered": len(markets),
        "markets_registered": len(registered),
        "markets_skipped_unregistered": len(markets) - len(registered),
        "strike_boundaries": boundaries,
        "spot": str(state.spot),
        "vol_30s": state.vol_30s,
        "vol_120s": state.vol_120s,
        "server_time_ms": state.server_time_ms,
        "observed_ts_ms": state.observed_ts_ms,
        "spot_state_head_sha256": ledger.head_hash,
        "spot_state_record_sha256": record["record_hash"],
        "spot_state_observations_total": len(ledger.rows),
        "prospective_head_sha256": prospective_head_sha256,
        "binance_market_data_base": BINANCE_MARKET_DATA_BASE,
        "authenticated_requests": 0,
        "order_submissions": 0,
        "trading_mode": "observation_only",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect public BTC market state without credentials")
    parser.add_argument("--diagnostic-filter", type=Path, required=True)
    parser.add_argument("--prospective-ledger", type=Path, required=True)
    parser.add_argument("--spot-ledger", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=20)
    args = parser.parse_args(argv)

    bloom = DiagnosticBloomFilter.from_path(args.diagnostic_filter)
    prospective = ProspectiveLedger(args.prospective_ledger, diagnostic_market_ids=bloom)
    markets = discover_target_markets(
        lambda params: fetch_gamma_page(params),
        page_size=args.page_size,
        max_pages=args.max_pages,
    )
    summary = observe_public_btc_state(
        markets,
        prospective_market_ids=prospective.market_ids,
        prospective_head_sha256=prospective.head_hash,
        ledger=SpotStateLedger(args.spot_ledger),
        observed_ts_ms=int(time.time() * 1_000),
        policy_sha256=_sha256_file(args.policy),
        source_sha256=_sha256_file(args.source_manifest),
    )
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
