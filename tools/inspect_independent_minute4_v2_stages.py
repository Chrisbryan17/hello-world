#!/usr/bin/env python3
"""Reproduce each exact V2 eligibility stage without writing a panel."""
from __future__ import annotations

from collections import Counter
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


def outcome(value: object) -> int | None:
    text = str(value).strip().lower()
    if text in {"up", "yes", "1", "true"}:
        return 1
    if text in {"down", "no", "0", "false"}:
        return 0
    return None


def main() -> None:
    out = Path("independent-minute4-v2-diagnostic")
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(".cache/kinzik-v2-stages")
    cache.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=REPO_ID,
        repo_type="dataset",
        local_dir=str(cache),
        allow_patterns=["parquet/slots.parquet", "parquet/book_snapshots.parquet"],
    )
    slots_path = next(cache.rglob("slots.parquet"))
    books_path = next(cache.rglob("book_snapshots.parquet"))
    slots = pd.read_parquet(slots_path)
    books = pd.read_parquet(books_path)

    slots["coin"] = slots["coin"].astype(str).str.upper()
    btc = slots.loc[
        slots["coin"].eq("BTC")
        & slots["duration"].astype(str).str.lower().isin(["5m", "5-minute", "300", "5"])
    ].copy()
    if btc.empty:
        btc = slots.loc[
            slots["coin"].eq("BTC")
            & slots["slug"].astype(str).str.contains("-5m-", na=False)
        ].copy()
    btc = btc.drop_duplicates("condition_id").set_index("condition_id")
    books = books.loc[books["condition_id"].isin(btc.index)].copy()

    numeric_requested = [
        "ts_ms", "secs_to_close", "yes_bid", "yes_ask", "yes_bid_size",
        "yes_ask_size", "no_bid", "no_ask", "no_bid_size", "no_ask_size",
        "spot", "ds_spot",
    ]
    missing_numeric_columns = [column for column in numeric_requested if column not in books.columns]
    for column in [column for column in numeric_requested if column in books.columns]:
        books[column] = pd.to_numeric(books[column], errors="coerce")

    sane = (
        books["yes_bid"].gt(0)
        & books["yes_ask"].lt(1)
        & books["no_bid"].gt(0)
        & books["no_ask"].lt(1)
        & books["yes_bid"].le(books["yes_ask"])
        & books["no_bid"].le(books["no_ask"])
    )
    books = books.loc[sane].sort_values(["condition_id", "ts_ms"])

    counts: Counter[str] = Counter()
    history_length_counts: Counter[str] = Counter()
    history_span_counts: Counter[str] = Counter()
    entry_delay_counts: Counter[str] = Counter()
    first_ready_examples: list[dict[str, object]] = []
    rows_ready = 0
    path_rows_ready = 0

    for condition_id, group in books.groupby("condition_id", sort=False):
        slot = btc.loc[condition_id]
        resolved = outcome(slot["resolved_side"])
        if resolved is None:
            counts["excluded_outcome"] += 1
            continue
        counts["outcome_valid"] += 1

        signals = group.loc[group["secs_to_close"].between(60, 61.75, inclusive="both")]
        if signals.empty:
            counts["excluded_signal"] += 1
            continue
        counts["signal_valid"] += 1
        signal = signals.sort_values("secs_to_close").iloc[0]

        entries = group.loc[
            group["ts_ms"].between(signal["ts_ms"] + 1000, signal["ts_ms"] + 3000, inclusive="both")
        ]
        if entries.empty:
            counts["excluded_entry"] += 1
            continue
        counts["entry_valid"] += 1
        entry = entries.sort_values("ts_ms").iloc[0]
        entry_delay_counts[str(int(entry["ts_ms"] - signal["ts_ms"]))] += 1

        yes_mid = (signal["yes_bid"] + signal["yes_ask"]) / 2
        no_mid = (signal["no_bid"] + signal["no_ask"]) / 2
        up = bool(yes_mid >= no_mid)
        leader = float(yes_mid if up else no_mid)
        ask = float(entry["yes_ask"] if up else entry["no_ask"])
        bid = float(entry["yes_bid"] if up else entry["no_bid"])
        ask_size = float(entry["yes_ask_size"] if up else entry["no_ask_size"])
        if not all(np.isfinite(value) for value in (leader, ask, bid, ask_size)):
            counts["excluded_nonfinite_entry_fields"] += 1
            continue
        counts["entry_fields_valid"] += 1

        history = group.loc[
            group["ts_ms"].between(signal["ts_ms"] - 31000, signal["ts_ms"], inclusive="both")
        ].copy()
        history["sec_bin"] = np.floor((history["ts_ms"] - signal["ts_ms"]) / 1000).astype(int)
        history = history.sort_values("ts_ms").drop_duplicates("sec_bin", keep="last")
        history_length_counts[str(len(history))] += 1
        if len(history):
            history_span_counts[str(int(signal["ts_ms"] - history["ts_ms"].min()))] += 1
        if len(history) < 8:
            counts["excluded_history_lt8"] += 1
            continue
        counts["history_valid"] += 1

        times = history["ts_ms"].to_numpy(float)
        mids = (
            ((history["yes_bid"] + history["yes_ask"]) / 2).to_numpy(float)
            if up
            else ((history["no_bid"] + history["no_ask"]) / 2).to_numpy(float)
        )
        lag_values: dict[str, float] = {}
        for seconds in [1, 3, 5, 10, 20, 30]:
            index = np.searchsorted(times, signal["ts_ms"] - seconds * 1000, side="right") - 1
            lag_values[f"mom{seconds}"] = leader - mids[index] if index >= 0 else np.nan
        if not all(np.isfinite(value) for value in lag_values.values()):
            counts["history_valid_with_missing_lag"] += 1
        else:
            counts["history_and_lags_valid"] += 1

        rows_ready += 1
        path_group = group.loc[
            group["ts_ms"].ge(entry["ts_ms"])
            & group["secs_to_close"].ge(0)
            & group["secs_to_close"].le(float(entry["secs_to_close"]) + 0.01)
        ]
        path_rows_ready += len(path_group)
        if len(first_ready_examples) < 20:
            first_ready_examples.append(
                {
                    "condition_id": str(condition_id),
                    "signal_secs_to_close": float(signal["secs_to_close"]),
                    "entry_delay_ms": int(entry["ts_ms"] - signal["ts_ms"]),
                    "history_rows": int(len(history)),
                    "history_span_ms": int(signal["ts_ms"] - history["ts_ms"].min()),
                    "path_rows": int(len(path_group)),
                    "leader": leader,
                    "ask": ask,
                    "bid": bid,
                }
            )

    report = {
        "source": REPO_ID,
        "source_hashes": {
            "slots": sha256_file(slots_path),
            "books": sha256_file(books_path),
        },
        "columns": books.columns.tolist(),
        "missing_numeric_columns_requested_by_v2": missing_numeric_columns,
        "selected": {
            "btc_slots": int(len(btc)),
            "sane_books": int(len(books)),
            "grouped_markets": int(books["condition_id"].nunique()),
        },
        "stage_counts": dict(counts),
        "history_length_counts": dict(history_length_counts),
        "history_span_ms_counts": dict(history_span_counts),
        "entry_delay_ms_counts": dict(entry_delay_counts),
        "feature_rows_ready": rows_ready,
        "path_rows_ready_before_column_selection": path_rows_ready,
        "path_columns_available": {
            column: column in books.columns for column in ["spot", "ds_spot"]
        },
        "first_ready_examples": first_ready_examples,
    }
    path = out / "stage_diagnostic.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    sums = out / "STAGE_SHA256SUMS"
    sums.write_text(f"{sha256_file(path)}  {path.name}\n")
    print(path.read_text())


if __name__ == "__main__":
    main()
