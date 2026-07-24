from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import requests

REPO = "obadiaha/polymarket-crypto-5m-15m"
API = f"https://huggingface.co/api/datasets/{REPO}"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(url: str, path: Path) -> None:
    with requests.get(url, stream=True, timeout=300) as response:
        response.raise_for_status()
        with path.open("wb") as handle:
            for block in response.iter_content(1 << 20):
                if block:
                    handle.write(block)


def main() -> None:
    response = requests.get(API, params={"blobs": "true"}, timeout=180)
    response.raise_for_status()
    info = response.json()
    revision = str(info["sha"])
    files: list[dict] = []
    for row in info.get("siblings", []):
        path = str(row.get("rfilename", ""))
        if not path.endswith(".parquet"):
            continue
        lfs = row.get("lfs") or {}
        files.append(
            {
                "path": path,
                "size": int(row.get("size") or lfs.get("size") or 0),
                "oid": lfs.get("oid"),
                "blob_id": row.get("blobId"),
            }
        )
    by_family: dict[str, list[dict]] = {}
    for row in files:
        by_family.setdefault(row["path"].split("/", 1)[0], []).append(row)
    family_summary = {
        family: {
            "count": len(rows),
            "bytes": sum(int(row["size"]) for row in rows),
            "first": min(row["path"] for row in rows),
            "last": max(row["path"] for row in rows),
        }
        for family, rows in sorted(by_family.items())
    }
    selected: list[dict] = []
    for family in ("markets", "resolutions", "orderbooks", "trades", "crypto_prices", "price_history"):
        rows = sorted(by_family.get(family, []), key=lambda row: row["path"])
        if rows:
            selected.append(rows[0])
            if rows[-1]["path"] != rows[0]["path"]:
                selected.append(rows[-1])
    base = f"https://huggingface.co/datasets/{REPO}/resolve/{revision}"
    samples = Path("obadiaha-samples")
    samples.mkdir(exist_ok=True)
    schema_report: list[dict] = []
    for row in selected:
        local = samples / row["path"].replace("/", "__")
        download(f"{base}/{row['path']}", local)
        got = sha256(local)
        oid = row.get("oid")
        if oid and str(oid).startswith("sha256:"):
            assert got == str(oid).split(":", 1)[1], (row["path"], got, oid)
        parquet = pq.ParquetFile(local)
        sample = pd.read_parquet(local).head(3)
        schema_report.append(
            {
                "path": row["path"],
                "bytes": local.stat().st_size,
                "sha256": got,
                "rows": parquet.metadata.num_rows,
                "row_groups": parquet.num_row_groups,
                "schema": str(parquet.schema_arrow),
                "sample": json.loads(sample.to_json(orient="records", date_format="iso")),
            }
        )
        print("\nFILE", row["path"], "rows", parquet.metadata.num_rows, "bytes", local.stat().st_size)
        print(parquet.schema_arrow)
        print(sample.to_string(index=False))
    output = {
        "repo": REPO,
        "revision": revision,
        "files": files,
        "families": family_summary,
        "schema_report": schema_report,
    }
    Path("obadiaha-inventory.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print("\nREVISION", revision)
    print(json.dumps(family_summary, indent=2))


if __name__ == "__main__":
    main()
