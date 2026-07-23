#!/usr/bin/env python3
"""Measure whether the independent corpus supports the promised 1–3s entry latency."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from huggingface_hub import snapshot_download

REPO_ID = "kinzikdza/polymarket-updown-microstructure"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    out = Path("independent-minute4-v2-diagnostic")
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(".cache/kinzik-v2-timing")
    cache.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=REPO_ID,
        repo_type="dataset",
        local_dir=str(cache),
        allow_patterns=["parquet/slots.parquet", "parquet/book_snapshots.parquet"],
    )
    slots = pd.read_parquet(next(cache.rglob("slots.parquet")))
    books = pd.read_parquet(next(cache.rglob("book_snapshots.parquet")))

    slots["coin_norm"] = slots["coin"].astype(str).str.strip().str.upper()
    slots["duration_norm"] = slots["duration"].astype(str).str.strip().str.lower()
    btc = (
        slots.loc[slots["coin_norm"].eq("BTC") & slots["duration_norm"].eq("5m")]
        .drop_duplicates("condition_id")
        .set_index("condition_id")
    )
    books = books.loc[books["condition_id"].isin(btc.index)].copy()
    numeric = [
        "ts_ms", "secs_to_close", "yes_bid", "yes_ask", "yes_bid_size",
        "yes_ask_size", "no_bid", "no_ask", "no_bid_size", "no_ask_size",
    ]
    for column in numeric:
        books[column] = pd.to_numeric(books[column], errors="coerce")
    sane = (
        books["yes_bid"].gt(0)
        & books["yes_ask"].lt(1)
        & books["no_bid"].gt(0)
        & books["no_ask"].lt(1)
        & books["yes_bid"].le(books["yes_ask"])
        & books["no_bid"].le(books["no_ask"])
    )
    sane_books = books.loc[sane].sort_values(["condition_id", "ts_ms"])

    counts: Counter[str] = Counter()
    first_delay_ms: Counter[str] = Counter()
    all_positive_delay_ms: Counter[str] = Counter()
    signal_secs: Counter[str] = Counter()
    capture_patterns: Counter[str] = Counter()
    pattern_market_counts: Counter[str] = Counter()
    pattern_original_entries: Counter[str] = Counter()
    interval_ms: Counter[str] = Counter()
    examples: list[dict[str, object]] = []
    entry_delay_values: list[int] = []

    grouped = {cid: group for cid, group in sane_books.groupby("condition_id", sort=False)}
    for cid, slot in btc.iterrows():
        group = grouped.get(cid)
        if group is None or group.empty:
            counts["missing_sane_group"] += 1
            continue
        counts["markets_with_sane_group"] += 1
        patterns = sorted(set(group.get("capture_pattern", pd.Series(dtype=str)).dropna().astype(str)))
        pattern = "|".join(patterns) if patterns else "<missing>"
        pattern_market_counts[pattern] += 1
        capture_patterns.update(group.get("capture_pattern", pd.Series(dtype=str)).dropna().astype(str).tolist())

        ts = np.sort(group["ts_ms"].dropna().astype(np.int64).unique())
        if len(ts) > 1:
            interval_ms.update(str(int(value)) for value in np.diff(ts))

        sigs = group.loc[group["secs_to_close"].between(60, 61.75, inclusive="both")]
        if sigs.empty:
            counts["missing_signal_60_61_75"] += 1
            continue
        counts["signal_present"] += 1
        signal = sigs.sort_values("secs_to_close").iloc[0]
        signal_secs[str(float(signal["secs_to_close"]))] += 1
        later = group.loc[group["ts_ms"].gt(signal["ts_ms"])].sort_values("ts_ms")
        if later.empty:
            counts["no_later_snapshot"] += 1
            continue
        delays = (later["ts_ms"] - signal["ts_ms"]).astype(np.int64)
        first = int(delays.iloc[0])
        first_delay_ms[str(first)] += 1
        all_positive_delay_ms.update(str(int(value)) for value in delays.head(10))
        entry_delay_values.append(first)

        original = later.loc[delays.between(1000, 3000, inclusive="both")]
        if original.empty:
            counts["missing_original_1_3s_entry"] += 1
        else:
            counts["original_1_3s_entry_present"] += 1
            pattern_original_entries[pattern] += 1

        for upper in (3000, 4000, 5000, 6000, 10000):
            if bool(delays.between(1000, upper, inclusive="both").any()):
                counts[f"entry_within_{upper // 1000}s"] += 1

        if len(examples) < 25:
            examples.append(
                {
                    "condition_id": str(cid),
                    "capture_pattern": pattern,
                    "signal_ts_ms": int(signal["ts_ms"]),
                    "signal_secs_to_close": float(signal["secs_to_close"]),
                    "first_later_delay_ms": first,
                    "first_later_secs_to_close": float(later.iloc[0]["secs_to_close"]),
                    "first_ten_delay_ms": [int(value) for value in delays.head(10)],
                }
            )

    delays_array = np.asarray(entry_delay_values, dtype=float)
    report = {
        "source": REPO_ID,
        "selection": {
            "btc_slots": int(len(btc)),
            "raw_books": int(len(books)),
            "sane_books": int(len(sane_books)),
        },
        "exact_v2_counts": dict(counts),
        "capture_pattern_row_counts": dict(capture_patterns),
        "capture_pattern_market_counts": dict(pattern_market_counts),
        "capture_pattern_original_entry_counts": dict(pattern_original_entries),
        "signal_secs_to_close_counts": dict(signal_secs),
        "first_later_delay_ms_counts": dict(first_delay_ms),
        "first_ten_positive_delay_ms_counts": dict(all_positive_delay_ms),
        "within_market_interval_ms_counts": dict(interval_ms),
        "first_later_delay_summary_ms": {
            "count": int(delays_array.size),
            "min": float(np.min(delays_array)) if delays_array.size else None,
            "median": float(np.median(delays_array)) if delays_array.size else None,
            "max": float(np.max(delays_array)) if delays_array.size else None,
            "p05": float(np.quantile(delays_array, 0.05)) if delays_array.size else None,
            "p95": float(np.quantile(delays_array, 0.95)) if delays_array.size else None,
        },
        "examples": examples,
    }
    path = out / "timing_diagnostic.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    sums_path = out / "TIMING_SHA256SUMS"
    sums_path.write_text(f"{sha256_file(path)}  {path.name}\n")
    print(path.read_text())


if __name__ == "__main__":
    main()
