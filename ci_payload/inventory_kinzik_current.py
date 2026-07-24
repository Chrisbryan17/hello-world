from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import requests

REPO = "kinzikdza/polymarket-updown-microstructure"
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
        if not path.endswith((".parquet", ".json", ".jsonl", ".csv", ".zip")):
            continue
        lfs = row.get("lfs") or {}
        files.append({"path": path, "size": int(row.get("size") or lfs.get("size") or 0), "oid": lfs.get("oid"), "blob_id": row.get("blobId")})
    selected = sorted([row for row in files if row["path"].endswith(".parquet")], key=lambda row: row["size"])
    # Download all compact parquet files and at most the three largest files when total remains manageable.
    total = sum(row["size"] for row in selected)
    chosen = selected if total <= 4_000_000_000 else selected[:10]
    base = f"https://huggingface.co/datasets/{REPO}/resolve/{revision}"
    samples = Path("kinzik-samples"); samples.mkdir(exist_ok=True)
    schemas=[]
    for row in chosen:
        local=samples/row["path"].replace("/","__")
        local.parent.mkdir(parents=True,exist_ok=True)
        download(f"{base}/{row['path']}", local)
        got=sha256(local)
        oid=row.get("oid")
        if oid and str(oid).startswith("sha256:"):
            assert got==str(oid).split(":",1)[1],(row["path"],got,oid)
        pf=pq.ParquetFile(local)
        sample=pd.read_parquet(local).head(3)
        schemas.append({"path":row["path"],"bytes":local.stat().st_size,"sha256":got,"rows":pf.metadata.num_rows,"row_groups":pf.num_row_groups,"schema":str(pf.schema_arrow),"sample":json.loads(sample.to_json(orient="records",date_format="iso"))})
        print("\nFILE",row["path"],"rows",pf.metadata.num_rows,"bytes",local.stat().st_size)
        print(pf.schema_arrow)
        print(sample.to_string(index=False))
    output={"repo":REPO,"revision":revision,"files":files,"total_listed_bytes":sum(row["size"] for row in files),"schemas":schemas}
    Path("kinzik-current-inventory.json").write_text(json.dumps(output,indent=2),encoding="utf-8")
    print("\nREVISION",revision)
    print("FILES",len(files),"BYTES",output["total_listed_bytes"])
    for row in files: print(row)


if __name__ == "__main__":
    main()
