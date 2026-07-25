from __future__ import annotations

import itertools
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

ASSETS = ["btc", "eth", "sol", "xrp", "doge", "hype", "bnb"]
ENTRY_SECONDS = [30, 60, 90, 120, 150, 180, 210, 240, 270, 285]
ASK_THRESHOLDS = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
LATENCIES = [0, 1, 2, 3]
LIMIT_BUFFERS = [0.00, 0.01, 0.02]
FEE_COEFFICIENT = 0.07
SHARES = 5.0
MIN_TICKS = 295
MIN_FINAL_CONFIDENCE = 0.95
MIN_TRAIN_TRADES = 5_000
MIN_VALIDATION_TRADES = 1_000
RANDOM_SEED = 20260725


@dataclass(frozen=True)
class Config:
    entry_second: int
    ask_threshold: float
    latency_seconds: int
    limit_buffer: float


def fee(price: np.ndarray | float, multiplier: float = 1.0) -> np.ndarray | float:
    return multiplier * FEE_COEFFICIENT * price * (1.0 - price)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def max_drawdown(values: np.ndarray) -> float:
    if len(values) == 0:
        return 0.0
    curve = np.concatenate(([0.0], np.cumsum(values)))
    peak = np.maximum.accumulate(curve)
    return float(np.min(curve - peak))


def longest_loss_streak(values: np.ndarray) -> int:
    best = current = 0
    for value in values:
        if value < 0.0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def block_bootstrap_daily(daily: np.ndarray, repeats: int = 5_000) -> dict[str, Any]:
    if len(daily) == 0:
        return {"lower_95": None, "upper_95": None, "probability_positive": None}
    rng = np.random.default_rng(RANDOM_SEED)
    means = np.empty(repeats, dtype=float)
    for iteration in range(repeats):
        means[iteration] = float(np.mean(rng.choice(daily, size=len(daily), replace=True)))
    return {
        "lower_95": float(np.quantile(means, 0.025)),
        "upper_95": float(np.quantile(means, 0.975)),
        "probability_positive": float(np.mean(means > 0.0)),
    }


