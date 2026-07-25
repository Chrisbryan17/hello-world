from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

import digital_surface_chainlink_audit_v3 as precision

GAMMA_SOURCE = "gamma_event_metadata.priceToBeat"
HTML_SOURCE = "polymarket_historical_5m_page.price_to_beat"
SHARED_SOURCE = "polymarket_historical_5m_page.same_chainlink_boundary"


def _parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    return []


def _resolved_outcome(event: dict[str, Any], slug: str) -> tuple[str | None, str, str]:
    markets = event.get("markets") or []
    market = next(
        (row for row in markets if str(row.get("slug")) == slug),
        markets[0] if markets else {},
    )
    outcomes = [str(value).title() for value in _parse_json_list(market.get("outcomes"))]
    prices = [float(value) for value in _parse_json_list(market.get("outcomePrices"))]
    page_outcome = None
    if outcomes and len(outcomes) == len(prices) and prices:
        winner_index = max(range(len(prices)), key=prices.__getitem__)
        if prices[winner_index] >= 0.999:
            page_outcome = outcomes[winner_index]
    return page_outcome, str(event.get("id") or ""), str(market.get("conditionId") or "")


def parse_gamma_event(slug: str, payload: bytes, status: int, final_url: str) -> dict[str, Any]:
    event = json.loads(payload)
    page_outcome, event_id, condition_id = _resolved_outcome(event, slug)
    metadata = event.get("eventMetadata") or {}
    price = metadata.get("priceToBeat")
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "slug": slug,
        "url": final_url,
        "status": int(status),
        "bytes": len(payload),
        "html_sha256": digest,
        "payload_sha256": digest,
        "price_to_beat": float(price) if price is not None else None,
        "page_outcome": page_outcome,
        "source": GAMMA_SOURCE if price is not None else "gamma_event_metadata.missing_priceToBeat",
        "event_id": event_id,
        "condition_id": condition_id,
        "fetched_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }


