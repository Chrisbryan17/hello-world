from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Mapping, Sequence


CLOB_BOOKS_URL = "https://clob.polymarket.com/books"


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: Decimal
    size: Decimal

    def as_json(self) -> dict[str, str]:
        return {"price": str(self.price), "size": str(self.size)}


@dataclass(frozen=True, slots=True)
class PublicOrderBook:
    condition_id: str
    token_id: str
    timestamp: str
    book_hash: str
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    min_order_size: Decimal
    tick_size: Decimal
    neg_risk: bool
    last_trade_price: Decimal | None
    payload_sha256: str

    @property
    def best_bid(self) -> BookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> BookLevel | None:
        return self.asks[0] if self.asks else None

    def as_json(self) -> dict[str, object]:
        return {
            "condition_id": self.condition_id,
            "token_id": self.token_id,
            "timestamp": self.timestamp,
            "book_hash": self.book_hash,
            "bids": [level.as_json() for level in self.bids],
            "asks": [level.as_json() for level in self.asks],
            "min_order_size": str(self.min_order_size),
            "tick_size": str(self.tick_size),
            "neg_risk": self.neg_risk,
            "last_trade_price": None if self.last_trade_price is None else str(self.last_trade_price),
            "payload_sha256": self.payload_sha256,
        }


def _levels(value: object, *, side: str) -> tuple[BookLevel, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{side} must be a sequence")
    levels: list[BookLevel] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise ValueError(f"{side} level must be an object")
        price = Decimal(str(row.get("price")))
        size = Decimal(str(row.get("size")))
        if not (Decimal("0") < price < Decimal("1")):
            raise ValueError(f"{side} price must be between zero and one")
        if size < 0:
            raise ValueError(f"{side} size must be non-negative")
        if size:
            levels.append(BookLevel(price=price, size=size))
    reverse = side == "bids"
    return tuple(sorted(levels, key=lambda level: level.price, reverse=reverse))


def parse_public_order_book(
    payload: Mapping[str, Any],
    *,
    expected_token_id: str | None = None,
) -> PublicOrderBook:
    token_id = str(payload.get("asset_id") or "").strip()
    condition_id = str(payload.get("market") or "").strip()
    if not token_id or not condition_id:
        raise ValueError("orderbook is missing market or asset_id")
    if expected_token_id is not None and token_id != str(expected_token_id):
        raise ValueError(f"orderbook asset mismatch: {token_id} != {expected_token_id}")
    raw_last = payload.get("last_trade_price")
    last_trade = None if raw_last in (None, "") else Decimal(str(raw_last))
    return PublicOrderBook(
        condition_id=condition_id,
        token_id=token_id,
        timestamp=str(payload.get("timestamp") or ""),
        book_hash=str(payload.get("hash") or ""),
        bids=_levels(payload.get("bids", []), side="bids"),
        asks=_levels(payload.get("asks", []), side="asks"),
        min_order_size=Decimal(str(payload.get("min_order_size") or "0")),
        tick_size=Decimal(str(payload.get("tick_size") or "0.01")),
        neg_risk=bool(payload.get("neg_risk", False)),
        last_trade_price=last_trade,
        payload_sha256=hashlib.sha256(_canonical_json(dict(payload))).hexdigest(),
    )


def fetch_public_order_books(
    token_ids: Sequence[str],
    *,
    post: Callable[..., Any] | None = None,
    timeout_seconds: float = 15.0,
    batch_size: int = 500,
) -> dict[str, PublicOrderBook]:
    if batch_size <= 0 or batch_size > 500:
        raise ValueError("batch_size must be between 1 and 500")
    ordered = list(dict.fromkeys(str(token).strip() for token in token_ids if str(token).strip()))
    if not ordered:
        return {}
    if post is None:
        import requests
        post = requests.post
    result: dict[str, PublicOrderBook] = {}
    for start in range(0, len(ordered), batch_size):
        batch = ordered[start : start + batch_size]
        response = post(
            CLOB_BOOKS_URL,
            json=[{"token_id": token} for token in batch],
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("public books response must be a list")
        expected = set(batch)
        for raw in payload:
            book = parse_public_order_book(raw)
            if book.token_id not in expected:
                raise ValueError(f"unexpected orderbook asset: {book.token_id}")
            if book.token_id in result:
                raise ValueError(f"duplicate orderbook asset: {book.token_id}")
            result[book.token_id] = book
    return result
