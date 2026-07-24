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

BASELINE_ZIP_SHA256 = "e049437fcdeafa433dc46cfc61ffdddfdbad64ec13534d8bf07879637f55bcba"
HTML_SOURCE = "polymarket_historical_5m_page.price_to_beat"
SHARED_SOURCE = "polymarket_historical_5m_page.same_chainlink_boundary"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


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


async def fetch_missing_epochs(epochs: list[int], concurrency: int = 12) -> dict[int, dict[str, Any]]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip",
        "Cache-Control": "no-cache",
    }
    limits = httpx.Limits(max_connections=concurrency + 2, max_keepalive_connections=concurrency)
    timeout = httpx.Timeout(60.0, connect=20.0)
    semaphore = asyncio.Semaphore(concurrency)
    rows: dict[int, dict[str, Any]] = {}

    async with httpx.AsyncClient(
        http2=True,
        headers=headers,
        limits=limits,
        timeout=timeout,
        follow_redirects=True,
    ) as client:

        async def fetch_one(epoch: int) -> tuple[int, dict[str, Any]]:
            slug = f"btc-updown-5m-{epoch}"
            url = f"https://polymarket.com/event/{slug}"
            last_error: Exception | None = None
            async with semaphore:
                for attempt in range(8):
                    try:
                        response = await client.get(url)
                        if response.status_code == 200:
                            price = parse_historical_price_to_beat(response.content)
                            return epoch, {
                                "slug": slug,
                                "url": str(response.url),
                                "price_to_beat": price,
                                "payload_sha256": hashlib.sha256(response.content).hexdigest(),
                                "bytes": len(response.content),
                                "status": response.status_code,
                            }
                        last_error = RuntimeError(f"HTTP {response.status_code} for {slug}")
                    except Exception as exc:
                        last_error = exc
                    await asyncio.sleep(min(0.5 * (2**attempt), 12.0))
            return epoch, {
                "slug": slug,
                "url": url,
                "price_to_beat": None,
                "error": repr(last_error),
                "status": None,
            }

        for offset in range(0, len(epochs), 30):
            batch = epochs[offset : offset + 30]
            fetched = await asyncio.gather(*(fetch_one(epoch) for epoch in batch))
            rows.update(fetched)
            failures = sum(row.get("price_to_beat") is None for row in rows.values())
            print(
                f"historical_page_progress={min(offset + len(batch), len(epochs))}/{len(epochs)} "
                f"failures={failures}",
                flush=True,
            )
    return rows


def write_checksums(out: Path) -> None:
    checksums = {
        path.name: sha256_file(path)
        for path in sorted(out.iterdir())
        if path.is_file() and path.name not in {"SHA256SUMS.json", "audit.log"}
    }
    atomic_json(out / "SHA256SUMS.json", checksums)