def parse_historical_price_to_beat(payload: bytes) -> float:
    raw = payload.decode("utf-8", "replace")
    normalized = html.unescape(raw).replace('\\"', '"').replace("\\u0024", "$")
    patterns = (
        r'opening\s+"Price to Beat"\s+of\s+\$([0-9,]+(?:\.[0-9]+)?)',
        r'live\s+"Price to Beat"\s*\(\$([0-9,]+(?:\.[0-9]+)?)\)',
        r'Price to Beat.{0,180}?\$([0-9,]+(?:\.[0-9]+)?)',
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return float(match.group(1).replace(",", ""))
    raise ValueError("official historical page Price to Beat missing")


def _epoch_and_horizon(slug: str) -> tuple[int, str]:
    match = re.fullmatch(r"btc-updown-(5m|15m)-(\d{10})", slug)
    if match is None:
        raise ValueError(f"unexpected canonical slug: {slug}")
    return int(match.group(2)), match.group(1)


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
        and existing[slug].get("status") == 200
        and isinstance(existing[slug].get("price_to_beat"), (int, float))
        and existing[slug].get("payload_sha256")
    }
    gamma_pending = [slug for slug in slugs if slug not in valid_cached]
    print(
        f"gamma_unique_events={len(slugs)} cached={len(valid_cached)} pending={len(gamma_pending)}",
        flush=True,
    )

    gamma_headers = {
        "User-Agent": "trading-tools-digital-surface-research/1.0",
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
    limits = httpx.Limits(max_connections=concurrency + 4, max_keepalive_connections=concurrency)
    timeout = httpx.Timeout(40.0, connect=15.0)
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(
        http2=True,
        headers=gamma_headers,
        limits=limits,
        timeout=timeout,
        follow_redirects=True,
    ) as client:

        async def fetch_gamma(slug: str) -> tuple[str, dict[str, Any]]:
            url = f"https://gamma-api.polymarket.com/events/slug/{slug}"
            last_error: Exception | None = None
            async with semaphore:
                for attempt in range(8):
                    try:
                        response = await client.get(url)
                        if response.status_code == 200:
                            return slug, parse_gamma_event(
                                slug, response.content, response.status_code, str(response.url)
                            )
                        last_error = RuntimeError(f"Gamma HTTP {response.status_code} for {slug}")
                    except Exception as exc:
                        last_error = exc
                    await asyncio.sleep(min(0.25 * (2**attempt), 8.0))
            return slug, {
                "slug": slug,
                "url": url,
                "status": None,
                "price_to_beat": None,
                "source": "gamma_event.error",
                "error": repr(last_error),
                "fetched_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            }

        for offset in range(0, len(gamma_pending), 200):
            batch = gamma_pending[offset : offset + 200]
            for slug, row in await asyncio.gather(*(fetch_gamma(slug) for slug in batch)):
                existing[slug] = row
            precision.prior.base.atomic_json(cache_path, existing)
            completed = min(offset + len(batch), len(gamma_pending))
            missing = sum(
                1 for slug in slugs if existing.get(slug, {}).get("price_to_beat") is None
            )
            print(f"gamma_progress={completed}/{len(gamma_pending)} missing={missing}", flush=True)

    missing_slugs = [slug for slug in slugs if existing.get(slug, {}).get("price_to_beat") is None]
    missing_epochs = sorted({_epoch_and_horizon(slug)[0] for slug in missing_slugs})
    fallback_slugs = [f"btc-updown-5m-{epoch}" for epoch in missing_epochs]
    print(
        f"gamma_missing={len(missing_slugs)} unique_boundary_fallbacks={len(fallback_slugs)}",
        flush=True,
    )

    if fallback_slugs:
        html_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip",
        }
        html_limits = httpx.Limits(max_connections=14, max_keepalive_connections=12)
        html_timeout = httpx.Timeout(60.0, connect=20.0)
        html_semaphore = asyncio.Semaphore(10)
        fallback_rows: dict[int, dict[str, Any]] = {}

        async with httpx.AsyncClient(
            http2=True,
            headers=html_headers,
            limits=html_limits,
            timeout=html_timeout,
            follow_redirects=True,
        ) as html_client:

            async def fetch_html(fallback_slug: str) -> tuple[int, dict[str, Any]]:
                epoch, _ = _epoch_and_horizon(fallback_slug)
                url = f"https://polymarket.com/event/{fallback_slug}"
                last_error: Exception | None = None
                async with html_semaphore:
                    for attempt in range(8):
                        try:
                            response = await html_client.get(url)
                            if response.status_code == 200:
                                price = parse_historical_price_to_beat(response.content)
                                digest = hashlib.sha256(response.content).hexdigest()
                                return epoch, {
                                    "price_to_beat": price,
                                    "fallback_url": str(response.url),
                                    "fallback_payload_sha256": digest,
                                    "fallback_bytes": len(response.content),
                                }
                            last_error = RuntimeError(
                                f"Polymarket HTML HTTP {response.status_code} for {fallback_slug}"
                            )
                        except Exception as exc:
                            last_error = exc
                        await asyncio.sleep(min(0.5 * (2**attempt), 12.0))
                return epoch, {"price_to_beat": None, "error": repr(last_error)}

            for offset in range(0, len(fallback_slugs), 30):
                batch = fallback_slugs[offset : offset + 30]
                for epoch, row in await asyncio.gather(*(fetch_html(slug) for slug in batch)):
                    fallback_rows[epoch] = row
                completed = min(offset + len(batch), len(fallback_slugs))
                failures = sum(row.get("price_to_beat") is None for row in fallback_rows.values())
                print(
                    f"historical_page_progress={completed}/{len(fallback_slugs)} failures={failures}",
                    flush=True,
                )

        for slug in missing_slugs:
            epoch, horizon = _epoch_and_horizon(slug)
            fallback = fallback_rows.get(epoch) or {}
            price = fallback.get("price_to_beat")
            original = existing.get(slug, {})
            original.update(
                {
                    "price_to_beat": price,
                    "source": HTML_SOURCE if horizon == "5m" else SHARED_SOURCE,
                    "fallback_slug": f"btc-updown-5m-{epoch}",
                    "fallback_url": fallback.get("fallback_url"),
                    "fallback_payload_sha256": fallback.get("fallback_payload_sha256"),
                    "fallback_bytes": fallback.get("fallback_bytes"),
                    "fallback_error": fallback.get("error"),
                    "status": 200 if price is not None else original.get("status"),
                    "payload_sha256": fallback.get("fallback_payload_sha256")
                    or original.get("payload_sha256"),
                    "html_sha256": fallback.get("fallback_payload_sha256")
                    or original.get("html_sha256"),
                }
            )
            existing[slug] = original
        precision.prior.base.atomic_json(cache_path, existing)

    remaining = [slug for slug in slugs if existing.get(slug, {}).get("price_to_beat") is None]
    print(f"final_missing_boundaries={len(remaining)}", flush=True)
    return existing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache-dir", type=Path, default=Path(".cache/digital-surface-chainlink-audit")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("chainlink-audit"))
    args = parser.parse_args()
    base = precision.prior.base
    base.normalize_source_tables = precision.normalize_source_tables
    base.fetch_pages = fetch_pages
    decision = base.run(args.cache_dir, args.output_dir)
    return 0 if decision["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
