from decimal import Decimal

import pytest

from research.digital_surface.public_books import BookLevel, parse_public_order_book
from research.digital_surface.shadow_fill import (
    estimate_buy_fok,
    estimate_pair_from_ledger_records,
    estimate_paired_fok,
)


def book(token, condition, asks):
    return parse_public_order_book({
        "market": condition,
        "asset_id": token,
        "timestamp": "1",
        "hash": f"h-{token}",
        "bids": [],
        "asks": [{"price": str(price), "size": str(size)} for price, size in asks],
        "min_order_size": "1",
        "tick_size": "0.01",
        "neg_risk": False,
    })


def record(item, outcome, observed=10, policy="1", source="2", prospective="3"):
    return {
        "condition_id": item.condition_id,
        "outcome": outcome,
        "observed_ts_ms": observed,
        "policy_sha256": policy * 64,
        "source_sha256": source * 64,
        "prospective_head_sha256": prospective * 64,
        "book": item.as_json(),
    }


def test_walks_multiple_ask_levels_under_frozen_limit():
    result = estimate_buy_fok(
        (BookLevel(Decimal("0.50"), Decimal("2")), BookLevel(Decimal("0.52"), Decimal("4"))),
        shares=Decimal("5"),
        max_price=Decimal("0.52"),
    )
    assert result.filled is True
    assert result.gross_cost == Decimal("2.56")
    assert result.average_price == Decimal("0.512")
    assert result.worst_price == Decimal("0.52")


def test_fok_estimate_discards_partial_cost_when_full_size_is_unavailable():
    result = estimate_buy_fok(
        (BookLevel(Decimal("0.50"), Decimal("2")),),
        shares=Decimal("5"),
        max_price=Decimal("0.50"),
    )
    assert result.filled is False
    assert result.shares_available == Decimal("2")
    assert result.gross_cost == Decimal("0")
    assert result.average_price is None


def test_pair_is_crossable_but_never_claimed_transactionally_atomic():
    low = book("yes-low", "low", [("0.50", "5")])
    high = book("no-high", "high", [("0.49", "5")])
    result = estimate_paired_fok(
        low, high, shares=Decimal("5"),
        low_max_price=Decimal("0.51"), high_max_price=Decimal("0.50"),
    )
    assert result.paired_crossable is True
    assert result.combined_gross_cost == Decimal("4.95")
    assert result.transactionally_atomic is False
    assert result.orphanable_leg is None


def test_pair_records_require_same_causal_observation_and_bound_digests():
    low = book("yes-low", "low", [("0.50", "5")])
    high = book("no-high", "high", [("0.49", "5")])
    with pytest.raises(ValueError, match="observed_ts_ms"):
        estimate_pair_from_ledger_records(
            record(low, "yes", observed=10),
            record(high, "no", observed=11),
            shares=Decimal("5"), low_max_price=Decimal("0.51"), high_max_price=Decimal("0.50"),
        )
