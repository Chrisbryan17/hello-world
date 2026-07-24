from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import requests

REPO = "Alezanello/polymarket-arena-capture"
API = f"https://huggingface.co/api/datasets/{REPO}"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
        files.append({"path": path, "size": int(row.get("size") or lfs.get("size") or 0), "oid": lfs.get("oid"), "blob_id": row.get("blobId")})
    families: dict[str, list[dict]] = {}
    for row in files:
        parts = row["path"].split("/")
        family = parts[-2] if len(parts) > 2 and parts[0] == "daily" else parts[0].removesuffix(".parquet")
        families.setdefault(family, []).append(row)
    selected: list[dict] = []
    for family, rows in sorted(families.items()):
        rows = sorted(rows, key=lambda r: r["path"])
        selected.append(rows[0])
        if rows[-1]["path"] != rows[0]["path"]:
            selected.append(rows[-1])
    base = f"https://huggingface.co/datasets/{REPO}/resolve/{revision}"
    samples = Path("arena-samples")
    samples.mkdir(exist_ok=True)
    schemas = []
    for row in selected:
        local = samples / row["path"].replace("/", "__")
        download(f"{base}/{row['path']}", local)
        got = sha256(local)
        oid = row.get("oid")
        if oid and str(oid).startswith("sha256:"):
            assert got == str(oid).split(":", 1)[1], (row["path"], got, oid)
        pf = pq.ParquetFile(local)
        sample = pd.read_parquet(local).head(3)
        schemas.append({"path": row["path"], "bytes": local.stat().st_size, "sha256": got, "rows": pf.metadata.num_rows, "row_groups": pf.num_row_groups, "schema": str(pf.schema_arrow), "sample": json.loads(sample.to_json(orient="records", date_format="iso"))})
        print("\nFILE", row["path"], "rows", pf.metadata.num_rows, "bytes", local.stat().st_size)
        print(pf.schema_arrow)
        print(sample.to_string(index=False))
    summary = {family: {"count": len(rows), "bytes": sum(r["size"] for r in rows), "first": min(r["path"] for r in rows), "last": max(r["path"] for r in rows)} for family, rows in sorted(families.items())}
    output = {"repo": REPO, "revision": revision, "files": files, "families": summary, "total_bytes": sum(r["size"] for r in files), "schemas": schemas}
    Path("arena-inventory.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print("\nREVISION", revision)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
