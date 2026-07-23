from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

MODULE_PATH = Path(__file__).with_name("hourly_orderbook_transfer.py")
spec = importlib.util.spec_from_file_location("hourly_orderbook_transfer", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load {MODULE_PATH}")
transfer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transfer)

_original_choose_col = transfer.choose_col


def _choose_col_with_ts_ms(names, *candidates):
    if candidates == ("timestamp_ms", "timestamp"):
        candidates = candidates + ("ts_ms",)
    return _original_choose_col(names, *candidates)


def _execute_after_arrival(
    signals,
    wide,
    ticks,
    shares,
    tape_window_ms=1500,
    latency_ms=1000,
    max_gap_ms=4000,
):
    """Require the displayed book and corroborating tape after order arrival."""
    rows = []
    books = {
        str(mid): g.sort_values("timestamp_ms")
        for mid, g in wide.groupby("market_id", sort=False)
    }
    tapes = {
        str(mid): g.sort_values("timestamp_ms")
        for mid, g in ticks.groupby("market_id", sort=False)
    }

    for signal in signals.itertuples(index=False):
        market_id = str(signal.market_id)
        book = books.get(market_id)
        arrival_ms = int(signal.timestamp_ms + latency_ms)
        if book is None:
            continue

        book_ts = book.timestamp_ms.to_numpy(dtype=np.int64)
        k = int(np.searchsorted(book_ts, arrival_ms, side="left"))
        if k >= len(book) or int(book.iloc[k].timestamp_ms) - arrival_ms > max_gap_ms:
            continue

        arrival = book.iloc[k]
        ask = float(arrival.up_ask if signal.side_up else arrival.down_ask)
        ask_size = float(
            arrival.up_ask_size if signal.side_up else arrival.down_ask_size
        )
        if not (
            np.isfinite(ask)
            and np.isfinite(ask_size)
            and ask <= signal.target_px + 1e-9
            and ask_size >= shares
        ):
            continue

        tape = tapes.get(market_id)
        tape_shares = 0.0
        if tape is not None:
            outcome = "up" if signal.side_up else "down"
            qualifying = tape[
                (tape.timestamp_ms >= arrival_ms)
                & (tape.timestamp_ms <= arrival_ms + tape_window_ms)
                & (tape.outcome.astype(str).str.lower() == outcome)
                & (tape.price <= signal.target_px + 1e-9)
            ]
            tape_shares = float(
                (qualifying.size_usdc / qualifying.price.clip(lower=0.01)).sum()
            )
        if tape_shares < shares:
            continue

        won = bool((int(signal.resolution) == 1) == bool(signal.side_up))
        rows.append(
            {
                "market_id": market_id,
                "crypto": signal.crypto,
                "spec": signal.spec,
                "week_start": signal.week_start,
                "signal_ts_ms": int(signal.timestamp_ms),
                "arrival_ms": arrival_ms,
                "s2c": float(signal.s2c),
                "side_up": bool(signal.side_up),
                "won": won,
                "decision_ask": float(signal.side_ask),
                "arrival_ask": ask,
                "arrival_ask_size": ask_size,
                "tape_shares": tape_shares,
                "fill_px": ask,
                "target_px": float(signal.target_px),
                "requested_shares": float(shares),
                "dist_bps": float(signal.dist_bps),
                "mom_bps": float(signal.mom_bps),
            }
        )
    return pd.DataFrame(rows)


transfer.choose_col = _choose_col_with_ts_ms
transfer.execute = _execute_after_arrival

if __name__ == "__main__":
    transfer.main()