def metrics(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {
            "trades": 0,
            "active_days": 0,
            "sum_pnl_five_shares": 0.0,
            "mean_pnl_per_share": None,
            "median_pnl_per_share": None,
            "win_rate": None,
            "daily_mean_pnl_five_shares": None,
            "daily_t_stat": None,
            "positive_day_fraction": None,
            "max_drawdown_five_shares": 0.0,
            "longest_loss_streak": 0,
        }
    ordered = trades.sort_values(["execution_t", "asset", "condition_id"], kind="mergesort")
    pnl = ordered["pnl_per_share"].to_numpy(dtype=float)
    fixed_pnl = pnl * SHARES
    daily = ordered.groupby("day", sort=True)["pnl_five_shares"].sum().to_numpy(dtype=float)
    daily_std = float(np.std(daily, ddof=1)) if len(daily) > 1 else 0.0
    daily_t = float(np.mean(daily) / (daily_std / math.sqrt(len(daily)))) if daily_std > 0 else None
    return {
        "trades": int(len(ordered)),
        "active_days": int(len(daily)),
        "sum_pnl_five_shares": float(np.sum(fixed_pnl)),
        "mean_pnl_per_share": float(np.mean(pnl)),
        "median_pnl_per_share": float(np.median(pnl)),
        "win_rate": float(np.mean(pnl > 0.0)),
        "daily_mean_pnl_five_shares": float(np.mean(daily)),
        "daily_t_stat": daily_t,
        "positive_day_fraction": float(np.mean(daily > 0.0)),
        "max_drawdown_five_shares": max_drawdown(fixed_pnl),
        "longest_loss_streak": longest_loss_streak(fixed_pnl),
    }


def capital_metrics(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {
            "maximum_concurrent_trades": 0,
            "maximum_capital_at_risk": 0.0,
            "test_return_on_maximum_capital": None,
            "trades_per_hour": 0.0,
        }
    events: list[tuple[int, int, float]] = []
    for row in trades.itertuples(index=False):
        stake = float(row.all_in_cost_per_share * SHARES)
        events.append((int(row.execution_t), 1, stake))
        events.append((int(row.market_end_epoch), -1, -stake))
    events.sort(key=lambda item: (item[0], item[1]))
    concurrent = 0
    capital = 0.0
    max_concurrent = 0
    max_capital = 0.0
    for _, direction, amount in events:
        concurrent += direction
        capital += amount
        max_concurrent = max(max_concurrent, concurrent)
        max_capital = max(max_capital, capital)
    elapsed_hours = max(1.0 / 3600.0, (trades["execution_t"].max() - trades["execution_t"].min()) / 3600.0)
    total_pnl = float(trades["pnl_five_shares"].sum())
    return {
        "maximum_concurrent_trades": int(max_concurrent),
        "maximum_capital_at_risk": float(max_capital),
        "test_return_on_maximum_capital": None if max_capital <= 0 else total_pnl / max_capital,
        "trades_per_hour": float(len(trades) / elapsed_hours),
    }


def load_asset(connection: duckdb.DuckDBPyConnection, data_dir: Path, asset: str) -> pd.DataFrame:
    markets_path = str((data_dir / f"{asset}_markets.parquet").resolve()).replace("'", "''")
    ticks_path = str((data_dir / f"{asset}_ticks.parquet").resolve()).replace("'", "''")
    seconds = ",".join(str(value) for value in ENTRY_SECONDS)
    latencies = ",".join(f"({value})" for value in LATENCIES)
    query = f"""
    WITH markets AS (
        SELECT * FROM read_parquet('{markets_path}')
    ),
    ticks AS (
        SELECT * FROM read_parquet('{ticks_path}')
    ),
    terminal AS (
        SELECT
            condition_id,
            arg_max((bu + au) / 2.0, t) AS final_up_mid,
            arg_max((bd + ad) / 2.0, t) AS final_down_mid
        FROM ticks
        GROUP BY condition_id
    ),
    signal AS (
        SELECT
            m.condition_id,
            m.market_start,
            m.market_end,
            epoch(m.market_end)::BIGINT AS market_end_epoch,
            m.outcome,
            m.n_ticks,
            s.t::BIGINT AS signal_t,
            CAST(s.t - epoch(m.market_start) AS BIGINT) AS entry_second,
            CASE WHEN (s.bu + s.au) >= (s.bd + s.ad) THEN 'Up' ELSE 'Down' END AS favorite,
            CASE WHEN (s.bu + s.au) >= (s.bd + s.ad) THEN s.au ELSE s.ad END AS signal_ask,
            CASE WHEN (s.bu + s.au) >= (s.bd + s.ad) THEN s.sau ELSE s.sad END AS signal_ask_size,
            CASE WHEN m.outcome = 'Up' THEN terminal.final_up_mid ELSE terminal.final_down_mid END AS final_confidence,
            date_trunc('day', m.market_start) AS day
        FROM ticks AS s
        JOIN markets AS m USING (condition_id)
        JOIN terminal USING (condition_id)
        WHERE CAST(s.t - epoch(m.market_start) AS BIGINT) IN ({seconds})
    ),
    latency(latency_seconds) AS (VALUES {latencies})
    SELECT
        '{asset}' AS asset,
        signal.*,
        latency.latency_seconds,
        execution.t::BIGINT AS execution_t,
        CASE WHEN signal.favorite = 'Up' THEN execution.au ELSE execution.ad END AS execution_ask,
        CASE WHEN signal.favorite = 'Up' THEN execution.sau ELSE execution.sad END AS execution_ask_size,
        CAST(signal.favorite = signal.outcome AS BOOLEAN) AS won
    FROM signal
    CROSS JOIN latency
    LEFT JOIN ticks AS execution
      ON execution.condition_id = signal.condition_id
     AND execution.t = signal.signal_t + latency.latency_seconds
    ORDER BY signal.signal_t, signal.condition_id, latency.latency_seconds
    """
    frame = connection.execute(query).fetchdf()
    frame["day"] = pd.to_datetime(frame["day"], utc=True)
    unique_days = np.sort(frame["day"].dropna().unique())
    train_end = max(1, int(len(unique_days) * 0.60))
    validation_end = max(train_end + 1, int(len(unique_days) * 0.80))
    train_days = set(unique_days[:train_end])
    validation_days = set(unique_days[train_end:validation_end])
    test_days = set(unique_days[validation_end:])
    frame["segment"] = np.where(
        frame["day"].isin(train_days),
        "train",
        np.where(frame["day"].isin(validation_days), "validation", "test"),
    )
    return frame


def select_trades(
    frame: pd.DataFrame,
    config: Config,
    *,
    segment: str | None = None,
    assets: set[str] | None = None,
    shares_required: float = SHARES,
    slippage: float = 0.0,
    fee_multiplier: float = 1.0,
    final_confidence: float = MIN_FINAL_CONFIDENCE,
    minimum_ticks: int = MIN_TICKS,
) -> pd.DataFrame:
    limit = np.minimum(0.99, frame["signal_ask"].to_numpy(dtype=float) + config.limit_buffer)
    execution_ask = frame["execution_ask"].to_numpy(dtype=float)
    mask = (
        (frame["entry_second"].to_numpy() == config.entry_second)
        & (frame["latency_seconds"].to_numpy() == config.latency_seconds)
        & (frame["signal_ask"].to_numpy(dtype=float) >= config.ask_threshold)
        & np.isfinite(execution_ask)
        & (execution_ask > 0.0)
        & (execution_ask <= limit + 1e-12)
        & (frame["execution_ask_size"].fillna(0.0).to_numpy(dtype=float) >= shares_required)
        & (frame["n_ticks"].fillna(0).to_numpy(dtype=float) >= minimum_ticks)
        & (frame["final_confidence"].fillna(0.0).to_numpy(dtype=float) >= final_confidence)
        & frame["outcome"].notna().to_numpy()
        & frame["won"].notna().to_numpy()
    )
    if segment is not None:
        mask &= frame["segment"].to_numpy() == segment
    if assets is not None:
        mask &= frame["asset"].isin(assets).to_numpy()
    selected = frame.loc[mask].copy()
    if selected.empty:
        selected["all_in_cost_per_share"] = pd.Series(dtype=float)
        selected["pnl_per_share"] = pd.Series(dtype=float)
        selected["pnl_five_shares"] = pd.Series(dtype=float)
        return selected
    adjusted_ask = np.minimum(0.99, selected["execution_ask"].to_numpy(dtype=float) + slippage)
    cost = adjusted_ask + fee(adjusted_ask, multiplier=fee_multiplier)
    selected["adjusted_execution_ask"] = adjusted_ask
    selected["all_in_cost_per_share"] = cost
    selected["pnl_per_share"] = selected["won"].astype(float).to_numpy() - cost
    selected["pnl_five_shares"] = selected["pnl_per_share"] * SHARES
    return selected


def daily_score(trades: pd.DataFrame) -> float:
    result = metrics(trades)
    if result["daily_t_stat"] is None:
        return -math.inf
    return float(result["daily_t_stat"])


def find_global_config(frame: pd.DataFrame) -> tuple[Config, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    best: tuple[float, Config] | None = None
    for values in itertools.product(ENTRY_SECONDS, ASK_THRESHOLDS, LATENCIES, LIMIT_BUFFERS):
        config = Config(*values)
        train = select_trades(frame, config, segment="train")
        validation = select_trades(frame, config, segment="validation")
        train_metrics = metrics(train)
        validation_metrics = metrics(validation)
        positive_validation_assets = 0
        for asset in ASSETS:
            asset_validation = validation[validation["asset"] == asset]
            if not asset_validation.empty and float(asset_validation["pnl_per_share"].mean()) > 0.0:
                positive_validation_assets += 1
        row = {
            **asdict(config),
            **{f"train_{key}": value for key, value in train_metrics.items()},
            **{f"validation_{key}": value for key, value in validation_metrics.items()},
            "positive_validation_assets": positive_validation_assets,
        }
        rows.append(row)
        qualifies = (
            train_metrics["trades"] >= MIN_TRAIN_TRADES
            and validation_metrics["trades"] >= MIN_VALIDATION_TRADES
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
        score = min(daily_score(train), daily_score(validation))
        if best is None or score > best[0]:
            best = (score, config)
    grid = pd.DataFrame(rows)
    if best is None:
        raise RuntimeError("no global configuration passed the frozen train/validation requirements")
    return best[1], grid


def validation_selected_assets(frame: pd.DataFrame, config: Config) -> set[str]:
    chosen: set[str] = set()
    for asset in ASSETS:
        train = select_trades(frame, config, segment="train", assets={asset})
        validation = select_trades(frame, config, segment="validation", assets={asset})
        if len(train) < 200 or len(validation) < 50:
            continue
        if train["pnl_per_share"].mean() > 0.0 and validation["pnl_per_share"].mean() > 0.0:
            chosen.add(asset)
    return chosen


def summarize_test(trades: pd.DataFrame) -> dict[str, Any]:
    result = metrics(trades)
    daily = trades.groupby("day", sort=True)["pnl_five_shares"].sum().to_numpy(dtype=float) if not trades.empty else np.empty(0)
    result["bootstrap_daily_mean"] = block_bootstrap_daily(daily)
    result["one_sided_daily_p_value"] = (
        float(stats.ttest_1samp(daily, popmean=0.0, alternative="greater").pvalue)
        if len(daily) > 1
        else None
    )
    result.update(capital_metrics(trades))
    return result


def main() -> None:
    data_dir = Path("data")
    output_dir = Path("results/favorite_walkforward")
    output_dir.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("PRAGMA threads=4")
    connection.execute("PRAGMA memory_limit='12GB'")

    frames = []
    split_rows = []
    for asset in ASSETS:
        print(f"[favorite] loading {asset}", flush=True)
        asset_frame = load_asset(connection, data_dir, asset)
        for segment, group in asset_frame.groupby("segment"):
            split_rows.append(
                {
                    "asset": asset,
                    "segment": segment,
                    "first_day": group["day"].min(),
                    "last_day": group["day"].max(),
                    "rows": len(group),
                    "markets": group["condition_id"].nunique(),
                }
            )
        frames.append(asset_frame)
    frame = pd.concat(frames, ignore_index=True)
    del frames

    selected_config, grid = find_global_config(frame)
    selected_assets = validation_selected_assets(frame, selected_config)
    if not selected_assets:
        selected_assets = set(ASSETS)

    all_test = select_trades(frame, selected_config, segment="test")
    subset_test = select_trades(frame, selected_config, segment="test", assets=selected_assets)
    all_test_summary = summarize_test(all_test)
    subset_test_summary = summarize_test(subset_test)

    per_asset_rows = []
    for asset in ASSETS:
        asset_test = all_test[all_test["asset"] == asset]
        per_asset_rows.append({"asset": asset, **summarize_test(asset_test)})

    stress_rows = []
    for slippage, fee_multiplier, size, confidence in itertools.product(
        [0.0, 0.005, 0.01], [1.0, 1.5, 2.0], [1.0, 5.0, 10.0], [0.90, 0.95, 0.99]
    ):
        stressed = select_trades(
            frame,
            selected_config,
            segment="test",
            assets=selected_assets,
            shares_required=size,
            slippage=slippage,
            fee_multiplier=fee_multiplier,
            final_confidence=confidence,
        )
        stress_rows.append(
            {
                "slippage": slippage,
                "fee_multiplier": fee_multiplier,
                "minimum_displayed_ask_size": size,
                "minimum_final_confidence": confidence,
                **metrics(stressed),
            }
        )

    neighbour_rows = []
    for second in sorted(set(value for value in [selected_config.entry_second - 30, selected_config.entry_second, selected_config.entry_second + 30] if value in ENTRY_SECONDS)):
        for threshold in sorted(set(value for value in [selected_config.ask_threshold - 0.05, selected_config.ask_threshold, selected_config.ask_threshold + 0.05] if round(value, 2) in ASK_THRESHOLDS)):
            neighbour = Config(
                entry_second=second,
                ask_threshold=round(threshold, 2),
                latency_seconds=selected_config.latency_seconds,
                limit_buffer=selected_config.limit_buffer,
            )
            neighbour_test = select_trades(frame, neighbour, segment="test", assets=selected_assets)
            neighbour_rows.append({**asdict(neighbour), **metrics(neighbour_test)})

    weekly = (
        subset_test.assign(week=subset_test["day"].dt.to_period("W").astype(str))
        .groupby(["week", "asset"], as_index=False)
        .agg(trades=("pnl_per_share", "size"), sum_pnl_five_shares=("pnl_five_shares", "sum"), mean_pnl_per_share=("pnl_per_share", "mean"))
    )

    summary = {
        "selected_config": asdict(selected_config),
        "selection_rule": {
            "scope": "one global configuration across seven assets",
            "minimum_train_trades": MIN_TRAIN_TRADES,
            "minimum_validation_trades": MIN_VALIDATION_TRADES,
            "minimum_positive_validation_assets": 4,
            "minimum_positive_validation_day_fraction": 0.55,
            "score": "maximize min(train daily t-stat, validation daily t-stat)",
        },
        "selected_assets_from_train_and_validation_only": sorted(selected_assets),
        "all_asset_test": all_test_summary,
        "validation_selected_asset_test": subset_test_summary,
        "per_asset_test": per_asset_rows,
        "label_contract": {
            "outcome_source": "inferred from final recorded book tick",
            "minimum_ticks": MIN_TICKS,
            "minimum_terminal_winner_mid": MIN_FINAL_CONFIDENCE,
            "official_settlement_required_before_live": True,
        },
        "execution_contract": {
            "shares": SHARES,
            "entry": "frozen favorite at signal second; FOK limit at signal ask plus selected buffer",
            "fees": "0.07 * p * (1-p) on entry",
            "settlement_exit_fee": 0.0,
            "displayed_ask_size_required": SHARES,
        },
    }

    grid.to_csv(output_dir / "selection_grid.csv", index=False)
    pd.DataFrame(split_rows).to_csv(output_dir / "chronological_splits.csv", index=False)
    all_test.to_csv(output_dir / "all_asset_test_trades.csv", index=False)
    subset_test.to_csv(output_dir / "selected_asset_test_trades.csv", index=False)
    pd.DataFrame(per_asset_rows).to_csv(output_dir / "per_asset_test.csv", index=False)
    pd.DataFrame(stress_rows).to_csv(output_dir / "stress_grid.csv", index=False)
    pd.DataFrame(neighbour_rows).to_csv(output_dir / "test_neighbourhood.csv", index=False)
    weekly.to_csv(output_dir / "test_weekly.csv", index=False)
    (output_dir / "summary.json").write_text(json.dumps(json_safe(summary), indent=2, sort_keys=True), encoding="utf-8")

    report = [
        "# Strict Favorite Walk-Forward Study",
        "",
        "One global entry rule is selected across all seven assets using training and validation only.",
        "The final chronological segment is evaluated once. Entry uses the executable ask after the",
        "selected latency, requires displayed size for five shares, respects a frozen FOK limit, and",
        "holds to the inferred terminal outcome.",
        "",
        "## Selected configuration",
        "",
        "```json",
        json.dumps(asdict(selected_config), indent=2),
        "```",
        "",
        f"Validation-selected assets: **{', '.join(sorted(selected_assets))}**",
        "",
        "## Untouched test — all assets",
        "",
        "```json",
        json.dumps(json_safe(all_test_summary), indent=2),
        "```",
        "",
        "## Untouched test — validation-selected assets",
        "",
        "```json",
        json.dumps(json_safe(subset_test_summary), indent=2),
        "```",
        "",
        "## Per-asset untouched test",
        "",
        pd.DataFrame(per_asset_rows)[["asset", "trades", "sum_pnl_five_shares", "mean_pnl_per_share", "win_rate", "daily_t_stat", "max_drawdown_five_shares"]].to_markdown(index=False),
        "",
        "## Non-negotiable caveats",
        "",
        "- Outcomes are inferred from the final recorded order book, not authoritative settlement.",
        "- The terminal-confidence and market-completeness filters reduce, but do not eliminate, label risk.",
        "- Positive test performance is not permission for live trading; it must transfer to official labels and prospective shadow fills.",
        "- Position sizing is fixed at five shares. No all-in compounding is evaluated or recommended.",
        "",
    ]
    (output_dir / "REPORT.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps(json_safe(summary), indent=2), flush=True)


if __name__ == "__main__":
    main()
