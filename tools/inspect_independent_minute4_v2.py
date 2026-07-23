#!/usr/bin/env python3
"""Read-only diagnostics for the independent May–June BTC 5-minute corpus."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import traceback

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


def normalized_duration(values: pd.Series) -> pd.Series:
    text = values.astype(str).str.strip().str.lower()
    return text.str.replace(r"\.0+$", "", regex=True)


def sample_records(frame: pd.DataFrame, columns: list[str], limit: int = 10) -> list[dict[str, object]]:
    available = [column for column in columns if column in frame.columns]
    return json.loads(frame.loc[:, available].head(limit).to_json(orient="records", date_format="iso"))


def finite_scalar(value: object) -> bool:
    try:
        return bool(np.isfinite(value))
    except (TypeError, ValueError):
        return False


def legacy_loop_diagnostic(btc: pd.DataFrame, books: pd.DataFrame) -> dict[str, object]:
    groups = {condition_id: group.copy() for condition_id, group in books.groupby("condition_id", sort=False)}
    counts: Counter[str] = Counter()
    exception_counts: Counter[str] = Counter()
    exception_examples: list[dict[str, object]] = []
    first_success: dict[str, object] | None = None

    for _, slot in btc.iterrows():
        condition_id = slot["condition_id"]
        try:
            book = groups.get(condition_id)
            if book is None or book.empty:
                counts["missing_book_group"] += 1
                continue
            book["secs_to_close"] = pd.to_numeric(book["secs_to_close"], errors="coerce")
            book["market_start"] = pd.to_datetime(int(slot["open_ts"]), unit="s", utc=True)
            book = book.sort_values("secs_to_close", ascending=False)

            side = str(slot["resolved_side"]).strip().lower()
            direction = 1 if side in {"yes", "up", "1", "true"} else -1
            entry_window = book[(book["secs_to_close"] <= 40) & (book["secs_to_close"] >= 5)].copy()
            if entry_window.empty:
                counts["empty_entry_window"] += 1
                continue
            entry = entry_window.sort_values("secs_to_close", ascending=False).iloc[0]
            yes_ask = pd.to_numeric(entry["yes_ask"], errors="coerce")
            no_ask = pd.to_numeric(entry["no_ask"], errors="coerce")
            yes_bid = pd.to_numeric(entry["yes_bid"], errors="coerce")
            no_bid = pd.to_numeric(entry["no_bid"], errors="coerce")
            if not finite_scalar(yes_ask):
                if finite_scalar(no_bid):
                    yes_ask = 1.0 - no_bid
                else:
                    counts["nonfinite_yes_ask"] += 1
                    continue
            if not finite_scalar(no_ask):
                if finite_scalar(yes_bid):
                    no_ask = 1.0 - yes_bid
                else:
                    counts["nonfinite_no_ask"] += 1
                    continue
            ask = float(yes_ask if direction == 1 else no_ask)
            depth = pd.to_numeric(entry["yes_ask_size"] if direction == 1 else entry["no_ask_size"], errors="coerce")
            if not finite_scalar(ask) or not (0.0 < ask < 1.0):
                counts["invalid_selected_ask"] += 1
                continue
            fee_rate = pd.to_numeric(slot.get("fee_rate", 0.0), errors="coerce")
            fee_rate = float(fee_rate) if finite_scalar(fee_rate) else 0.0
            fee = fee_rate * ask * (1.0 - ask)
            entry_cost = ask + 0.01 + fee
            win_multiple = 1.0 / entry_cost
            strike = pd.to_numeric(slot.get("strike"), errors="coerce")
            spot_close = pd.to_numeric(slot.get("spot_at_close"), errors="coerce")
            correct = (spot_close >= strike) if direction == 1 else (spot_close < strike)
            loss = (not bool(correct)) if finite_scalar(spot_close) else False
            if finite_scalar(spot_close):
                contract_multiple = 0.0 if loss else float(win_multiple)
                loss_source = "spot_at_close"
            else:
                contract_multiple = 0.0 if side not in {"yes" if direction == 1 else "no"} else float(win_multiple)
                loss = bool(contract_multiple == 0.0)
                loss_source = "resolved_side"

            late = book[(book["secs_to_close"] <= 60) & (book["secs_to_close"] >= 1)].copy()
            if late.empty:
                counts["empty_late_window"] += 1
                continue
            late_snapshot_count = 0
            for _, row in late.iterrows():
                current_mid = float(
                    pd.to_numeric(
                        row["yes_ask"] if direction == 1 else row["no_ask"],
                        errors="coerce",
                    )
                )
                current_bid = pd.to_numeric(row["yes_bid"] if direction == 1 else row["no_bid"], errors="coerce")
                current_spread = float(current_mid - current_bid) if finite_scalar(current_bid) and finite_scalar(current_mid) else np.nan
                current_size = pd.to_numeric(row["yes_ask_size"] if direction == 1 else row["no_ask_size"], errors="coerce")
                _ = {
                    "condition_id": condition_id,
                    "market_start": row["market_start"],
                    "secs_to_close": float(row["secs_to_close"]),
                    "current_mid": current_mid,
                    "current_spread": current_spread,
                    "current_size": float(current_size) if finite_scalar(current_size) else np.nan,
                    "loss": int(loss),
                }
                late_snapshot_count += 1

            counts["success"] += 1
            counts["late_snapshots"] += late_snapshot_count
            if first_success is None:
                first_success = {
                    "condition_id": condition_id,
                    "entry_secs_to_close": float(entry["secs_to_close"]),
                    "ask": ask,
                    "depth": float(depth) if finite_scalar(depth) else None,
                    "fee_rate": fee_rate,
                    "contract_multiple": contract_multiple,
                    "loss": int(loss),
                    "loss_source": loss_source,
                    "late_snapshot_count": late_snapshot_count,
                }
        except Exception as exc:  # Diagnostic intentionally captures the legacy silent failure.
            key = f"{type(exc).__name__}: {exc}"
            exception_counts[key] += 1
            if len(exception_examples) < 20:
                exception_examples.append(
                    {
                        "condition_id": str(condition_id),
                        "error": key,
                        "traceback": traceback.format_exc(),
                    }
                )

    return {
        "counts": dict(counts),
        "exception_counts": dict(exception_counts),
        "exception_examples": exception_examples,
        "first_success": first_success,
        "entry_secs_to_close_counts": books.loc[
            books["secs_to_close"].between(1, 60, inclusive="both"), "secs_to_close"
        ].value_counts().sort_index().to_dict(),
    }


def main() -> None:
    out = Path("independent-minute4-v2-diagnostic")
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(".cache/kinzik-v2-diagnostic")
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

    coin_norm = slots["coin"].astype(str).str.strip().str.upper()
    duration_norm = normalized_duration(slots["duration"])
    slug = slots["slug"].astype(str) if "slug" in slots.columns else pd.Series("", index=slots.index)
    old_exact = coin_norm.eq("BTC") & duration_norm.isin(["5m", "5-minute", "300", "5"])
    old_fallback = coin_norm.eq("BTC") & slug.str.contains("-5m-", case=False, na=False)
    broad_slug = coin_norm.eq("BTC") & slug.str.contains(r"(?:^|[-_])5m(?:$|[-_])", case=False, na=False, regex=True)
    numeric_seconds = pd.to_numeric(duration_norm, errors="coerce").eq(300)
    robust = coin_norm.eq("BTC") & (
        duration_norm.isin(["5m", "5-minute", "5min", "5mins", "300", "5"])
        | numeric_seconds
        | broad_slug
    )
    btc = slots.loc[robust].copy()
    btc_ids = set(btc["condition_id"].dropna())
    books_btc = books[books["condition_id"].isin(btc_ids)].copy()

    slot_ids_text = set(btc["condition_id"].dropna().astype(str))
    book_ids_raw = set(books["condition_id"].dropna())
    book_ids_text = set(books["condition_id"].dropna().astype(str))

    report = {
        "source": REPO_ID,
        "files": {
            "slots": {"path": str(slots_path), "bytes": slots_path.stat().st_size, "sha256": sha256_file(slots_path)},
            "books": {"path": str(books_path), "bytes": books_path.stat().st_size, "sha256": sha256_file(books_path)},
        },
        "shapes": {"slots": list(slots.shape), "books": list(books.shape), "btc_slots": list(btc.shape), "btc_books": list(books_btc.shape)},
        "columns": {"slots": slots.columns.tolist(), "books": books.columns.tolist()},
        "dtypes": {"slots": slots.dtypes.astype(str).to_dict(), "books": books.dtypes.astype(str).to_dict()},
        "coin_counts": coin_norm.value_counts(dropna=False).head(30).to_dict(),
        "btc_duration_counts_raw": slots.loc[coin_norm.eq("BTC"), "duration"].astype(str).value_counts(dropna=False).head(50).to_dict(),
        "btc_duration_counts_normalized": duration_norm.loc[coin_norm.eq("BTC")].value_counts(dropna=False).head(50).to_dict(),
        "spot_at_close": {
            "finite": int(pd.to_numeric(btc["spot_at_close"], errors="coerce").notna().sum()),
            "missing": int(pd.to_numeric(btc["spot_at_close"], errors="coerce").isna().sum()),
        },
        "selector_counts": {
            "old_exact": int(old_exact.sum()),
            "old_fallback": int(old_fallback.sum()),
            "broad_slug": int(broad_slug.sum()),
            "numeric_300": int((coin_norm.eq("BTC") & numeric_seconds).sum()),
            "robust": int(robust.sum()),
        },
        "condition_id": {
            "slot_python_types": btc["condition_id"].map(lambda value: type(value).__name__).value_counts().to_dict(),
            "book_python_types": books["condition_id"].head(10000).map(lambda value: type(value).__name__).value_counts().to_dict(),
            "robust_slot_ids": len(btc_ids),
            "raw_overlap": len(btc_ids & book_ids_raw),
            "text_overlap": len(slot_ids_text & book_ids_text),
            "books_matching_raw": int(books["condition_id"].isin(btc_ids).sum()),
            "books_matching_text": int(books["condition_id"].astype(str).isin(slot_ids_text).sum()),
        },
        "legacy_loop": legacy_loop_diagnostic(btc, books_btc),
        "samples": {
            "btc_slots": sample_records(btc, ["condition_id", "coin", "duration", "slug", "open_ts", "resolved_side", "strike", "spot_at_open", "spot_at_close", "fee_rate"]),
            "books": sample_records(books_btc, ["condition_id", "ts_ms", "secs_to_close", "yes_bid", "yes_ask", "no_bid", "no_ask"]),
        },
    }
    path = out / "diagnostic.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (out / "SHA256SUMS").write_text(f"{sha256_file(path)}  {path.name}\n")
    print(path.read_text())


if __name__ == "__main__":
    main()
