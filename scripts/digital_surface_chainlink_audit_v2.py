from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

import digital_surface_chainlink_audit as base


def normalize_source_tables(
    markets: pd.DataFrame,
    resolutions: pd.DataFrame,
    out: Path,
) -> pd.DataFrame:
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
    market_identifier = work["condition_id"].fillna("").astype(str).str.strip()
    unidentified_market_rows = int(market_identifier.eq("").sum())
    work["condition_id"] = market_identifier
    work = work[work["condition_id"].ne("")].copy()
    work["asset"] = work["asset"].astype(str).str.upper()
    work["market_type"] = work["market_type"].astype(str)
    work["start_dt"] = pd.to_datetime(work["start_time"], utc=True, errors="coerce")
    work = work[
        (work["asset"] == "BTC")
        & work["market_type"].isin(base.HORIZON_SECONDS)
        & work["start_dt"].between(
            pd.Timestamp("2026-03-06", tz="UTC"),
            pd.Timestamp("2026-03-20", tz="UTC"),
            inclusive="left",
        )
    ].copy()

    resolved = resolutions[["condition_id", "outcome"]].copy()
    resolution_identifier = resolved["condition_id"].fillna("").astype(str).str.strip()
    unidentified_resolution_rows = int(resolution_identifier.eq("").sum())
    resolved["condition_id"] = resolution_identifier
    resolved = resolved[resolved["condition_id"].ne("")].copy()
    resolved["outcome"] = resolved["outcome"].astype(str).str.title()
    inconsistent_resolutions = (
        resolved.groupby("condition_id")["outcome"]
        .nunique()
        .loc[lambda series: series > 1]
    )
    if not inconsistent_resolutions.empty:
        raise ValueError(
            "inconsistent duplicate resolutions: "
            f"{inconsistent_resolutions.index[:20].tolist()}"
        )
    identified_resolution_rows_before_dedup = len(resolved)
    resolved = resolved.drop_duplicates("condition_id", keep="last")

    work = work.merge(resolved, on="condition_id", how="inner", validate="many_to_one")
    joined_rows_before_dedup = len(work)
    work["start_epoch"] = (
        work["start_dt"].astype("int64") // 1_000_000_000
    ).astype("int64")
    work["duration_s"] = work["market_type"].map(base.HORIZON_SECONDS).astype("int64")
    work["end_epoch"] = work["start_epoch"] + work["duration_s"]
    work["canonical_slug"] = [
        f"btc-updown-{base.HORIZON_SLUG[kind]}-{epoch}"
        for kind, epoch in zip(work["market_type"], work["start_epoch"])
    ]
    work["next_slug"] = [
        f"btc-updown-{base.HORIZON_SLUG[kind]}-{epoch}"
        for kind, epoch in zip(work["market_type"], work["end_epoch"])
    ]

    supplied_slug = (
        work["slug"].astype(str)
        if "slug" in work
        else pd.Series("", index=work.index, dtype="object")
    )
    supplied_epoch = pd.to_numeric(
        supplied_slug.str.extract(r"(\d{10})(?:\D*)$")[0],
        errors="coerce",
    )
    work["supplied_slug"] = supplied_slug
    work["supplied_slug_epoch"] = supplied_epoch
    work["supplied_slug_matches_boundary"] = supplied_epoch.eq(work["start_epoch"])

    duplicate_rows = work.duplicated(["market_type", "start_epoch"], keep=False)
    duplicate_consistency = (
        work.loc[duplicate_rows]
        .groupby(["market_type", "start_epoch"])
        .agg(
            outcomes=("outcome", "nunique"),
            conditions=("condition_id", "nunique"),
        )
    )
    inconsistent_intervals = duplicate_consistency[
        duplicate_consistency["outcomes"] > 1
    ]
    if not inconsistent_intervals.empty:
        raise ValueError(
            "conflicting outcomes for duplicate intervals: "
            f"{inconsistent_intervals.head(20).to_dict('index')}"
        )

    work = (
        work.sort_values(
            ["market_type", "start_epoch", "condition_id"],
            kind="mergesort",
        )
        .drop_duplicates(["market_type", "start_epoch"], keep="last")
        .reset_index(drop=True)
    )
    if work.empty:
        raise ValueError("no identified BTC 5m/15m contracts in immutable window")

    preflight = {
        "market_columns": market_columns,
        "resolution_columns": resolution_columns,
        "raw_market_rows": int(len(markets)),
        "raw_resolution_rows": int(len(resolutions)),
        "filtered_joined_rows_before_interval_dedup": int(joined_rows_before_dedup),
        "contracts_after_normalization": int(len(work)),
        "unidentified_market_rows_excluded": unidentified_market_rows,
        "unidentified_resolution_rows_excluded": unidentified_resolution_rows,
        "identified_resolution_duplicate_rows": int(
            identified_resolution_rows_before_dedup - len(resolved)
        ),
        "duplicate_interval_groups": int(len(duplicate_consistency)),
        "slug_boundary_match_rate": float(
            work["supplied_slug_matches_boundary"].mean()
        ),
        "by_horizon": (
            work["market_type"]
            .value_counts()
            .sort_index()
            .astype(int)
            .to_dict()
        ),
        "first_start": work["start_dt"].min().isoformat(),
        "last_start": work["start_dt"].max().isoformat(),
    }
    base.atomic_json(out / "preflight.json", preflight)
    print(json.dumps(preflight, indent=2), flush=True)
    return work


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
    base.normalize_source_tables = normalize_source_tables
    decision = base.run(args.cache_dir, args.output_dir)
    return 0 if decision["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
