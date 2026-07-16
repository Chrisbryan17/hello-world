#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import re
import statistics
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

DATA = "https://data-api.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
OUT = Path("output")
OUT.mkdir(exist_ok=True)
UTC = timezone.utc
NOW = int(time.time())
LOOKBACK_DAYS = 7
START = NOW - LOOKBACK_DAYS * 86400
SHARES = 5.0
SLIPPAGES = (0.0, 0.01, 0.02)
BTC_RE = re.compile(r"btc-updown-(5m|15m)-(\d{10})$")
KNOWN_WALLET = "0xd02b6d910a38479c3125308fc4737a46509cd6df"


def new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "polymarket-live-copyability-scan/1.0"})
    return s


def get_json(session: requests.Session, url: str, params: dict[str, Any] | None = None, retries: int = 8) -> Any:
    delay = 0.75
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=60)
            if r.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"retryable HTTP {r.status_code}: {r.text[:200]}")
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            last = exc
            if attempt == retries - 1:
                break
            time.sleep(delay)
            delay = min(delay * 2, 15)
    raise RuntimeError(f"GET failed: {url} params={params}: {last}")


def parse_slug(slug: str) -> tuple[int, int, int] | None:
    m = BTC_RE.search(slug or "")
    if not m:
        return None
    duration = 300 if m.group(1) == "5m" else 900
    start = int(m.group(2))
    return start, start + duration, duration


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def winner_from_market(market: dict[str, Any]) -> str | None:
    outcomes = as_list(market.get("outcomes"))
    prices = as_list(market.get("outcomePrices"))
    if len(outcomes) != len(prices) or not outcomes:
        return None
    vals = [float(x) for x in prices]
    idx = max(range(len(vals)), key=vals.__getitem__)
    return str(outcomes[idx]) if vals[idx] >= 0.99 else None


def fetch_market_map() -> dict[str, dict[str, Any]]:
    session = new_session()
    start_iso = datetime.fromtimestamp(START - 3600, UTC).isoformat().replace("+00:00", "Z")
    end_iso = datetime.fromtimestamp(NOW + 3600, UTC).isoformat().replace("+00:00", "Z")
    result: dict[str, dict[str, Any]] = {}
    offset = 0
    while True:
        page = get_json(
            session,
            f"{GAMMA}/markets",
            {
                "closed": "true",
                "end_date_min": start_iso,
                "end_date_max": end_iso,
                "order": "end_date",
                "ascending": "true",
                "limit": 500,
                "offset": offset,
            },
        )
        if not isinstance(page, list):
            raise TypeError("Unexpected Gamma markets response")
        for m in page:
            slug = str(m.get("slug", ""))
            parsed = parse_slug(slug)
            if not parsed:
                continue
            st, en, duration = parsed
            winner = winner_from_market(m)
            if winner and START <= en <= NOW:
                result[str(m.get("conditionId", ""))] = {
                    "slug": slug,
                    "title": m.get("question") or m.get("title") or slug,
                    "start": st,
                    "end": en,
                    "duration": duration,
                    "winner": winner,
                    "order_min_size": float(m.get("orderMinSize") or 5),
                }
        print("MARKETS", offset, len(page), "BTC_RESOLVED", len(result), flush=True)
        offset += len(page)
        if len(page) < 500:
            break
        if offset > 10000:
            raise RuntimeError("Market pagination exceeded safety cap")
    return result


def fetch_leaderboards() -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    session = new_session()
    boards: dict[str, list[dict[str, Any]]] = {}
    merged: dict[str, dict[str, Any]] = {}
    limits = {"DAY": 15, "WEEK": 20, "MONTH": 20}
    for period, limit in limits.items():
        rows = get_json(
            session,
            f"{DATA}/v1/leaderboard",
            {
                "category": "CRYPTO",
                "timePeriod": period,
                "orderBy": "PNL",
                "limit": limit,
                "offset": 0,
            },
        )
        boards[period] = rows
        for row in rows:
            wallet = str(row.get("proxyWallet", "")).lower()
            if not wallet:
                continue
            item = merged.setdefault(
                wallet,
                {
                    "wallet": wallet,
                    "username": row.get("userName") or wallet,
                    "periods": [],
                    "day_rank": None,
                    "day_pnl": None,
                    "day_volume": None,
                    "week_rank": None,
                    "week_pnl": None,
                    "week_volume": None,
                    "month_rank": None,
                    "month_pnl": None,
                    "month_volume": None,
                },
            )
            item["periods"].append(period)
            prefix = period.lower()
            item[f"{prefix}_rank"] = int(row.get("rank"))
            item[f"{prefix}_pnl"] = float(row.get("pnl") or 0)
            item[f"{prefix}_volume"] = float(row.get("vol") or 0)
            if row.get("userName"):
                item["username"] = row.get("userName")
    if KNOWN_WALLET not in merged:
        merged[KNOWN_WALLET] = {
            "wallet": KNOWN_WALLET,
            "username": "wowitsamazing",
            "periods": ["CONTROL"],
            "day_rank": None,
            "day_pnl": None,
            "day_volume": None,
            "week_rank": None,
            "week_pnl": None,
            "week_volume": None,
            "month_rank": None,
            "month_pnl": None,
            "month_volume": None,
        }
    return boards, merged


