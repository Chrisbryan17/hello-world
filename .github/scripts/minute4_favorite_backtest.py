#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from huggingface_hub import hf_hub_download

REPO = "kachoio/polymarket-5-minute-crypto-up-down-markets"
COINS = ("BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE")
DECISION_SECOND = 240
LATENCIES = (0, 1, 2, 3)
SLIPPAGES = (0.00, 0.01, 0.02, 0.03, 0.05)
FEE_RATE = 0.07
START_BANKROLL = 90.0
RISK_FRACTIONS = (0.01, 0.02, 0.05, 0.10, 0.20, 0.25, 0.50, 1.00)
THRESHOLDS = tuple(np.round(np.arange(0.50, 0.91, 0.02), 2))
SPREAD_CAPS = (0.02, 0.03, 0.05, 0.08)
SIDES = ("Both", "Up", "Down")
OUT = Path("minute4-favorite-results")
DATA = Path(".cache/minute4-favorite-data")
OUT.mkdir(parents=True, exist_ok=True)
DATA.mkdir(parents=True, exist_ok=True)


def fee_per_share(price):
    p = np.asarray(price, dtype=float)
    return FEE_RATE * p * (1.0 - p)


def max_drawdown(values):
    arr = np.asarray(values, dtype=float)
    if len(arr) == 0:
        return float("nan")
    peak = np.maximum.accumulate(arr)
    dd = 1.0 - arr / np.maximum(peak, 1e-12)
    return float(np.nanmax(dd))


def safe_float(value):
    if value is None:
        return None
    try:
        v = float(value)
    except Exception:
        return None
    return v if math.isfinite(v) else None


def summarize(frame: pd.DataFrame, slippage: float) -> dict:
    if frame.empty:
        return {
            "n": 0,
            "win_rate": None,
            "avg_leader_mid": None,
            "avg_entry_price": None,
            "avg_total_cost": None,
            "mean_pnl_per_share": None,
            "roi_on_cost": None,
            "positive_day_rate": None,
            "initial_90_fok_rate": None,
        }
    p = np.minimum(0.99, frame["entry_ask"].to_numpy(float) + slippage)
    cost = p + fee_per_share(p)
    won = frame["won"].to_numpy(float)
    pnl = won - cost
    day = pd.to_datetime(frame["market_start"], utc=True).dt.date
    day_stats = pd.DataFrame({"day": day, "pnl": pnl}).groupby("day", as_index=False)["pnl"].mean()
    required_shares = START_BANKROLL / cost
    size = pd.to_numeric(frame["entry_ask_size"], errors="coerce").to_numpy(float)
    return {
        "n": int(len(frame)),
        "win_rate": float(won.mean()),
        "avg_leader_mid": float(frame["leader_mid"].mean()),
        "avg_entry_price": float(p.mean()),
        "avg_total_cost": float(cost.mean()),
        "break_even_accuracy_at_avg_cost": float(cost.mean()),
        "mean_pnl_per_share": float(pnl.mean()),
        "roi_on_cost": float(pnl.sum() / cost.sum()),
        "positive_day_rate": float((day_stats["pnl"] > 0).mean()),
        "initial_90_fok_rate": float(np.mean(np.isfinite(size) & (size >= required_shares))),
    }


def add_execution(frame: pd.DataFrame, slippage: float) -> pd.DataFrame:
    out = frame.copy()
    out["slippage"] = slippage
    out["effective_price"] = np.minimum(0.99, out["entry_ask"].astype(float) + slippage)
    out["fee_per_share"] = fee_per_share(out["effective_price"].to_numpy(float))
    out["total_cost"] = out["effective_price"] + out["fee_per_share"]
    out["pnl_per_share"] = out["won"].astype(float) - out["total_cost"]
    out["return_on_cost"] = out["pnl_per_share"] / out["total_cost"]
    return out


