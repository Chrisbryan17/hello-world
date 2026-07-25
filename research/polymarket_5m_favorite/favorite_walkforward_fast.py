from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd

import favorite_walkforward as study


def prepare_static_slice(frame: pd.DataFrame, entry_second: int, latency_seconds: int) -> pd.DataFrame:
    execution_ask = frame["execution_ask"].to_numpy(dtype=float)
    mask = (
        (frame["entry_second"].to_numpy() == entry_second)
        & (frame["latency_seconds"].to_numpy() == latency_seconds)
        & np.isfinite(execution_ask)
        & (execution_ask > 0.0)
        & (frame["execution_ask_size"].fillna(0.0).to_numpy(dtype=float) >= study.SHARES)
        & (frame["n_ticks"].fillna(0).to_numpy(dtype=float) >= study.MIN_TICKS)
        & (frame["final_confidence"].fillna(0.0).to_numpy(dtype=float) >= study.MIN_FINAL_CONFIDENCE)
        & frame["outcome"].notna().to_numpy()
        & frame["won"].notna().to_numpy()
    )
    return frame.loc[mask].copy()


def score_slice(base: pd.DataFrame, ask_threshold: float, limit_buffer: float) -> pd.DataFrame:
    if base.empty:
        return base.copy()
    signal_ask = base["signal_ask"].to_numpy(dtype=float)
    execution_ask = base["execution_ask"].to_numpy(dtype=float)
    limit = np.minimum(0.99, signal_ask + limit_buffer)
    mask = (signal_ask >= ask_threshold) & (execution_ask <= limit + 1e-12)
    selected = base.loc[mask].copy()
    if selected.empty:
        selected["all_in_cost_per_share"] = pd.Series(dtype=float)
        selected["pnl_per_share"] = pd.Series(dtype=float)
        selected["pnl_five_shares"] = pd.Series(dtype=float)
        return selected
    adjusted_ask = selected["execution_ask"].to_numpy(dtype=float)
    cost = adjusted_ask + study.fee(adjusted_ask)
    selected["adjusted_execution_ask"] = adjusted_ask
    selected["all_in_cost_per_share"] = cost
    selected["pnl_per_share"] = selected["won"].astype(float).to_numpy() - cost
    selected["pnl_five_shares"] = selected["pnl_per_share"] * study.SHARES
    return selected


def fast_find_global_config(frame: pd.DataFrame) -> tuple[study.Config, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    best: tuple[float, study.Config] | None = None
    for entry_second, latency_seconds in itertools.product(study.ENTRY_SECONDS, study.LATENCIES):
        base = prepare_static_slice(frame, entry_second, latency_seconds)
        print(
            f"[favorite-fast] second={entry_second} latency={latency_seconds} static_rows={len(base)}",
            flush=True,
        )
        for ask_threshold, limit_buffer in itertools.product(study.ASK_THRESHOLDS, study.LIMIT_BUFFERS):
            config = study.Config(entry_second, ask_threshold, latency_seconds, limit_buffer)
            selected = score_slice(base, ask_threshold, limit_buffer)
            train = selected[selected["segment"] == "train"]
            validation = selected[selected["segment"] == "validation"]
            train_metrics = study.metrics(train)
            validation_metrics = study.metrics(validation)
            positive_validation_assets = sum(
                1
                for asset in study.ASSETS
                if not validation[validation["asset"] == asset].empty
                and float(validation.loc[validation["asset"] == asset, "pnl_per_share"].mean()) > 0.0
            )
            row = {
                **study.asdict(config),
                **{f"train_{key}": value for key, value in train_metrics.items()},
                **{f"validation_{key}": value for key, value in validation_metrics.items()},
                "positive_validation_assets": positive_validation_assets,
            }
            rows.append(row)
            qualifies = (
                train_metrics["trades"] >= study.MIN_TRAIN_TRADES
                and validation_metrics["trades"] >= study.MIN_VALIDATION_TRADES
                and train_metrics["mean_pnl_per_share"] is not None
                and validation_metrics["mean_pnl_per_share"] is not None
                and train_metrics["mean_pnl_per_share"] > 0.0
                and validation_metrics["mean_pnl_per_share"] > 0.0
                and validation_metrics["positive_day_fraction"] is not None
                and validation_metrics["positive_day_fraction"] >= 0.55
                and positive_validation_assets >= 4
            )
            if not qualifies:
                continue
            train_score = study.daily_score(train)
            validation_score = study.daily_score(validation)
            score = min(train_score, validation_score)
            if math.isfinite(score) and (best is None or score > best[0]):
                best = (score, config)
        del base
    grid = pd.DataFrame(rows)
    if best is None:
        raise RuntimeError("no global configuration passed the frozen train/validation requirements")
    print(f"[favorite-fast] selected={best[1]} score={best[0]:.6f}", flush=True)
    return best[1], grid


if __name__ == "__main__":
    study.find_global_config = fast_find_global_config
    study.main()
