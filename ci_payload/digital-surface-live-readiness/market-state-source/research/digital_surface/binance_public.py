from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Mapping, Sequence


BINANCE_MARKET_DATA_BASE = "https://data-api.binance.vision"
BINANCE_SYMBOL = "BTCUSDT"
_INTERVAL_MS = {"1s": 1_000, "1m": 60_000}


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _payload_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class BinanceKline:
    open_time_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    close_time_ms: int


@dataclass(frozen=True, slots=True)
class BTCMarketState:
    symbol: str
    server_time_ms: int
    observed_ts_ms: int
    spot: Decimal
    vol_30s: float
    vol_120s: float
    strikes: dict[int, Decimal]
    closed_one_second_bars: int
    raw_response_sha256: dict[str, str]

    def as_json(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "server_time_ms": int(self.server_time_ms),
            "observed_ts_ms": int(self.observed_ts_ms),
            "spot": str(self.spot),
            "vol_30s": float(self.vol_30s),
            "vol_120s": float(self.vol_120s),
            "strikes": {str(key): str(value) for key, value in sorted(self.strikes.items())},
            "closed_one_second_bars": int(self.closed_one_second_bars),
            "raw_response_sha256": dict(sorted(self.raw_response_sha256.items())),
        }


def parse_klines(payload: object, *, interval: str) -> tuple[BinanceKline, ...]:
    if interval not in _INTERVAL_MS:
        raise ValueError(f"unsupported kline interval: {interval}")
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        raise ValueError("Binance klines payload must be a sequence")
    interval_ms = _INTERVAL_MS[interval]
    parsed: list[BinanceKline] = []
    for index, raw in enumerate(payload):
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) < 7:
            raise ValueError(f"Binance kline row {index} is malformed")
        open_time = int(raw[0])
        open_px = Decimal(str(raw[1]))
        high = Decimal(str(raw[2]))
        low = Decimal(str(raw[3]))
        close = Decimal(str(raw[4]))
        volume = Decimal(str(raw[5]))
        close_time = int(raw[6])
        if min(open_px, high, low, close) <= 0:
            raise ValueError("Binance kline prices must be positive")
        if volume < 0:
            raise ValueError("Binance kline volume must be non-negative")
        if high < max(open_px, close) or low > min(open_px, close) or low > high:
            raise ValueError("Binance kline OHLC values are inconsistent")
        if close_time < open_time:
            raise ValueError("Binance kline close time precedes open time")
        parsed.append(
            BinanceKline(
                open_time_ms=open_time,
                open=open_px,
                high=high,
                low=low,
                close=close,
                volume=volume,
                close_time_ms=close_time,
            )
        )
    parsed.sort(key=lambda item: item.open_time_ms)
    for previous, current in zip(parsed, parsed[1:]):
        if current.open_time_ms - previous.open_time_ms != interval_ms:
            raise ValueError(f"Binance {interval} klines must be contiguous")
    return tuple(parsed)


def realized_log_volatility(closes: Sequence[Decimal], *, returns: int) -> float:
    if returns <= 0:
        raise ValueError("returns must be positive")
    required = returns + 1
    if len(closes) < required:
        raise ValueError(f"realized volatility requires at least {required} close prices")
    trailing = [Decimal(value) for value in closes[-required:]]
    if any(value <= 0 for value in trailing):
        raise ValueError("close prices must be positive")
    log_returns = [math.log(float(current / previous)) for previous, current in zip(trailing, trailing[1:])]
    return float(statistics.pstdev(log_returns))


def _default_get(url: str, **kwargs: Any):
    import requests

    return requests.get(url, **kwargs)


def _get_json(
    get: Callable[..., Any],
    url: str,
    *,
    params: Mapping[str, object] | None = None,
    timeout_seconds: float = 15.0,
) -> object:
    kwargs: dict[str, object] = {"timeout": timeout_seconds}
    if params is not None:
        kwargs["params"] = dict(params)
    response = get(url, **kwargs)
    response.raise_for_status()
    return response.json()


def collect_btc_market_state(
    boundary_open_ms: Sequence[int],
    *,
    get: Callable[..., Any] | None = None,
    observed_ts_ms: int | None = None,
    timeout_seconds: float = 15.0,
) -> BTCMarketState:
    fetch = get or _default_get
    server_payload = _get_json(
        fetch,
        f"{BINANCE_MARKET_DATA_BASE}/api/v3/time",
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(server_payload, Mapping) or "serverTime" not in server_payload:
        raise ValueError("Binance server-time response is malformed")
    server_time_ms = int(server_payload["serverTime"])
    if server_time_ms < 0:
        raise ValueError("Binance server time must be non-negative")

    one_second_payload = _get_json(
        fetch,
        f"{BINANCE_MARKET_DATA_BASE}/api/v3/klines",
        params={
            "symbol": BINANCE_SYMBOL,
            "interval": "1s",
            "endTime": server_time_ms,
            "limit": 122,
        },
        timeout_seconds=timeout_seconds,
    )
    one_second_all = parse_klines(one_second_payload, interval="1s")
    closed = [item for item in one_second_all if item.close_time_ms <= server_time_ms]
    if len(closed) < 121:
        raise ValueError(f"need at least 121 closed one-second bars, found {len(closed)}")
    closed = closed[-121:]
    for previous, current in zip(closed, closed[1:]):
        if current.open_time_ms - previous.open_time_ms != 1_000:
            raise ValueError("closed one-second klines must be contiguous")
    closes = [item.close for item in closed]

    strikes: dict[int, Decimal] = {}
    raw_hashes = {
        "server_time": _payload_sha256(server_payload),
        "one_second_klines": _payload_sha256(one_second_payload),
    }
    for boundary in sorted({int(value) for value in boundary_open_ms}):
        if boundary < 0 or boundary % 60_000:
            raise ValueError(f"strike boundary must be a non-negative minute epoch in milliseconds: {boundary}")
        strike_payload = _get_json(
            fetch,
            f"{BINANCE_MARKET_DATA_BASE}/api/v3/klines",
            params={
                "symbol": BINANCE_SYMBOL,
                "interval": "1m",
                "startTime": boundary,
                "endTime": boundary + 59_999,
                "limit": 1,
            },
            timeout_seconds=timeout_seconds,
        )
        strike_rows = parse_klines(strike_payload, interval="1m")
        if len(strike_rows) != 1 or strike_rows[0].open_time_ms != boundary:
            returned = None if not strike_rows else strike_rows[0].open_time_ms
            raise ValueError(f"Binance did not return the exact boundary {boundary}; returned {returned}")
        strikes[boundary] = strike_rows[0].open
        raw_hashes[f"strike:{boundary}"] = _payload_sha256(strike_payload)

    observed = int(time.time() * 1000) if observed_ts_ms is None else int(observed_ts_ms)
    if observed < 0:
        raise ValueError("observed_ts_ms must be non-negative")
    return BTCMarketState(
        symbol=BINANCE_SYMBOL,
        server_time_ms=server_time_ms,
        observed_ts_ms=observed,
        spot=closes[-1],
        vol_30s=realized_log_volatility(closes, returns=30),
        vol_120s=realized_log_volatility(closes, returns=120),
        strikes=strikes,
        closed_one_second_bars=len(closed),
        raw_response_sha256=raw_hashes,
    )