def load_coin(coin: str) -> pd.DataFrame:
    lower = coin.lower()
    markets_path = hf_hub_download(
        repo_id=REPO,
        repo_type="dataset",
        filename=f"{lower}_markets.parquet",
        local_dir=DATA,
    )
    ticks_path = hf_hub_download(
        repo_id=REPO,
        repo_type="dataset",
        filename=f"{lower}_ticks.parquet",
        local_dir=DATA,
    )
    markets = pd.read_parquet(
        markets_path,
        columns=["condition_id", "market_start", "outcome"],
    )
    markets["market_start"] = pd.to_datetime(markets["market_start"], utc=True)
    markets = markets.loc[markets["outcome"].isin(["Up", "Down"])].copy()
    markets["market_start_s"] = markets["market_start"].astype("int64") // 1_000_000_000
    start_map = markets.set_index("condition_id")["market_start_s"]
    outcome_map = markets.set_index("condition_id")["outcome"]
    market_time_map = markets.set_index("condition_id")["market_start"]

    ticks = pd.read_parquet(
        ticks_path,
        columns=["condition_id", "t", "bu", "au", "bd", "ad", "sau", "sad"],
    )
    ticks["market_start_s"] = ticks["condition_id"].map(start_map)
    ticks = ticks.loc[ticks["market_start_s"].notna()].copy()
    ticks["elapsed"] = ticks["t"].astype("int64") - ticks["market_start_s"].astype("int64")
    needed = {DECISION_SECOND + latency for latency in LATENCIES}
    ticks = ticks.loc[ticks["elapsed"].isin(needed)].copy()

    decision = ticks.loc[ticks["elapsed"].eq(DECISION_SECOND)].copy()
    valid_decision = (
        decision[["bu", "au", "bd", "ad"]].notna().all(axis=1)
        & decision["bu"].gt(0) & decision["au"].lt(1) & decision["bu"].le(decision["au"])
        & decision["bd"].gt(0) & decision["ad"].lt(1) & decision["bd"].le(decision["ad"])
    )
    decision = decision.loc[valid_decision].copy()
    decision["mid_up"] = (decision["bu"] + decision["au"]) / 2.0
    decision["mid_down"] = (decision["bd"] + decision["ad"]) / 2.0
    decision["selected_side"] = np.where(decision["mid_up"] >= decision["mid_down"], "Up", "Down")
    decision["leader_mid"] = np.maximum(decision["mid_up"], decision["mid_down"])
    decision = decision[["condition_id", "selected_side", "leader_mid", "mid_up", "mid_down"]]

    rows = []
    for latency in LATENCIES:
        entry = ticks.loc[ticks["elapsed"].eq(DECISION_SECOND + latency)].copy()
        merged = decision.merge(entry, on="condition_id", how="inner", validate="one_to_one")
        merged["market_start"] = merged["condition_id"].map(market_time_map)
        merged["outcome"] = merged["condition_id"].map(outcome_map)
        is_up = merged["selected_side"].eq("Up")
        merged["entry_bid"] = np.where(is_up, merged["bu"], merged["bd"])
        merged["entry_ask"] = np.where(is_up, merged["au"], merged["ad"])
        merged["entry_ask_size"] = np.where(is_up, merged["sau"], merged["sad"])
        merged["spread"] = merged["entry_ask"] - merged["entry_bid"]
        valid_entry = (
            merged["entry_bid"].gt(0)
            & merged["entry_ask"].lt(1)
            & merged["entry_bid"].le(merged["entry_ask"])
            & merged["spread"].ge(0)
        )
        merged = merged.loc[valid_entry].copy()
        merged["won"] = merged["selected_side"].eq(merged["outcome"])
        merged["latency_s"] = latency
        merged["coin"] = coin
        rows.append(merged[[
            "coin", "condition_id", "market_start", "selected_side", "outcome", "won",
            "leader_mid", "mid_up", "mid_down", "entry_bid", "entry_ask", "entry_ask_size",
            "spread", "latency_s"
        ]])
    result = pd.concat(rows, ignore_index=True)
    del ticks, markets
    return result


def split_periods(frame: pd.DataFrame):
    dates = sorted(pd.to_datetime(frame["market_start"], utc=True).dt.date.unique())
    if len(dates) < 16:
        raise RuntimeError(f"insufficient dates: {len(dates)}")
    holdout_dates = set(dates[-7:])
    validation_dates = set(dates[-14:-7])
    d = pd.to_datetime(frame["market_start"], utc=True).dt.date
    train = frame.loc[~d.isin(holdout_dates | validation_dates)].copy()
    validation = frame.loc[d.isin(validation_dates)].copy()
    holdout = frame.loc[d.isin(holdout_dates)].copy()
    return train, validation, holdout, dates


