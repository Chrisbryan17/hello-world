from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

ASSETS = ["btc", "eth", "sol", "xrp", "doge", "hype", "bnb"]
FEE_COEFFICIENT = 0.07
ENTRY_SECONDS = [30, 60, 120, 180, 240, 270, 285]
FAVORITE_THRESHOLDS = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
LATENCIES_SECONDS = [0, 1, 2]
ADVERSE_SLIPPAGE_PER_LEG = [0.0, 0.005, 0.01]


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def scalar_record(connection: duckdb.DuckDBPyConnection, query: str) -> dict[str, Any]:
    frame = connection.execute(query).fetchdf()
    if len(frame) != 1:
        raise AssertionError(f"expected one row, found {len(frame)}")
    return frame.iloc[0].to_dict()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def fee_sql(price_expression: str) -> str:
    return f"({FEE_COEFFICIENT} * ({price_expression}) * (1.0 - ({price_expression})))"


def run_asset(connection: duckdb.DuckDBPyConnection, data_dir: Path, asset: str) -> dict[str, Any]:
    markets_path = sql_path(data_dir / f"{asset}_markets.parquet")
    ticks_path = sql_path(data_dir / f"{asset}_ticks.parquet")
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW markets AS SELECT * FROM read_parquet('{markets_path}')"
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW ticks AS SELECT * FROM read_parquet('{ticks_path}')"
    )

    market_quality = scalar_record(
        connection,
        """
        SELECT
            count(*) AS markets,
            count(DISTINCT condition_id) AS unique_conditions,
            count(*) FILTER (WHERE outcome IS NULL) AS null_outcomes,
            min(n_ticks) AS min_ticks,
            quantile_cont(n_ticks, 0.5) AS median_ticks,
            max(n_ticks) AS max_ticks,
            avg(CASE WHEN n_ticks >= 299 THEN 1.0 ELSE 0.0 END) AS fullish_market_fraction,
            min(market_start) AS start_time,
            max(market_end) AS end_time,
            quantile_cont(volume, 0.5) AS median_discovery_volume,
            quantile_cont(liquidity, 0.5) AS median_discovery_liquidity
        FROM markets
        """,
    )
    tick_quality = scalar_record(
        connection,
        """
        SELECT
            count(*) AS ticks,
            count(DISTINCT condition_id) AS tick_conditions,
            quantile_cont(au - bu, 0.5) AS median_up_spread,
            quantile_cont(ad - bd, 0.5) AS median_down_spread,
            quantile_cont(au + ad - 1.0, 0.5) AS median_ask_complement_premium,
            avg(CASE WHEN sau IS NULL THEN 1.0 ELSE 0.0 END) AS null_up_ask_size_fraction,
            avg(CASE WHEN sad IS NULL THEN 1.0 ELSE 0.0 END) AS null_down_ask_size_fraction
        FROM ticks
        """,
    )

    connection.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW arb_base AS
        SELECT
            *,
            least(coalesce(sau, 0.0), coalesce(sad, 0.0)) AS pair_size,
            1.0
              - (au + {fee_sql('au')})
              - (ad + {fee_sql('ad')}) AS net_edge
        FROM ticks
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP VIEW arb_flagged AS
        SELECT
            *,
            (net_edge > 0.0 AND pair_size > 0.0) AS crossable,
            lag(net_edge > 0.0 AND pair_size > 0.0, 1, false)
              OVER (PARTITION BY condition_id ORDER BY t) AS previous_crossable
        FROM arb_base
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP VIEW arb_episode_rows AS
        SELECT
            *,
            sum(CASE WHEN crossable AND NOT previous_crossable THEN 1 ELSE 0 END)
              OVER (PARTITION BY condition_id ORDER BY t ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
              AS episode_id
        FROM arb_flagged
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP VIEW arb_episodes AS
        SELECT
            condition_id,
            episode_id,
            min(t) AS start_t,
            max(t) AS end_t,
            count(*) AS duration_seconds,
            min(net_edge) AS minimum_net_edge,
            max(net_edge) AS maximum_net_edge,
            arg_min(net_edge, t) AS start_net_edge,
            arg_min(pair_size, t) AS start_pair_size,
            max(pair_size) AS maximum_pair_size
        FROM arb_episode_rows
        WHERE crossable
        GROUP BY condition_id, episode_id
        """
    )

    direct_tick = scalar_record(
        connection,
        """
        SELECT
            count(*) FILTER (WHERE crossable) AS crossable_seconds,
            count(DISTINCT condition_id) FILTER (WHERE crossable) AS crossable_markets,
            quantile_cont(net_edge, 0.5) FILTER (WHERE crossable) AS median_net_edge,
            quantile_cont(net_edge, 0.95) FILTER (WHERE crossable) AS p95_net_edge,
            max(net_edge) FILTER (WHERE crossable) AS maximum_net_edge,
            count(*) FILTER (WHERE crossable AND pair_size >= 1.0) AS seconds_size_ge_1,
            count(*) FILTER (WHERE crossable AND pair_size >= 5.0) AS seconds_size_ge_5,
            count(*) FILTER (WHERE crossable AND pair_size >= 10.0) AS seconds_size_ge_10
        FROM arb_flagged
        """,
    )
    direct_episode = scalar_record(
        connection,
        """
        SELECT
            count(*) AS episodes,
            count(DISTINCT condition_id) AS markets,
            quantile_cont(duration_seconds, 0.5) AS median_duration_seconds,
            quantile_cont(duration_seconds, 0.95) AS p95_duration_seconds,
            quantile_cont(maximum_net_edge, 0.5) AS median_best_net_edge,
            quantile_cont(maximum_net_edge, 0.95) AS p95_best_net_edge,
            count(*) FILTER (WHERE start_pair_size >= 5.0) AS episodes_start_size_ge_5,
            sum(least(start_pair_size, 5.0) * start_net_edge) AS first_cross_pnl_cap5
        FROM arb_episodes
        """,
    )

    latency_rows: list[dict[str, Any]] = []
    for latency in LATENCIES_SECONDS:
        for slippage in ADVERSE_SLIPPAGE_PER_LEG:
            up_px = f"least(0.99, execution.au + {slippage})"
            down_px = f"least(0.99, execution.ad + {slippage})"
            edge = (
                f"1.0 - ({up_px} + {fee_sql(up_px)})"
                f" - ({down_px} + {fee_sql(down_px)})"
            )
            query = f"""
            WITH candidates AS (
                SELECT
                    episode.condition_id,
                    episode.episode_id,
                    episode.start_t,
                    execution.t AS execution_t,
                    execution.pair_size,
                    {edge} AS executable_edge,
                    row_number() OVER (
                        PARTITION BY episode.condition_id
                        ORDER BY episode.start_t
                    ) AS market_attempt_number
                FROM arb_episodes AS episode
                JOIN arb_base AS execution
                  ON execution.condition_id = episode.condition_id
                 AND execution.t = episode.start_t + {latency}
                WHERE execution.pair_size >= 5.0
                  AND ({edge}) > 0.0
            )
            SELECT
                count(*) AS executable_episodes,
                count(DISTINCT condition_id) AS executable_markets,
                quantile_cont(executable_edge, 0.5) AS median_executable_edge,
                quantile_cont(executable_edge, 0.95) AS p95_executable_edge,
                sum(5.0 * executable_edge) AS all_episode_pnl_five_shares,
                count(*) FILTER (WHERE market_attempt_number = 1) AS first_attempt_markets,
                sum(CASE WHEN market_attempt_number = 1 THEN 5.0 * executable_edge ELSE 0.0 END)
                  AS first_attempt_pnl_five_shares
            FROM candidates
            """
            record = scalar_record(connection, query)
            record.update(
                {
                    "asset": asset,
                    "latency_seconds": latency,
                    "adverse_slippage_per_leg": slippage,
                    "transactionally_atomic": False,
                }
            )
            latency_rows.append(record)

    threshold_values = ",".join(f"({threshold})" for threshold in FAVORITE_THRESHOLDS)
    entry_values = ",".join(str(value) for value in ENTRY_SECONDS)
    favorite = connection.execute(
        f"""
        WITH snapshots AS (
            SELECT
                m.condition_id,
                m.market_start,
                m.outcome,
                t.t,
                CAST(t.t - epoch(m.market_start) AS BIGINT) AS elapsed_seconds,
                CASE
                    WHEN (t.bu + t.au) >= (t.bd + t.ad) THEN 'Up'
                    ELSE 'Down'
                END AS favorite,
                CASE
                    WHEN (t.bu + t.au) >= (t.bd + t.ad) THEN t.au
                    ELSE t.ad
                END AS entry_ask
            FROM ticks AS t
            JOIN markets AS m USING (condition_id)
            WHERE CAST(t.t - epoch(m.market_start) AS BIGINT) IN ({entry_values})
        ),
        scored AS (
            SELECT
                *,
                favorite = outcome AS won,
                entry_ask + {fee_sql('entry_ask')} AS all_in_cost,
                CAST(favorite = outcome AS DOUBLE)
                  - (entry_ask + {fee_sql('entry_ask')}) AS pnl_per_share,
                date_trunc('week', market_start) AS week_start
            FROM snapshots
            WHERE outcome IS NOT NULL
        ),
        thresholds(threshold) AS (VALUES {threshold_values})
        SELECT
            '{asset}' AS asset,
            elapsed_seconds,
            threshold AS ask_threshold,
            count(*) AS trades,
            avg(CAST(won AS DOUBLE)) AS win_rate,
            avg(entry_ask) AS mean_entry_ask,
            avg(pnl_per_share) AS mean_pnl_per_share,
            quantile_cont(pnl_per_share, 0.5) AS median_pnl_per_share,
            sum(pnl_per_share) AS sum_pnl_one_share,
            count(DISTINCT week_start) AS weeks
        FROM scored
        CROSS JOIN thresholds
        WHERE entry_ask >= threshold
        GROUP BY elapsed_seconds, threshold
        ORDER BY elapsed_seconds, threshold
        """
    ).fetchdf()

    favorite_weekly = connection.execute(
        f"""
        WITH snapshots AS (
            SELECT
                m.market_start,
                m.outcome,
                CAST(t.t - epoch(m.market_start) AS BIGINT) AS elapsed_seconds,
                CASE
                    WHEN (t.bu + t.au) >= (t.bd + t.ad) THEN 'Up'
                    ELSE 'Down'
                END AS favorite,
                CASE
                    WHEN (t.bu + t.au) >= (t.bd + t.ad) THEN t.au
                    ELSE t.ad
                END AS entry_ask
            FROM ticks AS t
            JOIN markets AS m USING (condition_id)
            WHERE CAST(t.t - epoch(m.market_start) AS BIGINT) IN ({entry_values})
        ),
        scored AS (
            SELECT
                *,
                CAST(favorite = outcome AS DOUBLE)
                  - (entry_ask + {fee_sql('entry_ask')}) AS pnl_per_share,
                date_trunc('week', market_start) AS week_start
            FROM snapshots
            WHERE outcome IS NOT NULL
        ),
        thresholds(threshold) AS (VALUES {threshold_values})
        SELECT
            '{asset}' AS asset,
            week_start,
            elapsed_seconds,
            threshold AS ask_threshold,
            count(*) AS trades,
            avg(pnl_per_share) AS mean_pnl_per_share,
            sum(pnl_per_share) AS sum_pnl_one_share
        FROM scored
        CROSS JOIN thresholds
        WHERE entry_ask >= threshold
        GROUP BY week_start, elapsed_seconds, threshold
        ORDER BY week_start, elapsed_seconds, threshold
        """
    ).fetchdf()

    spread_tte = connection.execute(
        """
        WITH framed AS (
            SELECT
                t.*,
                CAST(t.t - epoch(m.market_start) AS BIGINT) AS elapsed_seconds,
                floor(CAST(t.t - epoch(m.market_start) AS DOUBLE) / 30.0) * 30 AS elapsed_bucket,
                (t.bu + t.au) / 2.0 AS mid_up,
                lag((t.bu + t.au) / 2.0) OVER (
                    PARTITION BY t.condition_id ORDER BY t.t
                ) AS previous_mid_up
            FROM ticks AS t
            JOIN markets AS m USING (condition_id)
        )
        SELECT
            elapsed_bucket,
            count(*) AS ticks,
            quantile_cont(au - bu, 0.5) AS median_up_spread,
            quantile_cont(ad - bd, 0.5) AS median_down_spread,
            quantile_cont(au + ad - 1.0, 0.5) AS median_ask_complement_premium,
            avg(CASE WHEN mid_up != previous_mid_up THEN 1.0 ELSE 0.0 END) AS mid_update_fraction,
            quantile_cont(du + dd, 0.5) AS median_bid_depth_usdc
        FROM framed
        GROUP BY elapsed_bucket
        ORDER BY elapsed_bucket
        """
    ).fetchdf()
    spread_tte.insert(0, "asset", asset)

    return {
        "quality": {**market_quality, **tick_quality},
        "direct_arbitrage_tick": direct_tick,
        "direct_arbitrage_episode": direct_episode,
        "latency_rows": latency_rows,
        "favorite": favorite,
        "favorite_weekly": favorite_weekly,
        "spread_tte": spread_tte,
    }


def write_report(summary: dict[str, Any], output_dir: Path) -> None:
    direct = pd.DataFrame(summary["direct_arbitrage_by_asset"])
    latency = pd.DataFrame(summary["direct_arbitrage_latency"])
    favorites = pd.DataFrame(summary["favorite_cells"])
    viable = favorites[(favorites["trades"] >= 200) & favorites["mean_pnl_per_share"].notna()].copy()
    viable = viable.sort_values("mean_pnl_per_share", ascending=False).head(20)
    lines = [
        "# Polymarket 5-Minute Crypto — Structural EDA",
        "",
        "This pass scans all seven assets and all one-second observations. All costs use the",
        f"historical crypto taker-fee approximation `fee/share = {FEE_COEFFICIENT} × p × (1-p)`.",
        "Complement trades are explicitly **not** treated as transactionally atomic.",
        "",
        "## Dataset",
        "",
        f"- Markets: **{int(summary['totals']['markets']):,}**",
        f"- Ticks: **{int(summary['totals']['ticks']):,}**",
        f"- Null inferred outcomes: **{int(summary['totals']['null_outcomes']):,}**",
        "",
        "## Same-market complement arbitrage",
        "",
    ]
    if direct.empty:
        lines.append("No direct-arbitrage records were produced.")
    else:
        cols = [
            "asset",
            "crossable_markets",
            "episodes",
            "median_best_net_edge",
            "p95_best_net_edge",
            "first_cross_pnl_cap5",
        ]
        lines.append(direct[cols].to_markdown(index=False))
    lines.extend(["", "### Latency/slippage survival", ""])
    if not latency.empty:
        conservative = latency[
            (latency["latency_seconds"] == 1)
            & (latency["adverse_slippage_per_leg"] == 0.005)
        ]
        lines.append(
            conservative[
                [
                    "asset",
                    "executable_markets",
                    "median_executable_edge",
                    "first_attempt_pnl_five_shares",
                ]
            ].to_markdown(index=False)
        )
    lines.extend(["", "## Best settlement-favorite cells (minimum 200 trades)", ""])
    if viable.empty:
        lines.append("No cell with at least 200 trades had usable results.")
    else:
        lines.append(
            viable[
                [
                    "asset",
                    "elapsed_seconds",
                    "ask_threshold",
                    "trades",
                    "win_rate",
                    "mean_entry_ask",
                    "mean_pnl_per_share",
                ]
            ].to_markdown(index=False)
        )
    lines.extend(
        [
            "",
            "## Interpretation guardrails",
            "",
            "- `outcome` is inferred from the final book tick, not on-chain settlement.",
            "- Ask-size capacity is top-of-book only; queue position and simultaneous two-leg execution are unknown.",
            "- Repeated one-second rows are collapsed into opportunity episodes before latency analysis.",
            "- Favorite cells are descriptive EDA, not admission evidence; the next pass performs chronological selection and untouched testing.",
            "",
        ]
    )
    (output_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    data_dir = Path("data")
    output_dir = Path("results/phase1_structural")
    output_dir.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("PRAGMA threads=4")
    connection.execute("PRAGMA memory_limit='10GB'")

    summary: dict[str, Any] = {
        "assets": {},
        "fee_coefficient": FEE_COEFFICIENT,
        "direct_arbitrage_by_asset": [],
        "direct_arbitrage_latency": [],
        "favorite_cells": [],
        "favorite_weekly": [],
        "spread_tte": [],
    }
    for asset in ASSETS:
        print(f"[phase1] scanning {asset}", flush=True)
        result = run_asset(connection, data_dir, asset)
        summary["assets"][asset] = json_safe(result["quality"])
        summary["direct_arbitrage_by_asset"].append(
            {
                "asset": asset,
                **json_safe(result["direct_arbitrage_tick"]),
                **json_safe(result["direct_arbitrage_episode"]),
                "transactionally_atomic": False,
            }
        )
        summary["direct_arbitrage_latency"].extend(
            json_safe(result["latency_rows"])
        )
        summary["favorite_cells"].extend(
            json_safe(result["favorite"].to_dict("records"))
        )
        summary["favorite_weekly"].extend(
            json_safe(result["favorite_weekly"].to_dict("records"))
        )
        summary["spread_tte"].extend(
            json_safe(result["spread_tte"].to_dict("records"))
        )

    summary["totals"] = {
        "markets": sum(int(item["markets"]) for item in summary["assets"].values()),
        "ticks": sum(int(item["ticks"]) for item in summary["assets"].values()),
        "null_outcomes": sum(int(item["null_outcomes"]) for item in summary["assets"].values()),
    }
    pd.DataFrame(summary["direct_arbitrage_by_asset"]).to_csv(
        output_dir / "direct_arbitrage_by_asset.csv", index=False
    )
    pd.DataFrame(summary["direct_arbitrage_latency"]).to_csv(
        output_dir / "direct_arbitrage_latency.csv", index=False
    )
    pd.DataFrame(summary["favorite_cells"]).to_csv(
        output_dir / "favorite_cells.csv", index=False
    )
    pd.DataFrame(summary["favorite_weekly"]).to_csv(
        output_dir / "favorite_weekly.csv", index=False
    )
    pd.DataFrame(summary["spread_tte"]).to_csv(
        output_dir / "spread_time_to_expiry.csv", index=False
    )
    (output_dir / "summary.json").write_text(
        json.dumps(json_safe(summary), indent=2, sort_keys=True), encoding="utf-8"
    )
    write_report(summary, output_dir)
    print(json.dumps(summary["totals"], indent=2), flush=True)


if __name__ == "__main__":
    main()
