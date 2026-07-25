from decimal import Decimal

import pytest

from research.digital_surface.public_books import (
    CLOB_BOOKS_URL,
    fetch_public_order_books,
    parse_public_order_book,
)


class Response:
    def __init__(self, payload):
        self.payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self.payload


def payload(token="t1", condition="c1"):
    return {
        "market": condition,
        "asset_id": token,
        "timestamp": "1234",
        "hash": "book-hash",
        "bids": [{"price": "0.44", "size": "2"}, {"price": "0.46", "size": "3"}],
        "asks": [{"price": "0.55", "size": "4"}, {"price": "0.52", "size": "5"}],
        "min_order_size": "1",
        "tick_size": "0.01",
        "neg_risk": False,
        "last_trade_price": "0.50",
    }


def test_parses_and_sorts_full_public_orderbook_depth():
    book = parse_public_order_book(payload(), expected_token_id="t1")
    assert book.best_bid.price == Decimal("0.46")
    assert book.best_bid.size == Decimal("3")
    assert book.best_ask.price == Decimal("0.52")
    assert [level.price for level in book.asks] == [Decimal("0.52"), Decimal("0.55")]
    assert len(book.payload_sha256) == 64


def test_rejects_asset_mismatch_and_invalid_levels():
    with pytest.raises(ValueError, match="asset mismatch"):
        parse_public_order_book(payload(), expected_token_id="other")
    broken = payload()
    broken["asks"] = [{"price": "1.2", "size": "1"}]
    with pytest.raises(ValueError, match="between zero and one"):
        parse_public_order_book(broken)


def test_batch_fetch_uses_only_public_books_endpoint_without_headers():
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response([payload("t1"), payload("t2", "c2")])
    books = fetch_public_order_books(["t1", "t2"], post=post)
    assert set(books) == {"t1", "t2"}
    assert calls[0][0] == CLOB_BOOKS_URL
    assert calls[0][1]["json"] == [{"token_id": "t1"}, {"token_id": "t2"}]
    assert "headers" not in calls[0][1]