def threshold_search(name: str, frame: pd.DataFrame) -> tuple[pd.DataFrame, dict | None]:
    base = frame.loc[frame["latency_s"].eq(1)].copy()
    train, validation, holdout, dates = split_periods(base)
    rows = []
    for threshold in THRESHOLDS:
        for spread_cap in SPREAD_CAPS:
            for side in SIDES:
                def filt(x):
                    mask = x["leader_mid"].ge(threshold) & x["spread"].le(spread_cap)
                    if side != "Both":
                        mask &= x["selected_side"].eq(side)
                    return x.loc[mask]
                tr = filt(train)
                va = filt(validation)
                if len(tr) < 100 or len(va) < 25:
                    continue
                tr_s = summarize(tr, 0.01)
                va_s = summarize(va, 0.01)
                rows.append({
                    "strategy": name,
                    "min_leader_mid": threshold,
                    "max_spread": spread_cap,
                    "side": side,
                    "train_n": tr_s["n"],
                    "train_mean_pnl": tr_s["mean_pnl_per_share"],
                    "train_roi": tr_s["roi_on_cost"],
                    "train_win_rate": tr_s["win_rate"],
                    "validation_n": va_s["n"],
                    "validation_mean_pnl": va_s["mean_pnl_per_share"],
                    "validation_roi": va_s["roi_on_cost"],
                    "validation_win_rate": va_s["win_rate"],
                    "robust_score": min(tr_s["mean_pnl_per_share"], va_s["mean_pnl_per_share"]),
                })
    grid = pd.DataFrame(rows)
    if grid.empty:
        return grid, None
    eligible = grid.loc[(grid["train_mean_pnl"] > 0) & (grid["validation_mean_pnl"] > 0)].copy()
    if eligible.empty:
        return grid, None
    winner = eligible.sort_values(
        ["robust_score", "validation_n", "min_leader_mid"],
        ascending=[False, False, False],
    ).iloc[0].to_dict()
    mask = holdout["leader_mid"].ge(winner["min_leader_mid"]) & holdout["spread"].le(winner["max_spread"])
    if winner["side"] != "Both":
        mask &= holdout["selected_side"].eq(winner["side"])
    hold = holdout.loc[mask].copy()
    hold_summary = summarize(hold, 0.01)
    winner.update({f"holdout_{key}": value for key, value in hold_summary.items()})
    winner["train_start"] = str(min(dates))
    winner["holdout_start"] = str(dates[-7])
    winner["holdout_end"] = str(max(dates))
    return grid, winner


def bankroll_path(frame: pd.DataFrame, slippage: float, risk_fraction: float, strict_fok: bool = False):
    trades = add_execution(frame.sort_values("market_start"), slippage)
    bankroll = START_BANKROLL
    values = [bankroll]
    executed = 0
    skipped = 0
    for row in trades.itertuples(index=False):
        stake = bankroll * risk_fraction
        if stake <= 0:
            break
        shares = stake / row.total_cost
        if strict_fok:
            size = safe_float(row.entry_ask_size)
            if size is None or size < shares:
                skipped += 1
                values.append(bankroll)
                continue
        if row.won:
            bankroll = bankroll - stake + shares
        else:
            bankroll = bankroll - stake
        executed += 1
        values.append(bankroll)
        if bankroll < 1e-9:
            bankroll = 0.0
            break
    return {
        "ending_bankroll": float(bankroll),
        "peak_bankroll": float(max(values)),
        "max_drawdown": max_drawdown(values),
        "executed": int(executed),
        "skipped_depth": int(skipped),
        "ruined": bool(bankroll < 0.10 * START_BANKROLL),
    }


def all_in_streak_distribution(frame: pd.DataFrame, slippage: float) -> dict:
    trades = add_execution(frame.sort_values("market_start").reset_index(drop=True), slippage)
    streaks = []
    peaks = []
    hit2 = hit5 = hit10 = 0
    n = len(trades)
    for start in range(n):
        bankroll = START_BANKROLL
        peak = bankroll
        wins = 0
        for row in trades.iloc[start:].itertuples(index=False):
            if not row.won:
                break
            bankroll = bankroll / row.total_cost
            peak = max(peak, bankroll)
            wins += 1
        streaks.append(wins)
        peaks.append(peak)
        hit2 += peak >= START_BANKROLL * 2
        hit5 += peak >= START_BANKROLL * 5
        hit10 += peak >= START_BANKROLL * 10
    if not streaks:
        return {}
    return {
        "starts": n,
        "median_wins_before_crash": float(np.median(streaks)),
        "p90_wins_before_crash": float(np.quantile(streaks, 0.90)),
        "max_wins_before_crash": int(max(streaks)),
        "median_peak_bankroll": float(np.median(peaks)),
        "p90_peak_bankroll": float(np.quantile(peaks, 0.90)),
        "max_peak_bankroll": float(max(peaks)),
        "prob_double_before_crash": float(hit2 / n),
        "prob_5x_before_crash": float(hit5 / n),
        "prob_10x_before_crash": float(hit10 / n),
    }


