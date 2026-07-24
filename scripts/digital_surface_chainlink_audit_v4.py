from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

import digital_surface_chainlink_audit_v3 as precision


def _parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    return []


def parse_gamma_event(
    slug: str,
    payload: bytes,
    status: int,
    final_url: str,
) -> dict[str, Any]:
    data = json.loads(payload)
    metadata = data.get("eventMetadata") or {}
    price = metadata.get("priceToBeat")
    if price is None:
        raise ValueError(f"Gamma eventMetadata.priceToBeat missing for {slug}")
    markets = data.get("markets") or []
    market = next(
        (row for row in markets if str(row.get("slug")) == slug),
        markets[0] if markets else {},
    )
    outcomes = [
        str(value).title()
        for value in _parse_json_list(market.get("outcomes"))
    ]
    prices = [
        float(value)
        for value in _parse_json_list(market.get("outcomePrices"))
    ]
    page_outcome = None
    if outcomes and len(outcomes) == len(prices) and prices:
        winner_index = max(range(len(prices)), key=prices.__getitem__)
        if prices[winner_index] >= 0.999:
            page_outcome = outcomes[winner_index]
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    return {
        "slug": slug,
        "url": final_url,
        "status": int(status),
        "bytes": len(payload),
        "html_sha256": payload_sha256,
        "payload_sha256": payload_sha256,
        "price_to_beat": float(price),
        "page_outcome": page_outcome,
        "source": "gamma_event_metadata.priceToBeat",
        "event_id": str(data.get("id") or ""),
        "condition_id": str(market.get("conditionId") or ""),
        "fetched_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }


async def fetch_pages(
    slugs: list[str],
    cache_path: Path,
    concurrency: int = 40,
) -> dict[str, Any]:
    existing: dict[str, Any] = {}
    if cache_path.exists():
        try:
            existing = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            existing = {}
    valid_cached = {
        slug
        for slug in slugs
        if slug in existing
        and existing[slug].get("source")
        == "gamma_event_metadata.priceToBeat"
        and existing[slug].get("status") == 200
        and isinstance(existing[slug].get("price_to_beat"), (int, float))
        and existing[slug].get("payload_sha256")
    }
    pending = [slug for slug in slugs if slug not in valid_cached]
    print(
        f"gamma_unique_events={len(slugs)} "
        f"cached={len(valid_cached)} pending={len(pending)}",
        flush=True,
    )
    headers = {
        "User-Agent": "trading-tools-digital-surface-research/1.0",
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
    limits = httpx.Limits(
        max_connections=concurrency + 4,
        max_keepalive_connections=concurrency,
    )
    timeout = httpx.Timeout(35.0, connect=15.0)
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(
        http2=True,
        headers=headers,
        limits=limits,
        timeout=timeout,
        follow_redirects=True,
    ) as client:

        async def fetch_one(slug: str) -> tuple[str, dict[str, Any]]:
            url = f"https://gamma-api.polymarket.com/events/slug/{slug}"
            last_error: Exception | None = None
            async with semaphore:
                for attempt in range(8):
                    try:
                        response = await client.get(url)
                        if response.status_code == 200:
                            row = parse_gamma_event(
                                slug,
                                response.content,
                                response.status_code,
                                str(response.url),
                            )
                            return slug, row
                        last_error = RuntimeError(
                            f"Gamma HTTP {response.status_code} for {slug}"
                        )
                    except Exception as exc:
                        last_error = exc
                    await asyncio.sleep(min(0.25 * (2**attempt), 8.0))
            return slug, {
                "slug": slug,
                "url": url,
                "status": None,
                "price_to_beat": None,
                "source": "gamma_event_metadata.priceToBeat",
                "error": repr(last_error),
                "fetched_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            }

        for offset in range(0, len(pending), 200):
            batch = pending[offset : offset + 200]
            fetched = await asyncio.gather(
                *(fetch_one(slug) for slug in batch)
            )
            for slug, row in fetched:
                existing[slug] = row
            precision.prior.base.atomic_json(cache_path, existing)
            completed = min(offset + len(batch), len(pending))
            failures = sum(
                1
                for slug in slugs
                if slug in existing
                and existing[slug].get("price_to_beat") is None
            )
            print(
                f"gamma_progress={completed}/{len(pending)} "
                f"failures={failures}",
                flush=True,
            )
    return existing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".cache/digital-surface-chainlink-audit"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("chainlink-audit"),
    )
    args = parser.parse_args()
    base = precision.prior.base
    base.normalize_source_tables = precision.normalize_source_tables
    base.fetch_pages = fetch_pages
    decision = base.run(args.cache_dir, args.output_dir)
    return 0 if decision["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
