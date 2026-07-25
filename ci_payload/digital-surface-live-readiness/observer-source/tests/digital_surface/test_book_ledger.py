import json

import pytest

from research.digital_surface.book_ledger import BookLedgerIntegrityError, PublicBookLedger
from research.digital_surface.public_books import parse_public_order_book


def book():
    return parse_public_order_book({
        "market": "c1", "asset_id": "t1", "timestamp": "1", "hash": "h",
        "bids": [{"price": "0.40", "size": "10"}],
        "asks": [{"price": "0.50", "size": "10"}],
        "min_order_size": "1", "tick_size": "0.01", "neg_risk": False,
    })


def test_appends_and_reloads_book_hash_chain(tmp_path):
    path = tmp_path / "books.jsonl"
    ledger = PublicBookLedger(path)
    first = ledger.append(
        condition_id="c1", outcome="yes", observed_ts_ms=1, book=book(),
        policy_sha256="1"*64, source_sha256="2"*64, prospective_head_sha256="3"*64,
    )
    assert first["previous_hash"] == "0"*64
    reloaded = PublicBookLedger(path)
    assert reloaded.head_hash == first["record_hash"]
    assert len(reloaded.rows) == 1


def test_detects_book_ledger_tampering(tmp_path):
    path = tmp_path / "books.jsonl"
    ledger = PublicBookLedger(path)
    ledger.append(
        condition_id="c1", outcome="yes", observed_ts_ms=1, book=book(),
        policy_sha256="1"*64, source_sha256="2"*64, prospective_head_sha256="3"*64,
    )
    row = json.loads(path.read_text())
    row["book"]["asks"][0]["size"] = "999"
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(BookLedgerIntegrityError, match="record hash mismatch"):
        PublicBookLedger(path)
