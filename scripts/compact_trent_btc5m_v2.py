#!/usr/bin/env python3
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import math
import random
import re
import time

import numpy as np
import pandas as pd
from huggingface_hub import hf_hub_download, list_repo_files

REPO = "trentmkelly/polymarket_crypto_derivatives"
OBS = (10, 20, 30, 45, 60)
LATS = (100, 250, 500, 1000)
PAT = re.compile(r"btc5m_market(\d+)_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})_all")


def first_after(ts, target, max_gap):
    i = int(np.searchsorted(ts, target, side="left"))
    if i >= len(ts) or ts[i] - target > max_gap:
        return -1
    return i


def last_before(ts, vals, target, max_stale):
    i = int(np.searchsorted(ts, target, side="right")) - 1
    if i < 0 or target - ts[i] > max_stale:
        return np.nan
    return vals[i]


def outcome_from_preclose(d: pd.DataFrame, start_ms: int):
    sane = (
        d.up_best_bid.gt(0) & d.up_best_ask.gt(d.up_best_bid) & d.up_best_ask.lt(1)
        & d.down_best_bid.gt(0) & d.down_best_ask.gt(d.down_best_bid) & d.down_best_ask.lt(1)
    )
    g = d[sane & d.ts.between(start_ms + 270_000, start_ms + 302_000)]
    if g.empty:
        return None
    r = g.iloc[-1]
    up_mid = 0.5 * (float(r.up_best_bid) + float(r.up_best_ask))
    down_mid = 0.5 * (float(r.down_best_bid) + float(r.down_best_ask))
    # Require near-terminal market consensus so the label is not a prediction.
    if max(up_mid, down_mid) < 0.85 or abs(up_mid - down_mid) < 0.70:
        return None
    return int(up_mid >= down_mid), int(r.ts), up_mid, down_mid