def empirical_kelly(frame: pd.DataFrame, slippage: float) -> float:
    trades = add_execution(frame, slippage)
    if trades.empty:
        return 0.0
    won = trades["won"].to_numpy(bool)
    cost = trades["total_cost"].to_numpy(float)
    grid = np.linspace(0, 0.99, 991)
    best_f = 0.0
    best_growth = -np.inf
    for f in grid:
        win_mult = 1.0 + f * (1.0 / cost - 1.0)
        lose_mult = 1.0 - f
        logs = np.where(won, np.log(win_mult), np.log(lose_mult))
        growth = float(np.mean(logs))
        if growth > best_growth:
            best_growth = growth
            best_f = float(f)
    return best_f


def equal_split_windows(frame: pd.DataFrame, slippage: float, threshold: float) -> pd.DataFrame:
    x = add_execution(frame.loc[frame["leader_mid"].ge(threshold)].copy(), slippage)
    if x.empty:
        return pd.DataFrame()
    x["payout_multiple"] = x["won"].astype(float) / x["total_cost"]
    grouped = x.groupby("market_start", as_index=False).agg(
        n_legs=("coin", "size"),
        payout_multiple=("payout_multiple", "mean"),
        all_lost=("won", lambda s: bool((~s.astype(bool)).all())),
        mean_mid=("leader_mid", "mean"),
    )
    grouped["portfolio_return"] = grouped["payout_multiple"] - 1.0
    return grouped.sort_values("market_start")


def simulate_window_portfolio(windows: pd.DataFrame, risk_fraction: float):
    bankroll = START_BANKROLL
    values = [bankroll]
    for row in windows.itertuples(index=False):
        bankroll *= 1.0 + risk_fraction * row.portfolio_return
        bankroll = max(0.0, bankroll)
        values.append(bankroll)
        if bankroll < 1e-9:
            bankroll = 0.0
            break
    return {
        "ending_bankroll": float(bankroll),
        "peak_bankroll": float(max(values)),
        "max_drawdown": max_drawdown(values),
        "windows": int(min(len(windows), len(values) - 1)),
        "ruined": bool(bankroll < 0.10 * START_BANKROLL),
    }


def write_report(literal_df, slippage_df, winners_df, bankroll_df, streak_df, pooled_df):
    lines = [
        "# Minute-four favorite strategy backtest",
        "",
        "Literal rule: at T+240 seconds, select the side with the higher midpoint; enter at its ask after the stated latency; hold to resolution.",
        "Crypto taker fee charged as `0.07 × p × (1-p)` per share. Slippage is added to the observed ask.",
        "",
        "## Literal rule — 1 second latency, 1 cent slippage",
        "",
        literal_df.to_markdown(index=False),
        "",
        "## Slippage sensitivity — 1 second latency",
        "",
        slippage_df.to_markdown(index=False),
        "",
        "## Chronologically selected thresholds",
        "",
        winners_df.to_markdown(index=False) if not winners_df.empty else "No coin/side threshold was positive in both training and validation.",
        "",
        "## $90 bankroll paths",
        "",
        bankroll_df.to_markdown(index=False),
        "",
        "## All-in streak outcomes",
        "",
        streak_df.to_markdown(index=False),
        "",
        "## Cross-coin portfolio",
        "",
        pooled_df.to_markdown(index=False),
        "",
        "## Important limitations",
        "",
        "- The archive records one-second top-of-book data, not full ask-side depth.",
        "- Outcome labels are inferred from the final recorded book rather than on-chain oracle resolution.",
        "- Slippage scenarios approximate depth beyond the displayed best ask.",
        "- All-in means one losing trade destroys the bankroll; no positive expectation can remove that arithmetic fact.",
    ]
    (OUT / "REPORT.md").write_text("\n".join(lines))


