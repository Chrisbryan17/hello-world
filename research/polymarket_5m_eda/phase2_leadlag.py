from __future__ import annotations

import gc
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

ASSETS = ["eth", "sol", "xrp", "doge", "hype", "bnb"]
FEE_COEFFICIENT = 0.07
LAGS = [1, 2, 3, 5, 10]
HOLDS = [1, 2, 3, 5, 10, 15, 30]
LATENCIES = [0, 1, 2]
QUANTILES = [0.99, 0.995, 0.999, 0.9995]
IMBALANCE_FILTERS = [-1.0, 0.0, 0.2]
SHARES = 5.0
MIN_VALIDATION_TRADES = 100
RANDOM_SEED = 20260725


@dataclass(frozen=True)
class StrategyConfig:
    asset: str
    lag_seconds: int
    hold_seconds: int
    latency_seconds: int
    threshold_quantile: float
    threshold_value: float
    imbalance_filter: float
    beta: float
    residual_scale: float


def fee(price: np.ndarray) -> np.ndarray:
    return FEE_COEFFICIENT * price * (1.0 - price)


def max_drawdown(values: np.ndarray) -> float:
    if len(values) == 0:
        return 0.0
    curve = np.cumsum(values)
    peaks = np.maximum.accumulate(np.concatenate(([0.0], curve)))
    padded = np.concatenate(([0.0], curve))
    return float(np.min(padded - peaks))


def metrics(indices: np.ndarray, pnl: np.ndarray, days: np.ndarray) -> dict[str, Any]:
    if len(indices) == 0:
        return {
            "trades": 0,
            "active_days": 0,
            "sum_pnl_five_shares": 0.0,
            "mean_pnl_per_share": None,
            "median_pnl_per_share": None,
            "win_rate": None,
            "daily_mean_pnl_five_shares": None,
            "daily_t_stat": None,
            "max_drawdown_five_shares": 0.0,
        }
    trade_pnl = pnl * SHARES
    trade_days = days[indices]
    unique_days, inverse = np.unique(trade_days, return_inverse=True)
    daily = np.bincount(inverse, weights=trade_pnl)
    daily_mean = float(np.mean(daily))
    daily_std = float(np.std(daily, ddof=1)) if len(daily) > 1 else 0.0
    daily_t = daily_mean / (daily_std / math.sqrt(len(daily))) if daily_std > 0 else None
    return {
        "trades": int(len(indices)),
        "active_days": int(len(unique_days)),
        "sum_pnl_five_shares": float(np.sum(trade_pnl)),
        "mean_pnl_per_share": float(np.mean(pnl)),
        "median_pnl_per_share": float(np.median(pnl)),
        "win_rate": float(np.mean(pnl > 0.0)),
        "daily_mean_pnl_five_shares": daily_mean,
        "daily_t_stat": None if daily_t is None else float(daily_t),
        "max_drawdown_five_shares": max_drawdown(trade_pnl),
    }


def bootstrap_daily_ci(indices: np.ndarray, pnl: np.ndarray, days: np.ndarray, repeats: int = 2000) -> dict[str, Any]:
    if len(indices) == 0:
        return {"lower_95": None, "upper_95": None, "probability_positive": None}
    trade_days = days[indices]
    unique_days, inverse = np.unique(trade_days, return_inverse=True)
    daily = np.bincount(inverse, weights=pnl * SHARES)
    rng = np.random.default_rng(RANDOM_SEED)
    means = np.empty(repeats, dtype=float)
    for iteration in range(repeats):
        sample = rng.choice(daily, size=len(daily), replace=True)
        means[iteration] = np.mean(sample)
    return {
        "lower_95": float(np.quantile(means, 0.025)),
        "upper_95": float(np.quantile(means, 0.975)),
        "probability_positive": float(np.mean(means > 0.0)),
    }


def bh_adjust(p_values: list[float]) -> list[float]:
    count = len(p_values)
    order = np.argsort(p_values)
    adjusted = np.empty(count, dtype=float)
    running = 1.0
    for reverse_rank, index in enumerate(order[::-1], start=1):
        rank = count - reverse_rank + 1
        candidate = p_values[index] * count / rank
        running = min(running, candidate)
        adjusted[index] = min(1.0, running)
    return adjusted.tolist()


