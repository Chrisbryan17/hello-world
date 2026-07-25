from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from .public_books import BookLevel, PublicOrderBook


@dataclass(frozen=True, slots=True)
class BuyFokEstimate:
    filled: bool
    shares_requested: Decimal
    shares_available: Decimal
    gross_cost: Decimal
    average_price: Decimal | None
    worst_price: Decimal | None


@dataclass(frozen=True, slots=True)
class PairedFokEstimate:
    paired_crossable: bool
    orphanable_leg: str | None
    low: BuyFokEstimate
    high: BuyFokEstimate
    combined_gross_cost: Decimal | None
    transactionally_atomic: bool = False


def estimate_buy_fok(
    asks: tuple[BookLevel, ...],
    *,
    shares: Decimal,
    max_price: Decimal,
) -> BuyFokEstimate:
    requested = Decimal(shares)
    limit = Decimal(max_price)
    if requested <= 0:
        raise ValueError("shares must be positive")
    if not (Decimal("0") < limit < Decimal("1")):
        raise ValueError("max_price must be between zero and one")
    remaining = requested
    available = Decimal("0")
    gross_cost = Decimal("0")
    worst: Decimal | None = None
    for level in asks:
        if level.price > limit:
            break
        take = min(remaining, level.size)
        if take <= 0:
            continue
        available += take
        gross_cost += take * level.price
        worst = level.price
        remaining -= take
        if remaining == 0:
            break
    filled = remaining == 0
    if not filled:
        return BuyFokEstimate(
            filled=False,
            shares_requested=requested,
            shares_available=available,
            gross_cost=Decimal("0"),
            average_price=None,
            worst_price=None,
        )
    return BuyFokEstimate(
        filled=True,
        shares_requested=requested,
        shares_available=available,
        gross_cost=gross_cost,
        average_price=gross_cost / requested,
        worst_price=worst,
    )


def estimate_paired_fok(
    low_book: PublicOrderBook,
    high_book: PublicOrderBook,
    *,
    shares: Decimal,
    low_max_price: Decimal,
    high_max_price: Decimal,
) -> PairedFokEstimate:
    if low_book.token_id == high_book.token_id:
        raise ValueError("paired legs must use distinct tokens")
    low = estimate_buy_fok(low_book.asks, shares=shares, max_price=low_max_price)
    high = estimate_buy_fok(high_book.asks, shares=shares, max_price=high_max_price)
    orphanable_leg: str | None = None
    if low.filled != high.filled:
        orphanable_leg = "low_yes" if low.filled else "high_no"
    paired = low.filled and high.filled
    return PairedFokEstimate(
        paired_crossable=paired,
        orphanable_leg=orphanable_leg,
        low=low,
        high=high,
        combined_gross_cost=(low.gross_cost + high.gross_cost) if paired else None,
        transactionally_atomic=False,
    )


def estimate_pair_from_ledger_records(
    low_record: Mapping[str, Any],
    high_record: Mapping[str, Any],
    *,
    shares: Decimal,
    low_max_price: Decimal,
    high_max_price: Decimal,
) -> PairedFokEstimate:
    for field in ("observed_ts_ms", "policy_sha256", "source_sha256", "prospective_head_sha256"):
        if low_record.get(field) != high_record.get(field):
            raise ValueError(f"paired evidence mismatch for {field}")
    if str(low_record.get("outcome")) != "yes":
        raise ValueError("low record must be the YES leg")
    if str(high_record.get("outcome")) != "no":
        raise ValueError("high record must be the NO leg")
    if str(low_record.get("condition_id")) == str(high_record.get("condition_id")):
        raise ValueError("paired legs must use distinct conditions")
    return estimate_paired_fok(
        _book_from_record(low_record),
        _book_from_record(high_record),
        shares=shares,
        low_max_price=low_max_price,
        high_max_price=high_max_price,
    )


def _book_from_record(record: Mapping[str, Any]) -> PublicOrderBook:
    payload = record.get("book")
    if not isinstance(payload, Mapping):
        raise ValueError("ledger record is missing book data")
    def levels(name: str) -> tuple[BookLevel, ...]:
        raw = payload.get(name, [])
        if not isinstance(raw, list):
            raise ValueError(f"book {name} must be a list")
        return tuple(BookLevel(Decimal(str(row["price"])), Decimal(str(row["size"]))) for row in raw)
    last = payload.get("last_trade_price")
    return PublicOrderBook(
        condition_id=str(payload["condition_id"]),
        token_id=str(payload["token_id"]),
        timestamp=str(payload.get("timestamp") or ""),
        book_hash=str(payload.get("book_hash") or ""),
        bids=levels("bids"),
        asks=levels("asks"),
        min_order_size=Decimal(str(payload.get("min_order_size") or "0")),
        tick_size=Decimal(str(payload.get("tick_size") or "0.01")),
        neg_risk=bool(payload.get("neg_risk", False)),
        last_trade_price=None if last in (None, "") else Decimal(str(last)),
        payload_sha256=str(payload["payload_sha256"]),
    )
