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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    return []


def gamma_outcome(payload: bytes, slug: str) -> tuple[str, str, str]:
    event = json.loads(payload)
    markets = event.get("markets") or []
    market = next(
        (row for row in markets if str(row.get("slug")) == slug),
        markets[0] if markets else {},
    )
    outcomes = [str(value).title() for value in parse_json_list(market.get("outcomes"))]
    prices = [float(value) for value in parse_json_list(market.get("outcomePrices"))]
    if not outcomes or len(outcomes) != len(prices):
        raise ValueError(f"Gamma outcome vector unavailable for {slug}")
    winner = max(range(len(prices)), key=prices.__getitem__)
    if prices[winner] < 0.999:
        raise ValueError(f"Gamma market is not terminal for {slug}: {prices}")
    outcome = outcomes[winner]
    if outcome not in {"Up", "Down"}:
        raise ValueError(f"unexpected Gamma outcome for {slug}: {outcome}")
    return outcome, str(event.get("id") or ""), str(market.get("conditionId") or "")


def html_outcome(payload: bytes, slug: str) -> str:
    text = html.unescape(payload.decode("utf-8", "replace")).replace('\\"', '"')
    patterns = (
        r'final outcome was\s+"(Up|Down)"',
        r'100%\s+for\s+"(Up|Down)"',
        r'has closed and resolved[^.]{0,160}?"(Up|Down)"',
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).title()
    raise ValueError(f"official historical outcome missing for {slug}")


