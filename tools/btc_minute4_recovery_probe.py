#!/usr/bin/env python3
"""Verify public BTC/spot sources before the v54 sizing experiment.

This probe performs no strategy fitting and reads no untouched test outcomes for
policy selection. It only proves that the public source files reproduce the
preserved local corpus hashes and a known spot-price sample.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq
from huggingface_hub import HfApi, hf_hub_download

BTC_REPO = "kachoio/polymarket-5-minute-crypto-up-down-markets"
SPOT_REPO = "aliplayer1/polymarket-crypto-updown"
SPOT_REVISION = "refs/convert/parquet"
SPOT_FILE = "spot_prices/train/0000.parquet"
EXPECTED_MARKETS_SHA256 = "8e0ed78021bd98d3dba18829266103ebd9b46a77f6ba872a1c7f98be77b506bd"
EXPECTED_TICKS_SHA256 = "173760b951ac0a2c795e1c3873a506e2fd4372db356dd3515f06582820ff975e"
EXPECTED_MARKETS_ROWS = 15_682
EXPECTED_TICKS_ROWS = 4_704_518
KNOWN_SPOT_TS_MS = 1_774_494_180_000
KNOWN_SPOT_PRICE = 70_814.5


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def select_single_btc_archive(files: list[str]) -> str:
    candidates = [
        name
        for name in files
        if name.lower().endswith(".zip")
        and "btc" in Path(name).name.lower()
        and "5m" in Path(name).name.lower().replace("-", "")
    ]
    if len(candidates) != 1:
        candidates = [
            name
            for name in files
            if name.lower().endswith(".zip") and "btc" in Path(name).name.lower()
        ]
    if len(candidates) != 1:
        raise RuntimeError(f"expected one BTC archive; found {candidates}")
    return candidates[0]


def resolve_btc_source_files(files: list[str]) -> dict[str, str]:
    markets = [name for name in files if Path(name).name == "btc_markets.parquet"]
    ticks = [name for name in files if Path(name).name == "btc_ticks.parquet"]
    if len(markets) == 1 and len(ticks) == 1:
        return {
            "kind": "direct_parquet",
            "markets": markets[0],
            "ticks": ticks[0],
        }
    return {
        "kind": "zip",
        "archive": select_single_btc_archive(files),
    }


def find_exact_file(root: Path, basename: str) -> Path:
    matches = sorted(root.rglob(basename))
    if len(matches) != 1:
        raise RuntimeError(f"expected one {basename}; found {matches}")
    return matches[0]


def verify_spot_sample(spot_path: Path) -> dict[str, object]:
    parquet = pq.ParquetFile(spot_path)
    schema_names = parquet.schema_arrow.names
    expected_schema = ["ts_ms", "symbol", "price", "source"]
    if schema_names != expected_schema:
        raise AssertionError(f"spot schema mismatch: {schema_names}")

    found: list[dict[str, object]] = []
    for batch in parquet.iter_batches(
        batch_size=262_144,
        columns=expected_schema,
    ):
        mask = pc.and_(
            pc.equal(batch.column(batch.schema.get_field_index("ts_ms")), KNOWN_SPOT_TS_MS),
            pc.and_(
                pc.equal(batch.column(batch.schema.get_field_index("symbol")), "btcusdt"),
                pc.equal(batch.column(batch.schema.get_field_index("source")), "binance"),
            ),
        )
        selected = batch.filter(mask)
        if selected.num_rows:
            found.extend(selected.to_pylist())
    if len(found) != 1:
        raise AssertionError(f"known spot row count mismatch: {found}")
    price = float(found[0]["price"])
    if abs(price - KNOWN_SPOT_PRICE) > 1e-9:
        raise AssertionError(f"known spot price mismatch: {price}")

    return {
        "rows": parquet.metadata.num_rows,
        "row_groups": parquet.metadata.num_row_groups,
        "schema": schema_names,
        "known_sample": found[0],
        "sha256": sha256_file(spot_path),
        "size_bytes": spot_path.stat().st_size,
    }


def download_btc_sources(source: dict[str, str], temp: Path) -> tuple[Path, Path, dict[str, object]]:
    if source["kind"] == "direct_parquet":
        markets = Path(
            hf_hub_download(
                repo_id=BTC_REPO,
                repo_type="dataset",
                filename=source["markets"],
                local_dir=temp / "btc-download",
            )
        )
        ticks = Path(
            hf_hub_download(
                repo_id=BTC_REPO,
                repo_type="dataset",
                filename=source["ticks"],
                local_dir=temp / "btc-download",
            )
        )
        return markets, ticks, {
            "kind": "direct_parquet",
            "files": [source["markets"], source["ticks"]],
        }

    archive_path = Path(
        hf_hub_download(
            repo_id=BTC_REPO,
            repo_type="dataset",
            filename=source["archive"],
            local_dir=temp / "btc-download",
        )
    )
    extracted = temp / "btc-extracted"
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(extracted)
        members = sorted(archive.namelist())
    return (
        find_exact_file(extracted, "btc_markets.parquet"),
        find_exact_file(extracted, "btc_ticks.parquet"),
        {
            "kind": "zip",
            "archive": source["archive"],
            "archive_members": members,
            "archive_sha256": sha256_file(archive_path),
            "archive_size_bytes": archive_path.stat().st_size,
        },
    )


def main() -> None:
    output_dir = Path("recovery-probe-output")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    api = HfApi()
    btc_files = api.list_repo_files(BTC_REPO, repo_type="dataset")
    btc_source = resolve_btc_source_files(btc_files)

    with tempfile.TemporaryDirectory(prefix="btc-minute4-probe-") as temporary:
        temp = Path(temporary)
        markets, ticks, source_report = download_btc_sources(btc_source, temp)
        markets_sha = sha256_file(markets)
        ticks_sha = sha256_file(ticks)
        markets_rows = pq.ParquetFile(markets).metadata.num_rows
        ticks_rows = pq.ParquetFile(ticks).metadata.num_rows

        assert markets_sha == EXPECTED_MARKETS_SHA256, markets_sha
        assert ticks_sha == EXPECTED_TICKS_SHA256, ticks_sha
        assert markets_rows == EXPECTED_MARKETS_ROWS, markets_rows
        assert ticks_rows == EXPECTED_TICKS_ROWS, ticks_rows

        spot_path = Path(
            hf_hub_download(
                repo_id=SPOT_REPO,
                repo_type="dataset",
                revision=SPOT_REVISION,
                filename=SPOT_FILE,
                local_dir=temp / "spot-download",
            )
        )
        spot_report = verify_spot_sample(spot_path)

        report = {
            "status": "verified",
            "experiment_started": False,
            "btc": {
                "repository": BTC_REPO,
                **source_report,
                "markets_rows": markets_rows,
                "ticks_rows": ticks_rows,
                "markets_sha256": markets_sha,
                "ticks_sha256": ticks_sha,
            },
            "spot": {
                "repository": SPOT_REPO,
                "revision": SPOT_REVISION,
                "file": SPOT_FILE,
                **spot_report,
            },
        }

    report_path = output_dir / "recovery_probe.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (output_dir / "SHA256SUMS").write_text(
        f"{sha256_file(report_path)}  {report_path.name}\n"
    )
    print(report_path.read_text())


if __name__ == "__main__":
    main()