def trade_key(x: dict[str, Any]) -> tuple[Any, ...]:
    return (
        x.get("transactionHash"), x.get("asset"), x.get("timestamp"), x.get("side"),
        x.get("size"), x.get("price"), x.get("conditionId"),
    )


def fetch_interval(session: requests.Session, wallet: str, a: int, b: int, depth: int = 0) -> list[dict[str, Any]]:
    page = get_json(
        session,
        f"{DATA}/trades",
        {
            "user": wallet,
            "limit": 1000,
            "offset": 0,
            "takerOnly": "false",
            "start": a,
            "end": b,
        },
    )
    if len(page) < 1000:
        return page
    if b - a <= 2 or depth >= 24:
        raise RuntimeError(f"uncopyably dense interval {wallet} {a}-{b}")
    mid = (a + b) // 2
    return fetch_interval(session, wallet, a, mid, depth + 1) + fetch_interval(session, wallet, mid + 1, b, depth + 1)


def fetch_wallet_trades(wallet: str, market_map: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    session = new_session()
    try:
        rows: list[dict[str, Any]] = []
        cursor = datetime.fromtimestamp(START, UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        final = datetime.fromtimestamp(NOW, UTC)
        while cursor <= final:
            a = max(START, int(cursor.timestamp()))
            b = min(NOW, int((cursor + timedelta(days=1)).timestamp()) - 1)
            if a <= b:
                rows.extend(fetch_interval(session, wallet, a, b))
            cursor += timedelta(days=1)
        unique = {trade_key(x): x for x in rows}
        filtered = [
            x for x in unique.values()
            if str(x.get("conditionId", "")) in market_map
            and str(x.get("side", "")).upper() in ("BUY", "SELL")
        ]
        filtered.sort(key=lambda x: (int(x.get("timestamp", 0)), str(x.get("transactionHash", ""))))
        return filtered, None
    except Exception as exc:
        return [], repr(exc)


def fee(shares: float, p: float) -> float:
    return shares * 0.07 * p * (1.0 - p)


def signal_metrics(signals: list[dict[str, Any]], slip: float) -> dict[str, Any]:
    pnl_values: list[float] = []
    turnover = 0.0
    fees = 0.0
    wins = 0
    loss_streak = max_loss_streak = 0
    equity = peak = 0.0
    max_dd = 0.0
    for s in signals:
        p = min(0.99, max(0.01, float(s["price"]) + slip))
        f = fee(SHARES, p)
        cost = SHARES * p + f
        pnl = SHARES - cost if s["won"] else -cost
        pnl_values.append(pnl)
        turnover += SHARES * p
        fees += f
        if s["won"]:
            wins += 1
            loss_streak = 0
        else:
            loss_streak += 1
            max_loss_streak = max(max_loss_streak, loss_streak)
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    n = len(signals)
    gross_profit = sum(x for x in pnl_values if x > 0)
    gross_loss = -sum(x for x in pnl_values if x < 0)
    return {
        "signals": n,
        "wins": wins,
        "losses": n - wins,
        "win_rate": wins / n if n else None,
        "avg_price": statistics.mean(min(0.99, max(0.01, float(s["price"]) + slip)) for s in signals) if n else None,
        "turnover": turnover,
        "fees": fees,
        "net_pnl": sum(pnl_values),
        "avg_pnl": statistics.mean(pnl_values) if n else None,
        "roi": sum(pnl_values) / turnover if turnover else None,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "max_loss_streak": max_loss_streak,
        "max_drawdown_dollars": max_dd,
    }


def analyze_wallet(meta: dict[str, Any], trades: list[dict[str, Any]], market_map: dict[str, dict[str, Any]], error: str | None) -> dict[str, Any]:
    base = dict(meta)
    base["fetch_error"] = error
    base["raw_btc_fills_7d"] = len(trades)
    if error or not trades:
        base["status"] = "REJECT"
        base["reason"] = error or "No resolved BTC 5m/15m fills in seven days"
        return base

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        grouped[str(t.get("conditionId", ""))].append(t)
    for rows in grouped.values():
        rows.sort(key=lambda r: (int(r.get("timestamp", 0)), str(r.get("transactionHash", ""))))

    strategy_signals: dict[str, list[dict[str, Any]]] = {
        "first_buy_90s": [],
        "first_large_25_90s": [],
        "confirmed_100_80_90s": [],
    }
    both_sides_count = 0
    latest_btc_ts = 0
    analyzed_markets = 0

    for cid, rows in grouped.items():
        market = market_map[cid]
        buys = [r for r in rows if str(r.get("side", "")).upper() == "BUY"]
        if not buys:
            continue
        analyzed_markets += 1
        latest_btc_ts = max(latest_btc_ts, max(int(r.get("timestamp", 0)) for r in rows))
        buy_notional: dict[str, float] = defaultdict(float)
        for r in buys:
            buy_notional[str(r.get("outcome", ""))] += float(r.get("size") or 0) * float(r.get("price") or 0)
        both = len([v for v in buy_notional.values() if v > 0]) > 1
        both_sides_count += int(both)
        final_dom = max(buy_notional, key=buy_notional.get)

        first = buys[0]
        first_lead = market["end"] - int(first.get("timestamp", 0))
        if first_lead >= 90:
            strategy_signals["first_buy_90s"].append({
                "condition_id": cid, "slug": market["slug"], "title": market["title"],
                "timestamp": int(first["timestamp"]), "end": market["end"], "lead": first_lead,
                "side": str(first["outcome"]), "price": float(first["price"]),
                "winner": market["winner"], "won": str(first["outcome"]) == market["winner"],
                "final_dominant": final_dom, "reversed": str(first["outcome"]) != final_dom,
                "both_sides": both,
            })

        large = next((r for r in buys if float(r.get("size") or 0) * float(r.get("price") or 0) >= 25 and market["end"] - int(r["timestamp"]) >= 90), None)
        if large:
            strategy_signals["first_large_25_90s"].append({
                "condition_id": cid, "slug": market["slug"], "title": market["title"],
                "timestamp": int(large["timestamp"]), "end": market["end"], "lead": market["end"] - int(large["timestamp"]),
                "side": str(large["outcome"]), "price": float(large["price"]),
                "winner": market["winner"], "won": str(large["outcome"]) == market["winner"],
                "final_dominant": final_dom, "reversed": str(large["outcome"]) != final_dom,
                "both_sides": both,
            })

        cumulative: dict[str, float] = defaultdict(float)
        confirmed = None
        for r in buys:
            outcome = str(r.get("outcome", ""))
            cumulative[outcome] += float(r.get("size") or 0) * float(r.get("price") or 0)
            total = sum(cumulative.values())
            leader = max(cumulative, key=cumulative.get)
            share = cumulative[leader] / total if total else 0
            lead = market["end"] - int(r["timestamp"])
            if cumulative[leader] >= 100 and share >= 0.80 and lead >= 90:
                confirmed = (r, leader, share, lead)
                break
        if confirmed:
            r, leader, share, lead = confirmed
            strategy_signals["confirmed_100_80_90s"].append({
                "condition_id": cid, "slug": market["slug"], "title": market["title"],
                "timestamp": int(r["timestamp"]), "end": market["end"], "lead": lead,
                "side": leader, "price": float(r["price"]), "winner": market["winner"],
                "won": leader == market["winner"], "final_dominant": final_dom,
                "reversed": leader != final_dom, "both_sides": both, "flow_share": share,
            })

    base.update({
        "btc_markets_7d": analyzed_markets,
        "latest_btc_trade_epoch": latest_btc_ts,
        "latest_btc_trade_utc": datetime.fromtimestamp(latest_btc_ts, UTC).isoformat() if latest_btc_ts else None,
        "latest_btc_trade_age_hours": (NOW - latest_btc_ts) / 3600 if latest_btc_ts else None,
        "both_sides_market_rate": both_sides_count / analyzed_markets if analyzed_markets else None,
    })

    strategy_rows = []
    for name, sigs in strategy_signals.items():
        sigs.sort(key=lambda x: x["timestamp"])
        row: dict[str, Any] = {
            "strategy": name,
            "signal_count": len(sigs),
            "signals_last_24h": sum(s["timestamp"] >= NOW - 86400 for s in sigs),
            "latest_signal_epoch": max((s["timestamp"] for s in sigs), default=0),
            "latest_signal_utc": datetime.fromtimestamp(max((s["timestamp"] for s in sigs), default=0), UTC).isoformat() if sigs else None,
            "median_lead_seconds": statistics.median(s["lead"] for s in sigs) if sigs else None,
            "reversal_rate": statistics.mean(float(s["reversed"]) for s in sigs) if sigs else None,
            "hedged_market_rate": statistics.mean(float(s["both_sides"]) for s in sigs) if sigs else None,
        }
        for slip in SLIPPAGES:
            metrics = signal_metrics(sigs, slip)
            suffix = f"{int(slip * 100)}c"
            for key, value in metrics.items():
                row[f"{key}_{suffix}"] = value
        if sigs:
            n = len(sigs)
            avg1 = float(row["avg_pnl_1c"])
            avg2 = float(row["avg_pnl_2c"])
            reversal = float(row["reversal_rate"] or 0)
            hedge = float(row["hedged_market_rate"] or 0)
            streak = float(row["max_loss_streak_1c"] or 0)
            row["score"] = 100 * avg1 + 70 * avg2 + 2.5 * math.log1p(n) - 18 * reversal - 8 * hedge - 1.5 * streak
            passes = (
                n >= 50
                and row["signals_last_24h"] >= 1
                and avg1 > 0
                and avg2 >= 0
                and row["roi_1c"] > 0
                and row["max_loss_streak_1c"] <= 4
                and reversal <= 0.20
            )
            watch = n >= 30 and row["signals_last_24h"] >= 1 and avg1 > 0
            row["grade"] = "PASS" if passes else ("WATCH" if watch else "REJECT")
        else:
            row["score"] = -1e9
            row["grade"] = "REJECT"
        strategy_rows.append(row)

    strategy_rows.sort(key=lambda x: x["score"], reverse=True)
    best = strategy_rows[0]
    base["strategies"] = strategy_rows
    base["best_strategy"] = best["strategy"]
    base["best_grade"] = best["grade"]
    base["best_score"] = best["score"]
    for k, v in best.items():
        if k not in ("strategy", "grade", "score"):
            base[f"best_{k}"] = v
    base["status"] = best["grade"]
    base["reason"] = (
        "Passes seven-day live-executable fee/slippage screen"
        if best["grade"] == "PASS"
        else "Positive at +1c but fails one or more durability filters"
        if best["grade"] == "WATCH"
        else "No live-executable BTC signal remained profitable and durable after fees/slippage"
    )
    base["_signals"] = strategy_signals
    return base


def flatten_candidate(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in ("strategies", "_signals")}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                fields.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    markets = fetch_market_map()
    boards, candidates = fetch_leaderboards()
    print("CANDIDATES", len(candidates), "RESOLVED_MARKETS", len(markets), flush=True)

    fetched: dict[str, tuple[list[dict[str, Any]], str | None]] = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(fetch_wallet_trades, wallet, markets): wallet for wallet in candidates}
        for future in as_completed(futures):
            wallet = futures[future]
            fetched[wallet] = future.result()
            print("FETCHED", wallet, len(fetched[wallet][0]), fetched[wallet][1], flush=True)

    analyzed = []
    for wallet, meta in candidates.items():
        trades, error = fetched[wallet]
        analyzed.append(analyze_wallet(meta, trades, markets, error))
    analyzed.sort(key=lambda x: (0 if x.get("status") == "PASS" else 1 if x.get("status") == "WATCH" else 2, -float(x.get("best_score") or -1e9)))

    top = analyzed[0] if analyzed else None
    top_signals = []
    if top and top.get("_signals"):
        top_signals = top["_signals"].get(top.get("best_strategy"), [])
        top_signals = sorted(top_signals, key=lambda x: x["timestamp"], reverse=True)

    all_strategy_rows = []
    for row in analyzed:
        for strategy in row.get("strategies", []):
            all_strategy_rows.append({
                "wallet": row["wallet"], "username": row["username"], "status": row["status"],
                **strategy,
            })

    summary = {
        "generated_utc": datetime.fromtimestamp(NOW, UTC).isoformat(),
        "window_start_utc": datetime.fromtimestamp(START, UTC).isoformat(),
        "window_end_utc": datetime.fromtimestamp(NOW, UTC).isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "resolved_btc_markets": len(markets),
        "candidate_wallets": len(analyzed),
        "pass_count": sum(x.get("status") == "PASS" for x in analyzed),
        "watch_count": sum(x.get("status") == "WATCH" for x in analyzed),
        "top_candidate": flatten_candidate(top) if top else None,
        "selection_note": "No wallet is guaranteed profitable. PASS means historical seven-day live-executable signals survived taker fees and 1c/2c adverse slippage under the stated rules.",
    }

    (OUT / "leaderboards.json").write_text(json.dumps(boards, indent=2), encoding="utf-8")
    (OUT / "scan_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT / "all_candidates.json").write_text(json.dumps([{k: v for k, v in x.items() if k != "_signals"} for x in analyzed], indent=2), encoding="utf-8")
    write_csv(OUT / "ranked_candidates.csv", [flatten_candidate(x) for x in analyzed])
    write_csv(OUT / "all_strategy_metrics.csv", all_strategy_rows)
    write_csv(OUT / "top_candidate_signals.csv", top_signals)
    print("SUMMARY", json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
