from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
from huggingface_hub import hf_hub_download

DATASET_REPO = "kachoio/polymarket-5-minute-crypto-up-down-markets"
ASSETS = ("btc", "eth")
POLICY = {
    "assets": ASSETS,
    "entry_second": 210,
    "signal_ask_min": 0.85,
    "latency_seconds": 1,
    "fok_limit": "signal_ask",
    "shares": 5,
    "cancel_below_signal_by_more_than": 0.01,
    "hold": "settlement",
    "fee_rate": 0.07,
    "live_submission": "disabled",
}


def frozen_policy() -> dict[str, Any]:
    return dict(POLICY)


def fee_per_share(price: float) -> float:
    p = float(price)
    if not math.isfinite(p) or not 0.0 < p < 1.0:
        raise ValueError("price must be finite and strictly between zero and one")
    return POLICY["fee_rate"] * p * (1.0 - p)


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def evaluate_market(
    signal: Mapping[str, Any] | None,
    arrival: Mapping[str, Any] | None,
    *,
    outcome: str | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "selected_side": None,
        "signal_ask": None,
        "arrival_ask": None,
        "arrival_ask_size": None,
        "signal": False,
        "hypothetical_fok_fill": False,
        "decision": "no_signal_missing_signal_book",
        "won": None,
        "fee_per_share": None,
        "pnl_per_share": None,
        "pnl_at_five_shares": None,
    }
    if signal is None:
        return result

    up_ask = _finite(signal.get("au"))
    down_ask = _finite(signal.get("ad"))
    if up_ask is None or down_ask is None or not (0.0 < up_ask < 1.0 and 0.0 < down_ask < 1.0):
        result["decision"] = "no_signal_invalid_signal_book"
        return result
    if math.isclose(up_ask, down_ask, rel_tol=0.0, abs_tol=1e-12):
        result["decision"] = "no_signal_tied_favorite"
        return result

    selected_side = "Up" if up_ask > down_ask else "Down"
    signal_ask = up_ask if selected_side == "Up" else down_ask
    result.update({"selected_side": selected_side, "signal_ask": signal_ask})
    if signal_ask < POLICY["signal_ask_min"]:
        result["decision"] = "no_signal_below_threshold"
        return result
    result["signal"] = True

    if arrival is None:
        result["decision"] = "signal_missing_arrival_book"
        return result
    ask_column = "au" if selected_side == "Up" else "ad"
    size_column = "sau" if selected_side == "Up" else "sad"
    arrival_ask = _finite(arrival.get(ask_column))
    arrival_size = _finite(arrival.get(size_column))
    result.update({"arrival_ask": arrival_ask, "arrival_ask_size": arrival_size})
    if arrival_ask is None or not 0.0 < arrival_ask < 1.0:
        result["decision"] = "signal_invalid_arrival_ask"
        return result

    cancel_floor = signal_ask - POLICY["cancel_below_signal_by_more_than"]
    if arrival_ask < cancel_floor - 1e-12:
        result["decision"] = "cancel_adverse_move"
        return result
    if arrival_ask > signal_ask + 1e-12:
        result["decision"] = "no_fill_ask_above_frozen_limit"
        return result
    if arrival_size is None or arrival_size < POLICY["shares"]:
        result["decision"] = "no_fill_insufficient_displayed_depth"
        return result

    result["hypothetical_fok_fill"] = True
    result["decision"] = "hypothetical_fok_fill"
    normalized_outcome = str(outcome).title() if outcome is not None else None
    if normalized_outcome in {"Up", "Down"}:
        won = selected_side == normalized_outcome
        fee = fee_per_share(arrival_ask)
        pnl_per_share = float(won) - arrival_ask - fee
        result.update(
            {
                "won": won,
                "fee_per_share": fee,
                "pnl_per_share": pnl_per_share,
                "pnl_at_five_shares": pnl_per_share * POLICY["shares"],
            }
        )
    return result


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_id_hash(values: pd.Series) -> str:
    ids = sorted({str(value) for value in values.dropna()})
    canonical = (("\n".join(ids) + "\n") if ids else "").encode()
    return _sha256_bytes(canonical)


