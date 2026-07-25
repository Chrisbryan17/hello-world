from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import requests

REPO = "obadiaha/polymarket-crypto-5m-15m"
REVISION = "11793901f0ac89c5a6c51123a6ccd29a3aaf8f4c"
SOURCE_FILES = {
    "markets/all.parquet": 1_269_925,
    "resolutions/all.parquet": 1_264_422,
}
HORIZON_SECONDS = {"crypto_5m": 300, "crypto_15m": 900}
HORIZON_SLUG = {"crypto_5m": "5m", "crypto_15m": "15m"}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def download_pinned(data_dir: Path, relative: str, expected_size: int) -> Path:
    target = data_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    if target.exists() and target.stat().st_size == expected_size:
        return target
    url = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/{relative}"
    last_error: Exception | None = None
    for attempt in range(8):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > expected_size:
            partial.unlink(missing_ok=True)
            offset = 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        try:
            with requests.get(url, headers=headers, stream=True, timeout=300) as response:
                response.raise_for_status()
                mode = "ab" if offset and response.status_code == 206 else "wb"
                with partial.open(mode) as handle:
                    for block in response.iter_content(1 << 20):
                        if block:
                            handle.write(block)
            if partial.stat().st_size == expected_size:
                partial.replace(target)
                return target
            last_error = RuntimeError(
                f"incomplete {relative}: {partial.stat().st_size}/{expected_size}"
            )
        except Exception as exc:
            last_error = exc
        time.sleep(min(2**attempt, 15))
    raise RuntimeError(f"failed pinned download {relative}") from last_error


