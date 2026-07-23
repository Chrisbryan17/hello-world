#!/usr/bin/env python3
"""Read-only diagnostics for the independent May–June BTC 5-minute corpus."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
    text = text.str.replace(r"\.0+$", "", regex=True)
    return text


def sample_records(frame: pd.DataFrame, columns: list[str], limit: int = 10) -> list[dict[str, object]]:
    available = [column for column in columns if column in frame.columns]
    return json.loads(frame.loc[:, available].head(limit).to_json(orient="records", date_format="iso"))


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
    broad_slug = coin_norm.eq("BTC") & slug.str.contains(r"(^|[-_])5m($|[-_])", case=False, na=False, regex=True)
    numeric_seconds = pd.to_numeric(duration_norm, errors="coerce").eq(300)
    robust = coin_norm.eq("BTC") & (duration_norm.isin(["5m", "5-minute", "5min", "5mins", "300", "5"]) | numeric_seconds | broad_slug)

    slot_ids_raw = set(slots.loc[robust, "condition_id"].dropna().tolist())
    slot_ids_text = set(slots.loc[robust, "condition_id"].dropna().astype(str).tolist())
    book_ids_raw = set(books["condition_id"].dropna().tolist())
    book_ids_text = set(books["condition_id"].dropna().astype(str).tolist())

    report = {
        "source": REPO_ID,
        "files": {
            "slots": {"path": str(slots_path), "bytes": slots_path.stat().st_size, "sha256": sha256_file(slots_path)},
            "books": {"path": str(books_path), "bytes": books_path.stat().st_size, "sha256": sha256_file(books_path)},
        },
        "shapes": {"slots": list(slots.shape), "books": list(books.shape)},
        "columns": {"slots": slots.columns.tolist(), "books": books.columns.tolist()},
        "dtypes": {"slots": slots.dtypes.astype(str).to_dict(), "books": books.dtypes.astype(str).to_dict()},
        "coin_counts": coin_norm.value_counts(dropna=False).head(30).to_dict(),
        "btc_duration_counts_raw": slots.loc[coin_norm.eq("BTC"), "duration"].astype(str).value_counts(dropna=False).head(50).to_dict(),
        "btc_duration_counts_normalized": duration_norm.loc[coin_norm.eq("BTC")].value_counts(dropna=False).head(50).to_dict(),
        "selector_counts": {
            "old_exact": int(old_exact.sum()),
            "old_fallback": int(old_fallback.sum()),
            "broad_slug": int(broad_slug.sum()),
            "numeric_300": int((coin_norm.eq("BTC") & numeric_seconds).sum()),
            "robust": int(robust.sum()),
        },
        "condition_id": {
            "slot_python_types": slots.loc[robust, "condition_id"].map(lambda value: type(value).__name__).value_counts().to_dict(),
            "book_python_types": books["condition_id"].head(10000).map(lambda value: type(value).__name__).value_counts().to_dict(),
            "robust_slot_ids": len(slot_ids_raw),
            "raw_overlap": len(slot_ids_raw & book_ids_raw),
            "text_overlap": len(slot_ids_text & book_ids_text),
            "books_matching_raw": int(books["condition_id"].isin(slot_ids_raw).sum()),
            "books_matching_text": int(books["condition_id"].astype(str).isin(slot_ids_text).sum()),
        },
        "samples": {
            "btc_slots": sample_records(slots.loc[coin_norm.eq("BTC")], ["condition_id", "coin", "duration", "slug", "open_ts", "resolved_side", "strike", "spot_at_open", "spot_at_close", "fee_rate"]),
            "robust_slots": sample_records(slots.loc[robust], ["condition_id", "coin", "duration", "slug", "open_ts", "resolved_side"]),
            "books": sample_records(books, ["condition_id", "ts_ms", "secs_to_close", "yes_bid", "yes_ask", "no_bid", "no_ask"]),
        },
    }
    path = out / "diagnostic.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (out / "SHA256SUMS").write_text(f"{sha256_file(path)}  {path.name}\n")
    print(path.read_text())


if __name__ == "__main__":
    main()