def verify_candidate_spec(path: Path) -> str:
    raw = path.read_bytes()
    payload = json.loads(raw)
    expected = {
        "assets": ["btc", "eth"],
        "entry_second": 210,
        "signal_ask_min": 0.85,
        "latency_seconds": 1,
        "fok_limit": "signal_ask",
        "shares": 5,
        "hold": "settlement",
        "fee_per_share": "0.07*p*(1-p)",
        "live_submission": "disabled",
        "max_positions_per_asset_per_window": 1,
        "max_total_positions_per_window": 2,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise RuntimeError(f"candidate spec mismatch for {key}: {payload.get(key)!r} != {value!r}")
    cancel = payload.get("arrival_adverse_move_cancel") or {}
    if cancel.get("max_price_improvement") != 0.01:
        raise RuntimeError("candidate spec cancel threshold mismatch")
    return _sha256_bytes(raw)


def build_market_ledger(asset: str, markets_path: Path, ticks_path: Path) -> pd.DataFrame:
    asset = asset.lower()
    if asset not in ASSETS:
        raise ValueError(f"unsupported asset: {asset}")

    markets = pd.read_parquet(markets_path)
    required_market_columns = {"condition_id", "market_start", "outcome"}
    missing_market_columns = sorted(required_market_columns - set(markets.columns))
    if missing_market_columns:
        raise RuntimeError(f"market source missing columns: {missing_market_columns}")
    for optional in ("event_id", "slug", "market_end"):
        if optional not in markets.columns:
            markets[optional] = None
    markets = markets[["condition_id", "event_id", "slug", "market_start", "market_end", "outcome"]].copy()
    markets["market_start"] = pd.to_datetime(markets["market_start"], utc=True)
    markets["market_start_s"] = markets["market_start"].astype("int64") // 1_000_000_000
    markets = markets.sort_values(["market_start", "condition_id"]).drop_duplicates("condition_id", keep="last")

    tick_columns = ["condition_id", "t", "bu", "au", "bd", "ad", "sau", "sad"]
    ticks = pd.read_parquet(ticks_path, columns=tick_columns)
    starts = markets.set_index("condition_id")["market_start_s"]
    ticks["market_start_s"] = ticks["condition_id"].map(starts)
    ticks = ticks.loc[ticks["market_start_s"].notna()].copy()
    ticks["elapsed"] = ticks["t"].astype("int64") - ticks["market_start_s"].astype("int64")
    signal_second = POLICY["entry_second"]
    arrival_second = signal_second + POLICY["latency_seconds"]
    ticks = ticks.loc[ticks["elapsed"].isin({signal_second, arrival_second})].copy()
    duplicates = ticks.duplicated(["condition_id", "elapsed"], keep=False)
    if duplicates.any():
        examples = ticks.loc[duplicates, ["condition_id", "elapsed"]].head(10).to_dict("records")
        raise RuntimeError(f"duplicate exact-second observations: {examples}")
    indexed = {(str(row.condition_id), int(row.elapsed)): row._asdict() for row in ticks.itertuples(index=False)}

    rows: list[dict[str, Any]] = []
    for market in markets.itertuples(index=False):
        condition_id = str(market.condition_id)
        decision = evaluate_market(
            indexed.get((condition_id, signal_second)),
            indexed.get((condition_id, arrival_second)),
            outcome=market.outcome,
        )
        rows.append(
            {
                "asset": asset,
                "condition_id": condition_id,
                "event_id": None if market.event_id is None else str(market.event_id),
                "slug": None if market.slug is None else str(market.slug),
                "market_start": market.market_start,
                "market_end": market.market_end,
                "inferred_outcome": market.outcome,
                **decision,
            }
        )
    return pd.DataFrame(rows)


def _download_asset(asset: str, cache_dir: Path) -> tuple[Path, Path]:
    markets = hf_hub_download(
        repo_id=DATASET_REPO,
        repo_type="dataset",
        filename=f"{asset}_markets.parquet",
        local_dir=cache_dir,
    )
    ticks = hf_hub_download(
        repo_id=DATASET_REPO,
        repo_type="dataset",
        filename=f"{asset}_ticks.parquet",
        local_dir=cache_dir,
    )
    return Path(markets), Path(ticks)


def run_audit(candidate_spec: Path, out_dir: Path, cache_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    policy_sha256 = verify_candidate_spec(candidate_spec)
    ledgers: list[pd.DataFrame] = []
    source_files: dict[str, str] = {}
    for asset in ASSETS:
        markets_path, ticks_path = _download_asset(asset, cache_dir)
        source_files[f"{asset}_markets"] = _sha256_bytes(markets_path.read_bytes())
        source_files[f"{asset}_ticks"] = _sha256_bytes(ticks_path.read_bytes())
        ledgers.append(build_market_ledger(asset, markets_path, ticks_path))

    ledger = pd.concat(ledgers, ignore_index=True).sort_values(["market_start", "asset", "condition_id"])
    eligible = ledger.loc[ledger["hypothetical_fok_fill"]].copy()
    ledger_path = out_dir / "market_ledger.csv.gz"
    eligible_path = out_dir / "eligible_trades.csv.gz"
    compression = {"method": "gzip", "mtime": 0}
    ledger.to_csv(ledger_path, index=False, compression=compression)
    eligible.to_csv(eligible_path, index=False, compression=compression)

    by_asset: dict[str, Any] = {}
    for asset, frame in ledger.groupby("asset", sort=True):
        fills = frame.loc[frame["hypothetical_fok_fill"]]
        by_asset[asset] = {
            "markets": int(len(frame)),
            "signals": int(frame["signal"].sum()),
            "hypothetical_fok_fills": int(frame["hypothetical_fok_fill"].sum()),
            "inferred_label_wins": int(fills["won"].fillna(False).sum()),
            "inferred_label_pnl_at_five_shares": float(fills["pnl_at_five_shares"].sum()),
            "first_market_start": str(frame["market_start"].min()),
            "last_market_start": str(frame["market_start"].max()),
            "all_condition_ids_sha256": _canonical_id_hash(frame["condition_id"]),
            "filled_condition_ids_sha256": _canonical_id_hash(fills["condition_id"]),
        }

    audit: dict[str, Any] = {
        "candidate": "late_favorite_btc_eth_v2_diagnostic",
        "candidate_spec_sha256": policy_sha256,
        "dataset_repo": DATASET_REPO,
        "source_files_sha256": source_files,
        "source_module_sha256": _sha256_bytes(Path(__file__).read_bytes()),
        "policy": frozen_policy(),
        "markets": int(len(ledger)),
        "signals": int(ledger["signal"].sum()),
        "hypothetical_fok_fills": int(ledger["hypothetical_fok_fill"].sum()),
        "all_condition_ids_sha256": _canonical_id_hash(ledger["condition_id"]),
        "filled_condition_ids_sha256": _canonical_id_hash(eligible["condition_id"]),
        "decision_counts": {
            str(key): int(value)
            for key, value in ledger["decision"].value_counts(dropna=False).sort_index().items()
        },
        "by_asset": by_asset,
        "outcomes": "dataset-inferred; not admission evidence",
        "official_outcomes_used": 0,
        "live_submission": "physically_absent",
        "split_reproduction": "not claimed: original deep-EDA split manifest/source is absent",
        "future_outcomes_used_for_signal": 0,
    }
    audit_path = out_dir / "AUDIT.json"
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True, default=list) + "\n")

    report = (
        "# Late-Favorite BTC/ETH Reproducibility Audit\n\n"
        "## Scope\n\n"
        "This checkpoint applies the frozen 210-second BTC/ETH rule to every market in the public source corpus and binds the resulting market sets by SHA-256. It does **not** claim to reproduce the previously reported final-test split because the original split manifest and exact deep-EDA source were not preserved in the branch.\n\n"
        f"- Markets: {len(ledger):,}\n"
        f"- Signals: {int(ledger['signal'].sum()):,}\n"
        f"- Hypothetical five-share FOK fills: {int(ledger['hypothetical_fok_fill'].sum()):,}\n"
        f"- All-condition-set SHA-256: `{audit['all_condition_ids_sha256']}`\n"
        f"- Filled-condition-set SHA-256: `{audit['filled_condition_ids_sha256']}`\n\n"
        "## Evidence boundary\n\n"
        "PnL in this artifact uses the dataset's inferred outcomes only. It is diagnostic and cannot satisfy official-label transfer or prospective admission. No credentials, authenticated request, or order-submission implementation exists in this checkpoint.\n"
    )
    report_path = out_dir / "REPORT.md"
    report_path.write_text(report)

    outputs = [audit_path, eligible_path, ledger_path, report_path]
    sums = "".join(f"{_sha256_bytes(path.read_bytes())}  {path.name}\n" for path in sorted(outputs))
    (out_dir / "SHA256SUMS").write_text(sums)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-spec", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    audit = run_audit(args.candidate_spec, args.out_dir, args.cache_dir)
    print(json.dumps(audit, indent=2, sort_keys=True, default=list))


if __name__ == "__main__":
    main()