def main():
    all_frames = []
    literal_rows = []
    sensitivity_rows = []
    grids = []
    winners = []
    bankroll_rows = []
    streak_rows = []

    for coin in COINS:
        print("loading", coin, flush=True)
        frame = load_coin(coin)
        frame.to_parquet(OUT / f"{coin.lower()}_minute4_candidates.parquet", index=False, compression="zstd")
        all_frames.append(frame)

        base = frame.loc[frame["latency_s"].eq(1)]
        for side in SIDES:
            subset = base if side == "Both" else base.loc[base["selected_side"].eq(side)]
            s = summarize(subset, 0.01)
            literal_rows.append({"coin": coin, "side": side, **s})

        for latency in LATENCIES:
            latency_frame = frame.loc[frame["latency_s"].eq(latency)]
            for slip in SLIPPAGES:
                s = summarize(latency_frame, slip)
                sensitivity_rows.append({"coin": coin, "latency_s": latency, "slippage_cents": int(round(slip * 100)), **s})

        grid, winner = threshold_search(coin, frame)
        if not grid.empty:
            grids.append(grid)
        if winner is not None:
            winners.append(winner)

        literal = base.sort_values("market_start")
        for slip in (0.00, 0.01, 0.02, 0.03, 0.05):
            for risk in RISK_FRACTIONS:
                result = bankroll_path(literal, slip, risk, strict_fok=False)
                bankroll_rows.append({"strategy": coin, "policy": "literal", "slippage_cents": int(slip*100), "risk_fraction": risk, "depth_model": "optimistic", **result})
                if risk in (0.10, 0.25, 1.00):
                    strict = bankroll_path(literal, slip, risk, strict_fok=True)
                    bankroll_rows.append({"strategy": coin, "policy": "literal", "slippage_cents": int(slip*100), "risk_fraction": risk, "depth_model": "strict_top_ask_FOK", **strict})
        streak = all_in_streak_distribution(literal, 0.01)
        streak_rows.append({"strategy": coin, "slippage_cents": 1, **streak})

    combined = pd.concat(all_frames, ignore_index=True)
    common_start = max(frame["market_start"].min() for frame in all_frames)
    common = combined.loc[combined["market_start"].ge(common_start) & combined["latency_s"].eq(1)].copy()

    best_of_7 = common.sort_values(["market_start", "leader_mid", "coin"], ascending=[True, False, True]).drop_duplicates("market_start")
    best_of_7["coin"] = "BEST_OF_7:" + best_of_7["coin"]
    all_frames.append(best_of_7)
    s = summarize(best_of_7, 0.01)
    literal_rows.append({"coin": "BEST_OF_7", "side": "Both", **s})
    grid, winner = threshold_search("BEST_OF_7", best_of_7.assign(latency_s=1))
    if not grid.empty:
        grids.append(grid)
    if winner is not None:
        winners.append(winner)
    for risk in RISK_FRACTIONS:
        result = bankroll_path(best_of_7, 0.01, risk, strict_fok=False)
        bankroll_rows.append({"strategy": "BEST_OF_7", "policy": "literal", "slippage_cents": 1, "risk_fraction": risk, "depth_model": "optimistic", **result})
    streak_rows.append({"strategy": "BEST_OF_7", "slippage_cents": 1, **all_in_streak_distribution(best_of_7, 0.01)})

    pooled_rows = []
    dates = sorted(pd.to_datetime(common["market_start"], utc=True).dt.date.unique())
    train_dates = set(dates[:-14])
    val_dates = set(dates[-14:-7])
    hold_dates = set(dates[-7:])
    date_series = pd.to_datetime(common["market_start"], utc=True).dt.date
    for threshold in THRESHOLDS:
        windows = equal_split_windows(common, 0.01, threshold)
        if windows.empty:
            continue
        wdates = pd.to_datetime(windows["market_start"], utc=True).dt.date
        def ws(ds):
            subset = windows.loc[wdates.isin(ds)]
            if subset.empty:
                return None
            return {
                "n": int(len(subset)),
                "mean_return": float(subset["portfolio_return"].mean()),
                "positive_rate": float((subset["portfolio_return"] > 0).mean()),
            }
        tr, va, ho = ws(train_dates), ws(val_dates), ws(hold_dates)
        if tr and va:
            pooled_rows.append({
                "threshold": threshold,
                "train_n": tr["n"], "train_mean_return": tr["mean_return"], "train_positive_rate": tr["positive_rate"],
                "validation_n": va["n"], "validation_mean_return": va["mean_return"], "validation_positive_rate": va["positive_rate"],
                "holdout_n": 0 if ho is None else ho["n"],
                "holdout_mean_return": None if ho is None else ho["mean_return"],
                "holdout_positive_rate": None if ho is None else ho["positive_rate"],
                "robust_score": min(tr["mean_return"], va["mean_return"]),
            })
    pooled_grid = pd.DataFrame(pooled_rows)
    pooled_selected = pd.DataFrame()
    if not pooled_grid.empty:
        eligible = pooled_grid.loc[(pooled_grid["train_mean_return"] > 0) & (pooled_grid["validation_mean_return"] > 0)]
        if not eligible.empty:
            selected = eligible.sort_values(["robust_score", "validation_n"], ascending=[False, False]).head(1)
            pooled_selected = selected.copy()
            threshold = float(selected.iloc[0]["threshold"])
            windows = equal_split_windows(common, 0.01, threshold)
            for risk in RISK_FRACTIONS:
                result = simulate_window_portfolio(windows, risk)
                bankroll_rows.append({"strategy": "EQUAL_SPLIT_7", "policy": f"mid>={threshold:.2f}", "slippage_cents": 1, "risk_fraction": risk, "depth_model": "optimistic", **result})

    literal_df = pd.DataFrame(literal_rows)
    sensitivity_df = pd.DataFrame(sensitivity_rows)
    grid_df = pd.concat(grids, ignore_index=True) if grids else pd.DataFrame()
    winners_df = pd.DataFrame(winners)
    bankroll_df = pd.DataFrame(bankroll_rows)
    streak_df = pd.DataFrame(streak_rows)

    literal_df.to_csv(OUT / "literal_by_coin_and_side.csv", index=False)
    sensitivity_df.to_csv(OUT / "latency_slippage_sensitivity.csv", index=False)
    grid_df.to_csv(OUT / "threshold_search_train_validation.csv", index=False)
    winners_df.to_csv(OUT / "selected_thresholds_holdout.csv", index=False)
    bankroll_df.to_csv(OUT / "bankroll_90_simulations.csv", index=False)
    streak_df.to_csv(OUT / "all_in_streak_statistics.csv", index=False)
    pooled_grid.to_csv(OUT / "equal_split_thresholds.csv", index=False)

    main_literal = literal_df.loc[(literal_df["side"] == "Both")].copy()
    main_slip = sensitivity_df.loc[(sensitivity_df["latency_s"] == 1) & sensitivity_df["slippage_cents"].isin([0,1,2,3,5])].copy()
    display_cols = ["coin","n","win_rate","avg_entry_price","avg_total_cost","mean_pnl_per_share","roi_on_cost","positive_day_rate","initial_90_fok_rate"]
    slippage_cols = ["coin","slippage_cents","n","win_rate","mean_pnl_per_share","roi_on_cost"]
    winner_cols = [c for c in ["strategy","min_leader_mid","max_spread","side","train_n","train_mean_pnl","validation_n","validation_mean_pnl","holdout_n","holdout_win_rate","holdout_mean_pnl_per_share","holdout_roi_on_cost","holdout_positive_day_rate"] if c in winners_df.columns]
    bank_display = bankroll_df.loc[(bankroll_df["slippage_cents"] == 1) & bankroll_df["risk_fraction"].isin([0.05,0.10,0.25,1.00]) & bankroll_df["depth_model"].eq("optimistic")]
    write_report(
        main_literal[display_cols].round(6),
        main_slip[slippage_cols].round(6),
        winners_df[winner_cols].round(6) if winner_cols else pd.DataFrame(),
        bank_display.round(4),
        streak_df.round(4),
        pooled_selected.round(6),
    )

    summary = {
        "method": {
            "decision_second": DECISION_SECOND,
            "leader_definition": "higher Up/Down midpoint at T+240",
            "entry": "selected side ask at T+240+latency, plus modeled slippage",
            "exit": "hold to binary resolution",
            "fee_formula": "0.07*p*(1-p) per share",
            "starting_bankroll": START_BANKROLL,
        },
        "rows": {
            "literal": len(literal_df),
            "sensitivity": len(sensitivity_df),
            "threshold_grid": len(grid_df),
            "selected_thresholds": len(winners_df),
            "bankroll": len(bankroll_df),
        },
        "selected_thresholds": winners,
        "equal_split_selected": pooled_selected.to_dict(orient="records"),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
