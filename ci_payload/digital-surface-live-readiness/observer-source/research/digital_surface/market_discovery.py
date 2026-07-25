from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Mapping, Sequence


_TARGET_SLUG = re.compile(r"^btc-updown-(5m|15m)-(\d{10,13})$")


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _list(value: object, name: str) -> list[str]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, Sequence) or isinstance(parsed, (str, bytes)):
        raise ValueError(f"{name} must be a JSON array or sequence")
    return [str(item) for item in parsed]


@dataclass(frozen=True, slots=True)
class GammaMarketRecord:
    condition_id: str
    slug: str
    question: str
    yes_token_id: str
    no_token_id: str
    duration_seconds: int
    open_epoch_seconds: int
    end_date: str
    tick_size: Decimal


def parse_gamma_market(payload: Mapping[str, Any]) -> GammaMarketRecord:
    condition_id = str(payload.get("conditionId") or payload.get("condition_id") or "").strip()
    slug = str(payload.get("slug") or "").strip().lower()
    match = _TARGET_SLUG.fullmatch(slug)
    if not condition_id or match is None:
        raise ValueError("market is not a BTC 5m/15m up/down contract")
    token_ids = _list(payload.get("clobTokenIds") or payload.get("clob_token_ids"), "clobTokenIds")
    if len(token_ids) != 2 or not all(token_ids):
        raise ValueError("clobTokenIds must contain exactly two token IDs")
    outcomes = _list(payload.get("outcomes", '["Up","Down"]'), "outcomes")
    if len(outcomes) != 2:
        raise ValueError("outcomes must contain exactly two values")
    first = outcomes[0].strip().lower()
    second = outcomes[1].strip().lower()
    if first not in {"up", "yes"} or second not in {"down", "no"}:
        raise ValueError(f"unexpected outcome order: {outcomes}")
    epoch = int(match.group(2))
    if epoch >= 100_000_000_000:
        epoch //= 1000
    return GammaMarketRecord(
        condition_id=condition_id,
        slug=slug,
        question=str(payload.get("question") or ""),
        yes_token_id=token_ids[0],
        no_token_id=token_ids[1],
        duration_seconds=300 if match.group(1) == "5m" else 900,
        open_epoch_seconds=epoch,
        end_date=str(payload.get("endDate") or payload.get("end_date") or ""),
        tick_size=Decimal(str(payload.get("orderPriceMinTickSize") or payload.get("order_price_min_tick_size") or "0.01")),
    )


def _is_target(payload: Mapping[str, Any]) -> bool:
    slug = str(payload.get("slug") or "").strip().lower()
    return (
        _TARGET_SLUG.fullmatch(slug) is not None
        and _bool(payload.get("active", False))
        and not _bool(payload.get("closed", False))
        and _bool(payload.get("enableOrderBook", payload.get("enable_order_book", False)))
    )


def discover_target_markets(
    fetch_page: Callable[[dict[str, object]], Sequence[Mapping[str, Any]]],
    *,
    page_size: int = 100,
    max_pages: int = 20,
) -> list[GammaMarketRecord]:
    if page_size <= 0 or max_pages <= 0:
        raise ValueError("page_size and max_pages must be positive")
    records: dict[str, GammaMarketRecord] = {}
    for page in range(max_pages):
        offset = page * page_size
        payloads = list(fetch_page({
            "active": "true",
            "closed": "false",
            "limit": page_size,
            "offset": offset,
        }))
        for payload in payloads:
            if _is_target(payload):
                record = parse_gamma_market(payload)
                records.setdefault(record.condition_id, record)
        if len(payloads) < page_size:
            break
    return sorted(records.values(), key=lambda row: (row.open_epoch_seconds, row.duration_seconds, row.condition_id))