def compact_file(local_path: str, repo_path: str):
    m = PAT.fullmatch(Path(repo_path).parent.name)
    if not m:
        return []
    market_id, start_s = m.groups()
    start_dt = datetime.strptime(start_s, "%Y-%m-%d_%H-%M-%S").replace(tzinfo=timezone.utc)
    start_ms = int(start_dt.timestamp() * 1000)
    d = pd.read_parquet(local_path).sort_values("ts")
    d = d[d.ts.between(start_ms - 2_000, start_ms + 305_000)]
    if len(d) < 100:
        return []

    resolved = outcome_from_preclose(d, start_ms)
    if resolved is None:
        return []
    y, label_ts, terminal_up_mid, terminal_down_mid = resolved

    b = d[["ts", "binance_price"]].dropna()
    bt = b.ts.to_numpy(np.int64)
    bv = b.binance_price.to_numpy(float)
    open_i = first_after(bt, start_ms, 2_000)
    if open_i < 0 or bv[open_i] <= 0:
        return []
    open_px = float(bv[open_i])

    targets = start_ms + np.arange(0, 61, dtype=np.int64) * 1000
    path = np.array([last_before(bt, bv, int(t), 1_500) for t in targets], dtype=float)
    if not np.isfinite(path[0]):
        path[0] = open_px
    for j in range(1, len(path)):
        if not np.isfinite(path[j]):
            path[j] = path[j - 1]
    if not np.isfinite(path).all():
        return []
    lr = np.diff(np.log(np.maximum(path, 1e-12)), prepend=np.log(max(path[0], 1e-12)))
    ts = d.ts.to_numpy(np.int64)
    rows = []
    for obs in OBS:
        def mom(k):
            j = max(0, obs - k)
            return math.log(path[obs] / path[j]) * 1e4

        def vol(k):
            j = max(1, obs - k + 1)
            return float(np.std(lr[j:obs + 1]) * 1e4)

        base = {
            "episode": Path(repo_path).parent.name,
            "market_id": market_id,
            "market_start": start_dt.isoformat(),
            "market_start_ms": start_ms,
            "obs": obs,
            "y": y,
            "label_ts": label_ts,
            "terminal_up_mid": terminal_up_mid,
            "terminal_down_mid": terminal_down_mid,
            "binance_open": float(path[0]),
            "binance_now": float(path[obs]),
            "BTC_ret": math.log(path[obs] / path[0]) * 1e4,
            "BTC_mom5": mom(5),
            "BTC_mom10": mom(10),
            "BTC_vol10": vol(10),
            "BTC_vol30": vol(min(30, obs)),
            "BTC_range": (np.max(path[:obs + 1]) - np.min(path[:obs + 1])) / path[0] * 1e4,
        }
        for lat in LATS:
            target = start_ms + obs * 1000 + lat
            i = first_after(ts, target, 300)
            if i < 0:
                continue
            r = d.iloc[i]
            vals = [r.up_best_bid, r.up_best_ask, r.down_best_bid, r.down_best_ask]
            if not all(np.isfinite(vals)):
                continue
            ub, ua, db, da = map(float, vals)
            if not (0 < ub < ua < 1 and 0 < db < da < 1):
                continue
            sizes = [r.up_bid_size_total, r.up_ask_size_total, r.down_bid_size_total, r.down_ask_size_total]
            if not all(np.isfinite(sizes)):
                continue
            rows.append(dict(
                base,
                latency_ms=lat,
                entry_ts=int(r.ts),
                entry_gap_ms=int(r.ts - target),
                up_bid=ub,
                up_ask=ua,
                down_bid=db,
                down_ask=da,
                up_mid=float(r.up_mid),
                down_mid=float(r.down_mid),
                up_spread=float(r.up_spread),
                down_spread=float(r.down_spread),
                up_bid_size=float(r.up_bid_size_total),
                up_ask_size=float(r.up_ask_size_total),
                up_imbalance=float(r.up_imbalance),
                down_bid_size=float(r.down_bid_size_total),
                down_ask_size=float(r.down_ask_size_total),
                down_imbalance=float(r.down_imbalance),
            ))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--shards", type=int, default=16)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    files = sorted(p for p in list_repo_files(REPO, repo_type="dataset") if p.startswith("btc5m_") and p.endswith("/steps.parquet"))
    selected = [p for i, p in enumerate(files) if i % args.shards == args.shard]
    print(json.dumps({"all": len(files), "shard": args.shard, "selected": len(selected)}), flush=True)

    def dl(path):
        err = None
        for attempt in range(6):
            try:
                return path, hf_hub_download(REPO, path, repo_type="dataset"), None
            except Exception as exc:
                err = repr(exc)
                time.sleep(min(8.0, 0.5 * (2 ** attempt)) + random.random())
        return path, None, err

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        downloaded = list(ex.map(dl, selected))
    rows = []
    failures = {}
    missing = []
    for n, (repo_path, local_path, download_error) in enumerate(downloaded, 1):
        if local_path is None:
            missing.append({"path": repo_path, "error": download_error})
            continue
        try:
            rows.extend(compact_file(local_path, repo_path))
        except Exception as exc:
            key = type(exc).__name__
            failures[key] = failures.get(key, 0) + 1
        if n % 100 == 0:
            print("processed", n, "rows", len(rows), "missing", len(missing), "failures", failures, flush=True)

    out = pd.DataFrame(rows)
    parquet = f"trent_btc5m_compact_v2_shard_{args.shard:02d}.parquet"
    manifest_path = f"trent_btc5m_manifest_v2_shard_{args.shard:02d}.json"
    if len(out):
        out.to_parquet(parquet, index=False, compression="zstd")
    manifest = {
        "all_episodes": len(files),
        "shard": args.shard,
        "shards": args.shards,
        "episodes_selected": len(selected),
        "downloaded": len(downloaded) - len(missing),
        "download_missing": missing,
        "rows": len(out),
        "markets": int(out.episode.nunique()) if len(out) else 0,
        "start": str(out.market_start.min()) if len(out) else None,
        "end": str(out.market_start.max()) if len(out) else None,
        "failures": failures,
        "obs_counts": out.obs.value_counts().sort_index().to_dict() if len(out) else {},
        "latency_counts": out.latency_ms.value_counts().sort_index().to_dict() if len(out) else {},
    }
    Path(manifest_path).write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
