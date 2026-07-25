from decimal import Decimal

from research.digital_surface.book_ledger import PublicBookLedger
from research.digital_surface.market_discovery import GammaMarketRecord
from research.digital_surface.public_book_observer import observe_public_books
from research.digital_surface.public_books import parse_public_order_book


def market(condition="c1"):
    return GammaMarketRecord(
        condition_id=condition, slug="btc-updown-5m-1774450800", question="Bitcoin Up or Down",
        yes_token_id=f"yes-{condition}", no_token_id=f"no-{condition}", duration_seconds=300,
        open_epoch_seconds=1774450800, end_date="2026-07-25T15:00:00Z", tick_size=Decimal("0.01"),
    )


def book(token, condition):
    return parse_public_order_book({
        "market": condition, "asset_id": token, "timestamp": "1", "hash": f"h-{token}",
        "bids": [{"price": "0.40", "size": "10"}],
        "asks": [{"price": "0.50", "size": "10"}],
        "min_order_size": "1", "tick_size": "0.01", "neg_risk": False,
    })


def test_observer_records_both_registered_token_books_and_binds_prospective_head(tmp_path):
    item = market()
    books = {
        item.yes_token_id: book(item.yes_token_id, item.condition_id),
        item.no_token_id: book(item.no_token_id, item.condition_id),
    }
    ledger = PublicBookLedger(tmp_path / "books.jsonl")
    summary = observe_public_books(
        [item], books, ledger=ledger, prospective_market_ids={"c1"},
        prospective_head_sha256="3"*64, observed_ts_ms=10,
        policy_sha256="1"*64, source_sha256="2"*64,
    )
    assert summary["books_appended"] == 2
    assert summary["missing_token_ids"] == []
    assert {row["outcome"] for row in ledger.rows} == {"yes", "no"}
    assert all(row["prospective_head_sha256"] == "3"*64 for row in ledger.rows)


def test_observer_reports_missing_books_and_skips_unregistered_markets(tmp_path):
    registered = market("c1")
    unregistered = market("c2")
    books = {registered.yes_token_id: book(registered.yes_token_id, registered.condition_id)}
    ledger = PublicBookLedger(tmp_path / "books.jsonl")
    summary = observe_public_books(
        [registered, unregistered], books, ledger=ledger, prospective_market_ids={"c1"},
        prospective_head_sha256="3"*64, observed_ts_ms=10,
        policy_sha256="1"*64, source_sha256="2"*64,
    )
    assert summary["books_appended"] == 1
    assert summary["markets_skipped_unregistered"] == 1
    assert summary["missing_token_ids"] == [registered.no_token_id]