def select_one_per_market(
    indices: np.ndarray,
    pnl: np.ndarray,
    buckets: np.ndarray,
    cooldown_seconds: int,
) -> tuple[np.ndarray, np.ndarray]:
    if len(indices) == 0:
        return indices, pnl
    selected_positions: list[int] = []
    next_allowed = -1
    previous_bucket = None
    for position, index in enumerate(indices):
        bucket = int(buckets[index])
        if index < next_allowed or bucket == previous_bucket:
            continue
        selected_positions.append(position)
        next_allowed = int(index) + cooldown_seconds + 1
        previous_bucket = bucket
    positions = np.asarray(selected_positions, dtype=np.int64)
    return indices[positions], pnl[positions]


def evaluate_config(
    *,
    z: np.ndarray,
    threshold: float,
    segment_mask: np.ndarray,
    lag_valid: np.ndarray,
    latency: int,
    hold: int,
    imbalance_filter: float,
    t: np.ndarray,
    bucket: np.ndarray,
    au: np.ndarray,
    bu: np.ndarray,
    ad: np.ndarray,
    bd: np.ndarray,
    sau: np.ndarray,
    su: np.ndarray,
    sad: np.ndarray,
    sd: np.ndarray,
    slippage: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    candidates = np.flatnonzero(segment_mask & lag_valid & np.isfinite(z) & (np.abs(z) >= threshold))
    if len(candidates) == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=float)
    entry = candidates + latency
    exit_index = entry + hold
    inside = exit_index < len(t)
    candidates = candidates[inside]
    entry = entry[inside]
    exit_index = exit_index[inside]
    if len(candidates) == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=float)
    contiguous = (
        (t[entry] - t[candidates] == latency)
        & (t[exit_index] - t[entry] == hold)
        & (bucket[candidates] == bucket[entry])
        & (bucket[entry] == bucket[exit_index])
    )
    candidates = candidates[contiguous]
    entry = entry[contiguous]
    exit_index = exit_index[contiguous]
    if len(candidates) == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=float)

    direction_up = z[candidates] > 0.0
    entry_ask = np.where(direction_up, au[entry], ad[entry])
    exit_bid = np.where(direction_up, bu[exit_index], bd[exit_index])
    entry_size = np.where(direction_up, sau[entry], sad[entry])
    exit_size = np.where(direction_up, su[exit_index], sd[exit_index])
    bid_size = np.where(direction_up, su[entry], sd[entry])
    ask_size = np.where(direction_up, sau[entry], sad[entry])
    denominator = bid_size + ask_size
    imbalance = np.divide(
        bid_size - ask_size,
        denominator,
        out=np.full_like(denominator, np.nan, dtype=float),
        where=denominator > 0.0,
    )
    executable = (
        np.isfinite(entry_ask)
        & np.isfinite(exit_bid)
        & (entry_ask > 0.0)
        & (entry_ask < 1.0)
        & (exit_bid > 0.0)
        & (exit_bid < 1.0)
        & np.isfinite(entry_size)
        & np.isfinite(exit_size)
        & (entry_size >= SHARES)
        & (exit_size >= SHARES)
        & np.isfinite(imbalance)
        & (imbalance >= imbalance_filter)
    )
    candidates = candidates[executable]
    entry_ask = entry_ask[executable]
    exit_bid = exit_bid[executable]
    if len(candidates) == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=float)

    adjusted_entry = np.minimum(0.99, entry_ask + slippage)
    adjusted_exit = np.maximum(0.01, exit_bid - slippage)
    pnl = adjusted_exit - adjusted_entry - fee(adjusted_entry) - fee(adjusted_exit)
    return select_one_per_market(candidates, pnl, bucket, latency + hold)


