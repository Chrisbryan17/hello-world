from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Sequence

from .book_ledger import PublicBookLedger
from .diagnostic_filter import DiagnosticBloomFilter
from .market_discovery import GammaMarketRecord, discover_target_markets
from .prospective import ProspectiveLedger
from .public_books import PublicOrderBook, fetch_public_order_books
from .public_observer import fetch_gamma_page


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observe_public_books(
    markets: Sequence[GammaMarketRecord],
    books: dict[str, PublicOrderBook],
    *,
    ledger: PublicBookLedger,
    prospective_market_ids: set[str],
    prospective_head_sha256: str,
    observed_ts_ms: int,
    policy_sha256: str,
    source_sha256: str,
) -> dict[str, object]:
    requested = 0
    appended = 0
    missing: list[str] = []
    skipped_unregistered = 0
    for market in markets:
        if market.condition_id not in prospective_market_ids:
            skipped_unregistered += 1
            continue
        for outcome, token_id in (("yes", market.yes_token_id), ("no", market.no_token_id)):
            requested += 1
            book = books.get(token_id)
            if book is None:
                missing.append(token_id)
                continue
            ledger.append(
                condition_id=market.condition_id,
                outcome=outcome,
                observed_ts_ms=observed_ts_ms,
                book=book,
                policy_sha256=policy_sha256,
                source_sha256=source_sha256,
                prospective_head_sha256=prospective_head_sha256,
            )
            appended += 1
    return {
        "markets_discovered": len(markets),
        "markets_registered": len(prospective_market_ids),
        "markets_skipped_unregistered": skipped_unregistered,
        "tokens_requested": requested,
        "books_received": len(books),
        "books_appended": appended,
        "missing_token_ids": sorted(missing),
        "book_ledger_head_sha256": ledger.head_hash,
        "book_observations_total": len(ledger.rows),
        "prospective_head_sha256": prospective_head_sha256,
        "observed_ts_ms": int(observed_ts_ms),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect public Polymarket orderbooks without credentials")
    parser.add_argument("--diagnostic-filter", type=Path, required=True)
    parser.add_argument("--prospective-ledger", type=Path, required=True)
    parser.add_argument("--book-ledger", type=Path, required=True)
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
    registered = [market for market in markets if market.condition_id in prospective.market_ids]
    token_ids = [token for market in registered for token in (market.yes_token_id, market.no_token_id)]
    books = fetch_public_order_books(token_ids)
    book_ledger = PublicBookLedger(args.book_ledger)
    summary = observe_public_books(
        markets,
        books,
        ledger=book_ledger,
        prospective_market_ids=prospective.market_ids,
        prospective_head_sha256=prospective.head_hash,
        observed_ts_ms=int(time.time() * 1000),
        policy_sha256=_sha256_file(args.policy),
        source_sha256=_sha256_file(args.source_manifest),
    )
    summary.update({
        "authenticated_requests": 0,
        "order_submissions": 0,
        "trading_mode": "observation_only",
        "public_books_endpoint": "https://clob.polymarket.com/books",
    })
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