def normalize_source_tables(markets: pd.DataFrame, resolutions: pd.DataFrame, out: Path) -> pd.DataFrame:
    market_columns = markets.columns.astype(str).tolist()
    resolution_columns = resolutions.columns.astype(str).tolist()
    required_markets = {"condition_id", "asset", "market_type", "start_time"}
    required_resolutions = {"condition_id", "outcome"}
    missing_markets = sorted(required_markets - set(market_columns))
    missing_resolutions = sorted(required_resolutions - set(resolution_columns))
    if missing_markets or missing_resolutions:
        raise ValueError(
            f"missing columns: markets={missing_markets}, resolutions={missing_resolutions}"
        )

    work = markets.copy()
    work["condition_id"] = work["condition_id"].astype(str)
    work["asset"] = work["asset"].astype(str).str.upper()
    work["market_type"] = work["market_type"].astype(str)
    work["start_dt"] = pd.to_datetime(work["start_time"], utc=True, errors="coerce")
    work = work[
        (work["asset"] == "BTC")
        & work["market_type"].isin(HORIZON_SECONDS)
        & work["start_dt"].between(
            pd.Timestamp("2026-03-06", tz="UTC"),
            pd.Timestamp("2026-03-20", tz="UTC"),
            inclusive="left",
        )
    ].copy()

    resolved = resolutions[["condition_id", "outcome"]].copy()
    resolved["condition_id"] = resolved["condition_id"].astype(str)
    resolved["outcome"] = resolved["outcome"].astype(str).str.title()
    inconsistent_resolutions = (
        resolved.groupby("condition_id")["outcome"].nunique().loc[lambda series: series > 1]
    )
    if not inconsistent_resolutions.empty:
        raise ValueError(
            f"inconsistent duplicate resolutions: {inconsistent_resolutions.index[:20].tolist()}"
        )
    resolution_rows_before_dedup = len(resolved)
    resolved = resolved.drop_duplicates("condition_id", keep="last")

    work = work.merge(resolved, on="condition_id", how="inner", validate="many_to_one")
    joined_rows_before_dedup = len(work)
    work["start_epoch"] = (work["start_dt"].astype("int64") // 1_000_000_000).astype("int64")
    work["duration_s"] = work["market_type"].map(HORIZON_SECONDS).astype("int64")
    work["end_epoch"] = work["start_epoch"] + work["duration_s"]
    work["canonical_slug"] = [
        f"btc-updown-{HORIZON_SLUG[kind]}-{epoch}"
        for kind, epoch in zip(work["market_type"], work["start_epoch"])
    ]
    work["next_slug"] = [
        f"btc-updown-{HORIZON_SLUG[kind]}-{epoch}"
        for kind, epoch in zip(work["market_type"], work["end_epoch"])
    ]

    supplied_slug = work["slug"].astype(str) if "slug" in work else pd.Series("", index=work.index)
    supplied_epoch = pd.to_numeric(
        supplied_slug.str.extract(r"(\d{10})(?:\D*)$")[0], errors="coerce"
    )
    work["supplied_slug"] = supplied_slug
    work["supplied_slug_epoch"] = supplied_epoch
    work["supplied_slug_matches_boundary"] = supplied_epoch.eq(work["start_epoch"])

    duplicate_rows = work.duplicated(["market_type", "start_epoch"], keep=False)
    duplicate_consistency = (
        work.loc[duplicate_rows]
        .groupby(["market_type", "start_epoch"])
        .agg(outcomes=("outcome", "nunique"), conditions=("condition_id", "nunique"))
    )
    inconsistent_intervals = duplicate_consistency[duplicate_consistency["outcomes"] > 1]
    if not inconsistent_intervals.empty:
        raise ValueError(
            f"conflicting outcomes for duplicate intervals: {inconsistent_intervals.head(20).to_dict('index')}"
        )
    work = (
        work.sort_values(["market_type", "start_epoch", "condition_id"], kind="mergesort")
        .drop_duplicates(["market_type", "start_epoch"], keep="last")
        .reset_index(drop=True)
    )
    if work.empty:
        raise ValueError("no BTC 5m/15m contracts in immutable window")

    preflight = {
        "market_columns": market_columns,
        "resolution_columns": resolution_columns,
        "raw_market_rows": int(len(markets)),
        "raw_resolution_rows": int(len(resolutions)),
        "filtered_joined_rows_before_interval_dedup": int(joined_rows_before_dedup),
        "contracts_after_normalization": int(len(work)),
        "resolution_duplicate_rows": int(resolution_rows_before_dedup - len(resolved)),
        "duplicate_interval_groups": int(len(duplicate_consistency)),
        "slug_boundary_match_rate": float(work["supplied_slug_matches_boundary"].mean()),
        "by_horizon": work["market_type"].value_counts().sort_index().astype(int).to_dict(),
        "first_start": work["start_dt"].min().isoformat(),
        "last_start": work["start_dt"].max().isoformat(),
    }
    atomic_json(out / "preflight.json", preflight)
    print(json.dumps(preflight, indent=2), flush=True)
    return work


def parse_page(slug: str, payload: bytes, status: int, final_url: str) -> dict[str, Any]:
    raw_text = payload.decode("utf-8", "replace")
    normalized = html.unescape(raw_text).replace('\\"', '"').replace("\\u0024", "$")
    match = re.search(
        r'opening\s+"Price to Beat"\s+of\s+\$([0-9,]+(?:\.[0-9]+)?)',
        normalized,
        flags=re.IGNORECASE,
    )
    if match is None:
        match = re.search(
            r'Price to Beat.{0,120}?\$([0-9,]+(?:\.[0-9]+)?)',
            normalized,
            flags=re.IGNORECASE | re.DOTALL,
        )
    outcome_match = re.search(
        r'final outcome was\s+"(Up|Down)"', normalized, flags=re.IGNORECASE
    )
    if outcome_match is None:
        outcome_match = re.search(
            r'100%\s+for\s+"(Up|Down)"', normalized, flags=re.IGNORECASE
        )
    return {
        "slug": slug,
        "url": final_url,
        "status": int(status),
        "bytes": len(payload),
        "html_sha256": sha256_bytes(payload),
        "price_to_beat": float(match.group(1).replace(",", "")) if match else None,
        "page_outcome": outcome_match.group(1).title() if outcome_match else None,
        "fetched_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }


async def fetch_pages(slugs: list[str], cache_path: Path, concurrency: int = 10) -> dict[str, Any]:
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
        and existing[slug].get("html_sha256")
    }
    pending = [slug for slug in slugs if slug not in valid_cached]
    print(
        f"unique_pages={len(slugs)} cached={len(valid_cached)} pending={len(pending)}",
        flush=True,
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip",
        "Cache-Control": "no-cache",
    }
    limits = httpx.Limits(max_connections=concurrency + 2, max_keepalive_connections=concurrency)
    timeout = httpx.Timeout(45.0, connect=20.0)
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(
        http2=True,
        headers=headers,
        limits=limits,
        timeout=timeout,
        follow_redirects=True,
    ) as client:

        async def fetch_one(slug: str) -> tuple[str, dict[str, Any]]:
            url = f"https://polymarket.com/event/{slug}"
            last_error: Exception | None = None
            async with semaphore:
                for attempt in range(8):
                    try:
                        response = await client.get(url)
                        if response.status_code == 200:
                            row = parse_page(slug, response.content, response.status_code, str(response.url))
                            if row["price_to_beat"] is not None:
                                return slug, row
                            last_error = RuntimeError(f"Price to Beat missing for {slug}")
                        else:
                            last_error = RuntimeError(f"HTTP {response.status_code} for {slug}")
                    except Exception as exc:
                        last_error = exc
                    await asyncio.sleep(min(0.5 * (2**attempt), 12.0))
            return slug, {
                "slug": slug,
                "url": url,
                "status": None,
                "price_to_beat": None,
                "error": repr(last_error),
                "fetched_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            }

        for offset in range(0, len(pending), 40):
            batch = pending[offset : offset + 40]
            fetched = await asyncio.gather(*(fetch_one(slug) for slug in batch))
            for slug, row in fetched:
                existing[slug] = row
            atomic_json(cache_path, existing)
            completed = min(offset + len(batch), len(pending))
            failures = sum(
                1
                for slug in slugs
                if slug in existing and existing[slug].get("price_to_beat") is None
            )
            print(f"page_progress={completed}/{len(pending)} failures={failures}", flush=True)
    return existing


def write_checksums(out: Path) -> None:
    checksums = {
        path.name: sha256_file(path)
        for path in sorted(out.iterdir())
        if path.is_file() and path.name != "SHA256SUMS.json"
    }
    atomic_json(out / "SHA256SUMS.json", checksums)


def run(cache_dir: Path, out: Path) -> dict[str, Any]:
    data_dir = cache_dir / "data"
    page_cache = cache_dir / "pages.json"
    data_dir.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    source_paths = {
        name: download_pinned(data_dir, name, size) for name, size in SOURCE_FILES.items()
    }
    source_manifest = {
        "repo": REPO,
        "revision": REVISION,
        "files": {
            name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for name, path in source_paths.items()
        },
    }
    atomic_json(out / "immutable_source_manifest.json", source_manifest)

    markets = pd.read_parquet(source_paths["markets/all.parquet"])
    resolutions = pd.read_parquet(source_paths["resolutions/all.parquet"])
    work = normalize_source_tables(markets, resolutions, out)

    slugs = sorted(set(work["canonical_slug"]) | set(work["next_slug"]))
    snapshot = asyncio.run(fetch_pages(slugs, page_cache))
    page_rows = [snapshot.get(slug, {"slug": slug, "price_to_beat": None}) for slug in slugs]
    pages = pd.DataFrame(page_rows)
    pages["market_type"] = pages["slug"].str.extract(r"btc-updown-(5m|15m)-")[0].map(
        {"5m": "crypto_5m", "15m": "crypto_15m"}
    )
    pages["boundary_epoch"] = pd.to_numeric(
        pages["slug"].str.extract(r"(\d{10})(?:\D*)$")[0], errors="raise"
    ).astype("int64")
    pages = pages.sort_values(["market_type", "boundary_epoch"], kind="mergesort")
    pages.to_parquet(out / "chainlink_ptb_snapshot.parquet", index=False)
    pages.to_csv(out / "chainlink_ptb_snapshot.csv", index=False)

    ptb_map = pages.set_index("slug")["price_to_beat"].to_dict()
    outcome_map = pages.set_index("slug")["page_outcome"].to_dict()
    work["chainlink_open"] = work["canonical_slug"].map(ptb_map)
    work["chainlink_close"] = work["next_slug"].map(ptb_map)
    valid = work["chainlink_open"].notna() & work["chainlink_close"].notna()
    work["reconstructed_outcome"] = None
    work.loc[valid, "reconstructed_outcome"] = [
        "Up" if close >= open_ else "Down"
        for open_, close in zip(
            work.loc[valid, "chainlink_open"], work.loc[valid, "chainlink_close"]
        )
    ]
    work["recorded_outcome"] = work["outcome"].astype(str).str.title()
    work["page_outcome"] = work["canonical_slug"].map(outcome_map)
    work["direction_match"] = work["reconstructed_outcome"] == work["recorded_outcome"]
    work["page_outcome_match"] = work["page_outcome"] == work["recorded_outcome"]
    work["chainlink_delta"] = work["chainlink_close"] - work["chainlink_open"]

    five = pages.loc[
        pages["market_type"] == "crypto_5m", ["boundary_epoch", "price_to_beat"]
    ].rename(columns={"price_to_beat": "ptb_5m"})
    fifteen = pages.loc[
        pages["market_type"] == "crypto_15m", ["boundary_epoch", "price_to_beat"]
    ].rename(columns={"price_to_beat": "ptb_15m"})
    overlap = five.merge(fifteen, on="boundary_epoch", how="inner")
    overlap["absolute_difference"] = (overlap["ptb_5m"] - overlap["ptb_15m"]).abs()
    overlap["match_to_cent"] = overlap["absolute_difference"] < 0.005
    overlap.to_csv(out / "horizon_boundary_crosscheck.csv", index=False)

    coverage = float(valid.mean())
    agreement = float(work.loc[valid, "direction_match"].mean()) if valid.any() else 0.0
    page_outcome_valid = work["page_outcome"].notna()
    page_outcome_coverage = float(page_outcome_valid.mean())
    page_outcome_agreement = (
        float(work.loc[page_outcome_valid, "page_outcome_match"].mean())
        if page_outcome_valid.any()
        else 0.0
    )
    overlap_agreement = float(overlap["match_to_cent"].mean()) if len(overlap) else 0.0

    by_horizon: dict[str, Any] = {}
    for horizon, group in work.groupby("market_type"):
        group_valid = group["chainlink_open"].notna() & group["chainlink_close"].notna()
        by_horizon[horizon] = {
            "contracts": int(len(group)),
            "coverage": float(group_valid.mean()),
            "agreement": (
                float(group.loc[group_valid, "direction_match"].mean())
                if group_valid.any()
                else 0.0
            ),
        }

    decision = {
        "method": "official Polymarket historical Price-to-Beat boundary chaining",
        "resolution_source": "Chainlink BTC/USD data stream",
        "contracts": int(len(work)),
        "unique_pages": int(len(slugs)),
        "coverage": coverage,
        "direction_agreement": agreement,
        "required_agreement": 0.99,
        "page_outcome_coverage_audit": page_outcome_coverage,
        "page_outcome_agreement_audit": page_outcome_agreement,
        "shared_boundary_count": int(len(overlap)),
        "shared_boundary_agreement_to_cent": overlap_agreement,
        "by_horizon": by_horizon,
        "gate_passed": bool(
            coverage == 1.0
            and agreement >= 0.99
            and len(overlap) > 0
            and overlap_agreement == 1.0
        ),
        "signals_changed": False,
        "thresholds_changed": False,
        "execution_assumptions_changed": False,
        "validation_chronology_changed": False,
        "contracts_filtered": False,
    }
    atomic_json(out / "chainlink_source_decision.json", decision)
    work.to_parquet(out / "chainlink_resolution_audit.parquet", index=False)
    work.to_csv(out / "chainlink_resolution_audit.csv", index=False)
    work.loc[~work["direction_match"]].to_csv(
        out / "chainlink_direction_mismatches.csv", index=False
    )
    work.loc[page_outcome_valid & ~work["page_outcome_match"]].to_csv(
        out / "page_outcome_mismatches.csv", index=False
    )
    write_checksums(out)
    print(json.dumps(decision, indent=2), flush=True)
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache-dir", type=Path, default=Path(".cache/digital-surface-chainlink-audit")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("chainlink-audit"))
    args = parser.parse_args()
    decision = run(args.cache_dir, args.output_dir)
    return 0 if decision["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