def read_pair(connection: duckdb.DuckDBPyConnection, data_dir: Path, asset: str) -> pd.DataFrame:
    btc = str((data_dir / "btc_ticks.parquet").resolve()).replace("'", "''")
    target = str((data_dir / f"{asset}_ticks.parquet").resolve()).replace("'", "''")
    query = f"""
    SELECT
        b.t::BIGINT AS t,
        floor(b.t / 300)::BIGINT AS market_bucket,
        ((b.bu + b.au) / 2.0)::DOUBLE AS btc_mid,
        ((x.bu + x.au) / 2.0)::DOUBLE AS target_mid,
        x.au::DOUBLE AS au,
        x.bu::DOUBLE AS bu,
        x.ad::DOUBLE AS ad,
        x.bd::DOUBLE AS bd,
        coalesce(x.sau, 0.0)::DOUBLE AS sau,
        coalesce(x.su, 0.0)::DOUBLE AS su,
        coalesce(x.sad, 0.0)::DOUBLE AS sad,
        coalesce(x.sd, 0.0)::DOUBLE AS sd
    FROM read_parquet('{btc}') AS b
    INNER JOIN read_parquet('{target}') AS x USING (t)
    ORDER BY t
    """
    return connection.execute(query).fetchdf()


def chronological_masks(days: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    unique_days = np.unique(days)
    train_end = max(1, int(len(unique_days) * 0.60))
    validation_end = max(train_end + 1, int(len(unique_days) * 0.80))
    train_days = unique_days[:train_end]
    validation_days = unique_days[train_end:validation_end]
    test_days = unique_days[validation_end:]
    train = np.isin(days, train_days)
    validation = np.isin(days, validation_days)
    test = np.isin(days, test_days)
    description = {
        "unique_days": int(len(unique_days)),
        "train_days": [int(train_days[0]), int(train_days[-1])],
        "validation_days": [int(validation_days[0]), int(validation_days[-1])],
        "test_days": [int(test_days[0]), int(test_days[-1])],
    }
    return train, validation, test, description


def lead_lag_correlations(
    btc_logit: np.ndarray,
    target_logit: np.ndarray,
    t: np.ndarray,
    bucket: np.ndarray,
    test_mask: np.ndarray,
    asset: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    btc_impulse = btc_logit - np.roll(btc_logit, 1)
    target_impulse = target_logit - np.roll(target_logit, 1)
    base_valid = np.arange(len(t)) > 0
    base_valid &= (t - np.roll(t, 1) == 1) & (bucket == np.roll(bucket, 1))
    for horizon in [1, 2, 3, 5, 10]:
        future_index = np.arange(len(t)) + horizon
        valid = base_valid & test_mask & (future_index < len(t))
        valid_indices = np.flatnonzero(valid)
        future_index = future_index[valid]
        same = (
            (t[future_index] - t[valid_indices] == horizon)
            & (bucket[future_index] == bucket[valid_indices])
        )
        valid_indices = valid_indices[same]
        future_index = future_index[same]
        if len(valid_indices) < 100:
            continue
        target_future = target_logit[future_index] - target_logit[valid_indices]
        btc_future = btc_logit[future_index] - btc_logit[valid_indices]
        forward = float(np.corrcoef(btc_impulse[valid_indices], target_future)[0, 1])
        reverse = float(np.corrcoef(target_impulse[valid_indices], btc_future)[0, 1])
        rows.append(
            {
                "asset": asset,
                "horizon_seconds": horizon,
                "btc_to_target_correlation": forward,
                "target_to_btc_correlation": reverse,
                "btc_lead_advantage": abs(forward) - abs(reverse),
                "observations": int(len(valid_indices)),
            }
        )
    return rows


def run_asset(connection: duckdb.DuckDBPyConnection, data_dir: Path, asset: str) -> dict[str, Any]:
    print(f"[phase2] loading BTC/{asset}", flush=True)
    frame = read_pair(connection, data_dir, asset)
    arrays = {column: frame[column].to_numpy() for column in frame.columns}
    del frame
    gc.collect()

    t = arrays["t"].astype(np.int64, copy=False)
    bucket = arrays["market_bucket"].astype(np.int64, copy=False)
    days = t // 86_400
    btc_mid = np.clip(arrays["btc_mid"].astype(float), 0.01, 0.99)
    target_mid = np.clip(arrays["target_mid"].astype(float), 0.01, 0.99)
    btc_logit = np.log(btc_mid / (1.0 - btc_mid))
    target_logit = np.log(target_mid / (1.0 - target_mid))
    train_mask, validation_mask, test_mask, split_description = chronological_masks(days)

    correlations = lead_lag_correlations(
        btc_logit, target_logit, t, bucket, test_mask, asset
    )
    validation_grid: list[dict[str, Any]] = []
    best: tuple[float, StrategyConfig, dict[str, Any]] | None = None
    indices = np.arange(len(t))

    for lag in LAGS:
        shifted_btc = np.roll(btc_logit, lag)
        shifted_target = np.roll(target_logit, lag)
        btc_impulse = btc_logit - shifted_btc
        target_impulse = target_logit - shifted_target
        lag_valid = indices >= lag
        lag_valid &= (t - np.roll(t, lag) == lag)
        lag_valid &= bucket == np.roll(bucket, lag)
        fit_mask = train_mask & lag_valid & np.isfinite(btc_impulse) & np.isfinite(target_impulse)
        x = btc_impulse[fit_mask]
        y = target_impulse[fit_mask]
        variance = float(np.var(x))
        if variance <= 0.0:
            continue
        beta = float(np.cov(x, y, ddof=0)[0, 1] / variance)
        residual = beta * btc_impulse - target_impulse
        scale = float(np.std(residual[fit_mask]))
        if not math.isfinite(scale) or scale <= 0.0:
            continue
        z = residual / scale
        train_abs = np.abs(z[fit_mask])
        thresholds = {quantile: float(np.quantile(train_abs, quantile)) for quantile in QUANTILES}

        for quantile, threshold in thresholds.items():
            for latency in LATENCIES:
                for hold in HOLDS:
                    for imbalance_filter in IMBALANCE_FILTERS:
                        trade_indices, trade_pnl = evaluate_config(
                            z=z,
                            threshold=threshold,
                            segment_mask=validation_mask,
                            lag_valid=lag_valid,
                            latency=latency,
                            hold=hold,
                            imbalance_filter=imbalance_filter,
                            t=t,
                            bucket=bucket,
                            au=arrays["au"],
                            bu=arrays["bu"],
                            ad=arrays["ad"],
                            bd=arrays["bd"],
                            sau=arrays["sau"],
                            su=arrays["su"],
                            sad=arrays["sad"],
                            sd=arrays["sd"],
                        )
                        result = metrics(trade_indices, trade_pnl, days)
                        config = StrategyConfig(
                            asset=asset,
                            lag_seconds=lag,
                            hold_seconds=hold,
                            latency_seconds=latency,
                            threshold_quantile=quantile,
                            threshold_value=threshold,
                            imbalance_filter=imbalance_filter,
                            beta=beta,
                            residual_scale=scale,
                        )
                        row = {**asdict(config), **result}
                        validation_grid.append(row)
                        if (
                            result["trades"] >= MIN_VALIDATION_TRADES
                            and result["active_days"] >= 5
                            and result["sum_pnl_five_shares"] > 0.0
                            and result["daily_t_stat"] is not None
                        ):
                            score = float(result["daily_t_stat"])
                            if best is None or score > best[0]:
                                best = (score, config, result)

    if best is None:
        return {
            "asset": asset,
            "split": split_description,
            "selected": None,
            "validation_grid": validation_grid,
            "correlations": correlations,
            "test_trades": [],
        }

    _, selected, validation_metrics = best
    lag = selected.lag_seconds
    btc_impulse = btc_logit - np.roll(btc_logit, lag)
    target_impulse = target_logit - np.roll(target_logit, lag)
    lag_valid = indices >= lag
    lag_valid &= (t - np.roll(t, lag) == lag)
    lag_valid &= bucket == np.roll(bucket, lag)
    z = (selected.beta * btc_impulse - target_impulse) / selected.residual_scale

    test_indices, test_pnl = evaluate_config(
        z=z,
        threshold=selected.threshold_value,
        segment_mask=test_mask,
        lag_valid=lag_valid,
        latency=selected.latency_seconds,
        hold=selected.hold_seconds,
        imbalance_filter=selected.imbalance_filter,
        t=t,
        bucket=bucket,
        au=arrays["au"],
        bu=arrays["bu"],
        ad=arrays["ad"],
        bd=arrays["bd"],
        sau=arrays["sau"],
        su=arrays["su"],
        sad=arrays["sad"],
        sd=arrays["sd"],
    )
    test_metrics = metrics(test_indices, test_pnl, days)
    bootstrap = bootstrap_daily_ci(test_indices, test_pnl, days)
    if len(test_indices):
        trade_days = days[test_indices]
        unique_days, inverse = np.unique(trade_days, return_inverse=True)
        daily = np.bincount(inverse, weights=test_pnl * SHARES)
        test_p_value = float(stats.ttest_1samp(daily, popmean=0.0, alternative="greater").pvalue) if len(daily) > 1 else 1.0
    else:
        test_p_value = 1.0

    stress: list[dict[str, Any]] = []
    for slippage in [0.0, 0.0025, 0.005, 0.01]:
        stress_indices, stress_pnl = evaluate_config(
            z=z,
            threshold=selected.threshold_value,
            segment_mask=test_mask,
            lag_valid=lag_valid,
            latency=selected.latency_seconds,
            hold=selected.hold_seconds,
            imbalance_filter=selected.imbalance_filter,
            t=t,
            bucket=bucket,
            au=arrays["au"],
            bu=arrays["bu"],
            ad=arrays["ad"],
            bd=arrays["bd"],
            sau=arrays["sau"],
            su=arrays["su"],
            sad=arrays["sad"],
            sd=arrays["sd"],
            slippage=slippage,
        )
        stress.append({"slippage_per_side": slippage, **metrics(stress_indices, stress_pnl, days)})

    test_trades = [
        {
            "asset": asset,
            "signal_t": int(t[index]),
            "market_bucket": int(bucket[index]),
            "day": int(days[index]),
            "pnl_per_share": float(pnl),
            "pnl_five_shares": float(pnl * SHARES),
        }
        for index, pnl in zip(test_indices, test_pnl)
    ]
    return {
        "asset": asset,
        "split": split_description,
        "selected": {
            **asdict(selected),
            "validation": validation_metrics,
            "test": test_metrics,
            "test_daily_bootstrap": bootstrap,
            "test_one_sided_daily_p_value": test_p_value,
            "stress": stress,
        },
        "validation_grid": validation_grid,
        "correlations": correlations,
        "test_trades": test_trades,
    }


def portfolio_metrics(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {"trades": 0, "sum_pnl_five_shares": 0.0}
    trades = trades.sort_values(["signal_t", "asset"], kind="mergesort")
    daily = trades.groupby("day", sort=True)["pnl_five_shares"].sum()
    daily_t = (
        float(daily.mean() / (daily.std(ddof=1) / math.sqrt(len(daily))))
        if len(daily) > 1 and daily.std(ddof=1) > 0
        else None
    )
    return {
        "trades": int(len(trades)),
        "assets": sorted(trades["asset"].unique().tolist()),
        "active_days": int(daily.size),
        "sum_pnl_five_shares": float(trades["pnl_five_shares"].sum()),
        "mean_pnl_per_share": float(trades["pnl_per_share"].mean()),
        "win_rate": float((trades["pnl_per_share"] > 0).mean()),
        "daily_mean_pnl_five_shares": float(daily.mean()),
        "daily_t_stat": daily_t,
        "max_drawdown_five_shares": max_drawdown(trades["pnl_five_shares"].to_numpy()),
    }


def write_report(summary: dict[str, Any], output_dir: Path) -> None:
    selected = pd.DataFrame(summary["selected_configs"])
    lines = [
        "# BTC → Altcoin Lead–Lag EDA",
        "",
        "Each target asset is searched only on its training/validation chronology. One configuration",
        "per asset is frozen on validation and evaluated once on the final untouched date segment.",
        "Trades cross the observed ask, exit at the observed bid, pay the fee approximation on both",
        "sides, require five shares at both entry and exit, and allow at most one trade per market.",
        "",
        "## Untouched test results",
        "",
    ]
    if selected.empty:
        lines.append("No asset produced a validation-qualified configuration.")
    else:
        columns = [
            "asset",
            "lag_seconds",
            "hold_seconds",
            "latency_seconds",
            "threshold_quantile",
            "imbalance_filter",
            "test_trades",
            "test_sum_pnl_five_shares",
            "test_mean_pnl_per_share",
            "test_daily_t_stat",
            "test_fdr_p_value",
        ]
        lines.append(selected[columns].to_markdown(index=False))
    lines.extend(
        [
            "",
            "## Combined selected portfolio",
            "",
            "```json",
            json.dumps(summary["combined_test_portfolio"], indent=2),
            "```",
            "",
            "## Research controls",
            "",
            "- Configuration selection uses validation only; test dates are untouched until one final evaluation.",
            "- Signals are derived from BTC and target implied-probability changes, not realized outcomes.",
            "- Entry latency, spread crossing, fees, size, cooldown, and market-boundary checks are enforced.",
            "- Test significance is computed on daily P&L blocks and adjusted across the six selected assets.",
            "- This dataset does not identify queue position or guarantee fills; positive results still require prospective shadow execution.",
            "",
        ]
    )
    (output_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    output_dir = Path("results/phase2_leadlag")
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path("data")
    connection = duckdb.connect()
    connection.execute("PRAGMA threads=4")
    connection.execute("PRAGMA memory_limit='12GB'")

    asset_results: list[dict[str, Any]] = []
    grids: list[dict[str, Any]] = []
    correlations: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    for asset in ASSETS:
        result = run_asset(connection, data_dir, asset)
        asset_results.append(result)
        grids.extend(result["validation_grid"])
        correlations.extend(result["correlations"])
        trades.extend(result["test_trades"])
        del result
        gc.collect()

    selected_results = [result for result in asset_results if result["selected"] is not None]
    raw_p_values = [result["selected"]["test_one_sided_daily_p_value"] for result in selected_results]
    adjusted = bh_adjust(raw_p_values) if raw_p_values else []
    selected_rows: list[dict[str, Any]] = []
    for result, adjusted_p in zip(selected_results, adjusted):
        selected = result["selected"]
        test = selected["test"]
        selected_rows.append(
            {
                "asset": result["asset"],
                "lag_seconds": selected["lag_seconds"],
                "hold_seconds": selected["hold_seconds"],
                "latency_seconds": selected["latency_seconds"],
                "threshold_quantile": selected["threshold_quantile"],
                "threshold_value": selected["threshold_value"],
                "imbalance_filter": selected["imbalance_filter"],
                "beta": selected["beta"],
                "residual_scale": selected["residual_scale"],
                "validation_trades": selected["validation"]["trades"],
                "validation_sum_pnl_five_shares": selected["validation"]["sum_pnl_five_shares"],
                "validation_daily_t_stat": selected["validation"]["daily_t_stat"],
                "test_trades": test["trades"],
                "test_sum_pnl_five_shares": test["sum_pnl_five_shares"],
                "test_mean_pnl_per_share": test["mean_pnl_per_share"],
                "test_win_rate": test["win_rate"],
                "test_daily_t_stat": test["daily_t_stat"],
                "test_raw_p_value": selected["test_one_sided_daily_p_value"],
                "test_fdr_p_value": adjusted_p,
                "test_bootstrap_lower_95_daily_pnl": selected["test_daily_bootstrap"]["lower_95"],
                "test_bootstrap_upper_95_daily_pnl": selected["test_daily_bootstrap"]["upper_95"],
            }
        )

    trades_frame = pd.DataFrame(trades)
    summary = {
        "fee_coefficient": FEE_COEFFICIENT,
        "shares_per_trade": SHARES,
        "selection_rule": "maximum validation daily t-stat with >=100 trades, >=5 active days, and positive validation P&L",
        "selected_configs": selected_rows,
        "combined_test_portfolio": portfolio_metrics(trades_frame),
        "asset_results": asset_results,
    }
    pd.DataFrame(grids).to_csv(output_dir / "validation_grid.csv", index=False)
    pd.DataFrame(correlations).to_csv(output_dir / "lead_lag_correlations.csv", index=False)
    pd.DataFrame(selected_rows).to_csv(output_dir / "selected_configs.csv", index=False)
    trades_frame.to_csv(output_dir / "test_trades.csv", index=False)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_report(summary, output_dir)
    print(json.dumps({"selected_assets": len(selected_rows), "combined": summary["combined_test_portfolio"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