def recover(baseline: Path, out: Path, baseline_zip_sha256: str) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    snapshot = pd.read_csv(baseline / "chainlink_ptb_snapshot.csv")
    audit = pd.read_csv(baseline / "chainlink_resolution_audit.csv")
    baseline_decision = json.loads((baseline / "chainlink_source_decision.json").read_text())
    source_manifest = json.loads((baseline / "immutable_source_manifest.json").read_text())
    preflight = json.loads((baseline / "preflight.json").read_text())

    missing = snapshot["price_to_beat"].isna()
    missing_epochs = sorted(snapshot.loc[missing, "boundary_epoch"].astype("int64").unique())
    print(
        f"baseline_rows={len(snapshot)} missing_rows={int(missing.sum())} "
        f"unique_missing_epochs={len(missing_epochs)}",
        flush=True,
    )
    recovered = asyncio.run(fetch_missing_epochs(missing_epochs))
    failures = {epoch: row for epoch, row in recovered.items() if row.get("price_to_beat") is None}
    if failures:
        atomic_json(out / "fallback_failures.json", failures)
        raise RuntimeError(f"failed to recover {len(failures)} official boundary pages")

    for index in snapshot.index[missing]:
        epoch = int(snapshot.at[index, "boundary_epoch"])
        horizon = str(snapshot.at[index, "market_type"])
        row = recovered[epoch]
        snapshot.at[index, "price_to_beat"] = float(row["price_to_beat"])
        snapshot.at[index, "source"] = HTML_SOURCE if horizon == "crypto_5m" else SHARED_SOURCE
        snapshot.at[index, "fallback_slug"] = row["slug"]
        snapshot.at[index, "fallback_url"] = row["url"]
        snapshot.at[index, "fallback_payload_sha256"] = row["payload_sha256"]
        snapshot.at[index, "fallback_bytes"] = int(row["bytes"])
        snapshot.at[index, "payload_sha256"] = row["payload_sha256"]
        snapshot.at[index, "html_sha256"] = row["payload_sha256"]
        snapshot.at[index, "status"] = int(row["status"])

    if snapshot["price_to_beat"].isna().any():
        raise AssertionError("recovered snapshot still has missing prices")

    snapshot = snapshot.sort_values(["market_type", "boundary_epoch"], kind="mergesort")
    snapshot.to_csv(out / "chainlink_ptb_snapshot.csv", index=False)
    snapshot.to_parquet(out / "chainlink_ptb_snapshot.parquet", index=False)

    ptb = snapshot.set_index("slug")["price_to_beat"].to_dict()
    audit["chainlink_open"] = audit["canonical_slug"].map(ptb)
    audit["chainlink_close"] = audit["next_slug"].map(ptb)
    valid = audit["chainlink_open"].notna() & audit["chainlink_close"].notna()
    audit["reconstructed_outcome"] = None
    audit.loc[valid, "reconstructed_outcome"] = [
        "Up" if close >= open_ else "Down"
        for open_, close in zip(audit.loc[valid, "chainlink_open"], audit.loc[valid, "chainlink_close"])
    ]
    audit["recorded_outcome"] = audit["recorded_outcome"].astype(str).str.title()
    audit["direction_match"] = audit["reconstructed_outcome"] == audit["recorded_outcome"]
    audit["chainlink_delta"] = audit["chainlink_close"] - audit["chainlink_open"]
    audit.to_csv(out / "chainlink_resolution_audit.csv", index=False)
    audit.to_parquet(out / "chainlink_resolution_audit.parquet", index=False)
    audit.loc[~audit["direction_match"]].to_csv(out / "chainlink_direction_mismatches.csv", index=False)

    five = snapshot.loc[
        snapshot["market_type"] == "crypto_5m", ["boundary_epoch", "price_to_beat"]
    ].rename(columns={"price_to_beat": "ptb_5m"})
    fifteen = snapshot.loc[
        snapshot["market_type"] == "crypto_15m", ["boundary_epoch", "price_to_beat"]
    ].rename(columns={"price_to_beat": "ptb_15m"})
    overlap = five.merge(fifteen, on="boundary_epoch", how="inner")
    overlap["absolute_difference"] = (overlap["ptb_5m"] - overlap["ptb_15m"]).abs()
    overlap["match_to_cent"] = overlap["absolute_difference"] < 0.005
    overlap.to_csv(out / "horizon_boundary_crosscheck.csv", index=False)

    coverage = float(valid.mean())
    direction_agreement = float(audit.loc[valid, "direction_match"].mean())
    shared_agreement = float(overlap["match_to_cent"].mean()) if len(overlap) else 0.0
    by_horizon: dict[str, Any] = {}
    for horizon, group in audit.groupby("market_type"):
        group_valid = group["chainlink_open"].notna() & group["chainlink_close"].notna()
        by_horizon[horizon] = {
            "contracts": int(len(group)),
            "coverage": float(group_valid.mean()),
            "agreement": float(group.loc[group_valid, "direction_match"].mean()),
        }

    decision = {
        **baseline_decision,
        "method": (
            "official Gamma eventMetadata.priceToBeat with official Polymarket historical "
            "5-minute page fallback for the March 9 metadata gap"
        ),
        "coverage": coverage,
        "direction_agreement": direction_agreement,
        "shared_boundary_count": int(len(overlap)),
        "shared_boundary_agreement_to_cent": shared_agreement,
        "by_horizon": by_horizon,
        "gamma_metadata_boundaries": int(snapshot["source"].eq("gamma_event_metadata.priceToBeat").sum()),
        "historical_page_boundaries": int(snapshot["source"].eq(HTML_SOURCE).sum()),
        "shared_horizon_fallback_boundaries": int(snapshot["source"].eq(SHARED_SOURCE).sum()),
        "baseline_artifact_sha256": baseline_zip_sha256,
        "baseline_artifact_expected_sha256": BASELINE_ZIP_SHA256,
        "gate_passed": bool(
            baseline_zip_sha256 == BASELINE_ZIP_SHA256
            and coverage == 1.0
            and direction_agreement >= float(baseline_decision["required_agreement"])
            and len(overlap) > 0
            and shared_agreement == 1.0
        ),
        "contracts_filtered": False,
        "signals_changed": False,
        "thresholds_changed": False,
        "execution_assumptions_changed": False,
        "validation_chronology_changed": False,
    }
    atomic_json(out / "chainlink_source_decision.json", decision)
    atomic_json(out / "immutable_source_manifest.json", source_manifest)
    atomic_json(out / "preflight.json", preflight)
    atomic_json(
        out / "gap_recovery_provenance.json",
        {
            "baseline_artifact_sha256": baseline_zip_sha256,
            "baseline_artifact_expected_sha256": BASELINE_ZIP_SHA256,
            "missing_boundary_rows": int(missing.sum()),
            "unique_missing_epochs": len(missing_epochs),
            "fallback_pages": {
                str(epoch): row for epoch, row in sorted(recovered.items())
            },
        },
    )
    write_checksums(out)
    print(json.dumps(decision, indent=2), flush=True)
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline-zip", type=Path, required=True)
    args = parser.parse_args()
    digest = sha256_file(args.baseline_zip)
    if digest != BASELINE_ZIP_SHA256:
        raise RuntimeError(f"baseline artifact hash mismatch: {digest}")
    decision = recover(args.baseline_dir, args.output_dir, digest)
    return 0 if decision["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
