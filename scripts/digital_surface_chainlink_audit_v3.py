from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import digital_surface_chainlink_audit_v2 as prior


def normalize_source_tables(
    markets: pd.DataFrame,
    resolutions: pd.DataFrame,
    out: Path,
) -> pd.DataFrame:
    normalized = markets.copy()
    timestamps = pd.to_datetime(
        normalized["start_time"],
        utc=True,
        errors="coerce",
    )
    normalized["start_time"] = [
        int(value.value) if pd.notna(value) else None
        for value in timestamps
    ]
    frame = prior.normalize_source_tables(normalized, resolutions, out)
    expected = (
        pd.to_datetime(frame["start_time"], utc=True)
        .map(lambda value: int(value.timestamp()))
        .astype("int64")
    )
    if not frame["start_epoch"].astype("int64").equals(expected):
        raise AssertionError("canonical Unix-second boundary normalization failed")
    if int(frame["start_epoch"].min()) < 1_000_000_000:
        raise AssertionError("canonical epochs are not 10-digit Unix seconds")
    return frame


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
    prior.base.normalize_source_tables = normalize_source_tables
    decision = prior.base.run(args.cache_dir, args.output_dir)
    return 0 if decision["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