async def recover_missing(rows: pd.DataFrame, concurrency: int = 6) -> dict[str, dict[str, Any]]:
    slugs = rows["canonical_slug"].astype(str).tolist()
    headers = {
        "User-Agent": "trading-tools-digital-surface-research/1.0",
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
    limits = httpx.Limits(max_connections=concurrency + 2, max_keepalive_connections=concurrency)
    timeout = httpx.Timeout(45.0, connect=20.0)
    semaphore = asyncio.Semaphore(concurrency)
    recovered: dict[str, dict[str, Any]] = {}

    async with httpx.AsyncClient(
        http2=True,
        headers=headers,
        limits=limits,
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        async def fetch_gamma(slug: str) -> tuple[str, dict[str, Any]]:
            url = f"https://gamma-api.polymarket.com/events/slug/{slug}"
            last: Exception | None = None
            async with semaphore:
                for attempt in range(10):
                    try:
                        response = await client.get(url)
                        if response.status_code == 200:
                            outcome, event_id, condition_id = gamma_outcome(response.content, slug)
                            return slug, {
                                "official_outcome": outcome,
                                "verification_source": "gamma_terminal_outcome",
                                "verification_url": str(response.url),
                                "payload_sha256": hashlib.sha256(response.content).hexdigest(),
                                "payload_bytes": len(response.content),
                                "event_id": event_id,
                                "gamma_condition_id": condition_id,
                                "status": response.status_code,
                            }
                        last = RuntimeError(f"Gamma HTTP {response.status_code}")
                    except Exception as exc:
                        last = exc
                    await asyncio.sleep(min(0.5 * (2**attempt), 15.0))
            return slug, {"gamma_error": repr(last)}

        for offset in range(0, len(slugs), 30):
            batch = slugs[offset : offset + 30]
            for slug, result in await asyncio.gather(*(fetch_gamma(slug) for slug in batch)):
                recovered[slug] = result
            print(f"gamma_outcome_progress={min(offset+len(batch),len(slugs))}/{len(slugs)}", flush=True)
            await asyncio.sleep(1.0)

    fallback = [slug for slug in slugs if "official_outcome" not in recovered.get(slug, {})]
    print(f"gamma_outcome_failures={len(fallback)}", flush=True)
    if fallback:
        html_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip",
        }
        html_semaphore = asyncio.Semaphore(10)
        async with httpx.AsyncClient(
            http2=True,
            headers=html_headers,
            limits=httpx.Limits(max_connections=12, max_keepalive_connections=10),
            timeout=httpx.Timeout(60.0, connect=20.0),
            follow_redirects=True,
        ) as client:
            async def fetch_html(slug: str) -> tuple[str, dict[str, Any]]:
                url = f"https://polymarket.com/event/{slug}"
                last: Exception | None = None
                async with html_semaphore:
                    for attempt in range(8):
                        try:
                            response = await client.get(url)
                            if response.status_code == 200:
                                outcome = html_outcome(response.content, slug)
                                prior = recovered.get(slug, {})
                                return slug, {
                                    **prior,
                                    "official_outcome": outcome,
                                    "verification_source": "polymarket_historical_page_terminal_outcome",
                                    "verification_url": str(response.url),
                                    "payload_sha256": hashlib.sha256(response.content).hexdigest(),
                                    "payload_bytes": len(response.content),
                                    "status": response.status_code,
                                }
                            last = RuntimeError(f"HTML HTTP {response.status_code}")
                        except Exception as exc:
                            last = exc
                        await asyncio.sleep(min(0.5 * (2**attempt), 12.0))
                return slug, {**recovered.get(slug, {}), "html_error": repr(last)}

            for offset in range(0, len(fallback), 30):
                batch = fallback[offset : offset + 30]
                for slug, result in await asyncio.gather(*(fetch_html(slug) for slug in batch)):
                    recovered[slug] = result
                print(f"html_outcome_progress={min(offset+len(batch),len(fallback))}/{len(fallback)}", flush=True)
    return recovered


def build_snapshot(baseline: Path, baseline_zip: Path, output: Path) -> dict[str, Any]:
    digest = sha256_file(baseline_zip)
    if digest != BASELINE_ZIP_SHA256:
        raise RuntimeError(f"baseline artifact SHA-256 mismatch: {digest}")
    audit = pd.read_csv(baseline / "chainlink_resolution_audit.csv")
    required = {"condition_id", "canonical_slug", "recorded_outcome", "page_outcome"}
    missing = sorted(required - set(audit.columns))
    if missing:
        raise ValueError(f"baseline audit missing columns: {missing}")
    audit["recorded_outcome"] = audit["recorded_outcome"].astype(str).str.title()
    audit["official_outcome"] = audit["page_outcome"].where(audit["page_outcome"].notna(), None)
    audit["verification_source"] = audit["official_outcome"].map(
        lambda value: "gamma_terminal_outcome" if value in {"Up", "Down"} else None
    )
    audit["verification_url"] = None
    audit["payload_sha256"] = None
    audit["payload_bytes"] = None
    audit["event_id"] = None
    audit["gamma_condition_id"] = None
    missing_rows = audit[audit["official_outcome"].isna()].copy()
    recovered = asyncio.run(recover_missing(missing_rows))
    for index in audit.index[audit["official_outcome"].isna()]:
        slug = str(audit.at[index, "canonical_slug"])
        result = recovered.get(slug, {})
        for column in (
            "official_outcome", "verification_source", "verification_url",
            "payload_sha256", "payload_bytes", "event_id", "gamma_condition_id",
        ):
            audit.at[index, column] = result.get(column)
    unresolved = audit[audit["official_outcome"].isna()]
    if not unresolved.empty:
        atomic_json(output / "unresolved_outcomes.json", {
            str(row.canonical_slug): recovered.get(str(row.canonical_slug), {})
            for row in unresolved.itertuples()
        })
        raise RuntimeError(f"failed to recover {len(unresolved)} official outcomes")
    audit["official_outcome"] = audit["official_outcome"].astype(str).str.title()
    audit["outcome_match"] = audit["official_outcome"] == audit["recorded_outcome"]
    snapshot = audit[[
        "condition_id", "canonical_slug", "recorded_outcome", "official_outcome",
        "outcome_match", "verification_source", "verification_url", "payload_sha256",
        "payload_bytes", "event_id", "gamma_condition_id",
    ]].copy()
    if snapshot["condition_id"].duplicated().any():
        raise ValueError("official outcome snapshot contains duplicate condition IDs")
    coverage = float(snapshot["official_outcome"].notna().mean())
    agreement = float(snapshot["outcome_match"].mean())
    decision = {
        "method": "official Polymarket terminal outcome verification",
        "contracts": int(len(snapshot)),
        "coverage": coverage,
        "agreement": agreement,
        "required_agreement": 0.99,
        "gate_passed": bool(coverage == 1.0 and agreement >= 0.99),
        "gamma_verified": int(snapshot["verification_source"].eq("gamma_terminal_outcome").sum()),
        "historical_page_verified": int(snapshot["verification_source"].eq("polymarket_historical_page_terminal_outcome").sum()),
        "baseline_artifact_sha256": digest,
        "contracts_filtered": False,
        "signals_changed": False,
        "thresholds_changed": False,
        "execution_assumptions_changed": False,
        "validation_chronology_changed": False,
        "strike_source": "causal Binance one-minute opening price (unchanged)",
        "resolution_source": "Chainlink BTC/USD via official Polymarket terminal outcome",
    }
    output.mkdir(parents=True, exist_ok=True)
    snapshot.to_csv(output / "official_outcome_snapshot.csv", index=False)
    snapshot.to_parquet(output / "official_outcome_snapshot.parquet", index=False)
    atomic_json(output / "official_outcome_decision.json", decision)
    atomic_json(output / "recovery_details.json", recovered)
    checksums = {
        path.name: sha256_file(path)
        for path in sorted(output.iterdir())
        if path.is_file() and path.name != "SHA256SUMS.json"
    }
    atomic_json(output / "SHA256SUMS.json", checksums)
    print(json.dumps(decision, indent=2), flush=True)
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--baseline-zip", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    decision = build_snapshot(args.baseline_dir, args.baseline_zip, args.output_dir)
    return 0 if decision["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
