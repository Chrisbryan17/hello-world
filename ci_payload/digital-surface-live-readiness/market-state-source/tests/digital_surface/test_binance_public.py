import hashlib
import json
import math
from decimal import Decimal

import pytest

from research.digital_surface.binance_public import (
    BINANCE_MARKET_DATA_BASE,
    collect_btc_market_state,
    parse_klines,
    realized_log_volatility,
)


class Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def row(open_ms: int, close: str, *, interval_ms: int = 1_000, open_price: str | None = None):
    price = open_price or close
    return [
        open_ms,
        price,
        str(Decimal(price) + Decimal("1")),
        str(Decimal(price) - Decimal("1")),
        close,
        "1.0",
        open_ms + interval_ms - 1,
        "1.0",
        1,
        "0.5",
        "0.5",
        "0",
    ]


def test_parse_klines_rejects_nonpositive_prices_and_time_gaps():
    with pytest.raises(ValueError, match="positive"):
        parse_klines([row(0, "0")], interval="1s")

    with pytest.raises(ValueError, match="contiguous"):
        parse_klines([row(0, "100"), row(2_000, "101")], interval="1s")


def test_realized_log_volatility_uses_exact_trailing_return_count():
    closes = [Decimal(str(math.exp(index * 0.001))) for index in range(121)]
    assert realized_log_volatility(closes, returns=30) == pytest.approx(0.0, abs=1e-15)
    assert realized_log_volatility(closes, returns=120) == pytest.approx(0.0, abs=1e-15)
    with pytest.raises(ValueError, match="121 close prices"):
        realized_log_volatility(closes[:-1], returns=120)


def test_collects_closed_one_second_state_and_exact_boundary_strikes_without_auth_headers():
    boundary_a = 1_800_000
    boundary_b = 2_100_000
    server_time = 5_000_000
    observed_time = 5_000_123
    calls = []

    closes = [Decimal("100") + Decimal(index) / Decimal("10") for index in range(122)]
    one_second = [row(4_878_000 + index * 1_000, str(price)) for index, price in enumerate(closes)]
    # The newest candle is still open at server_time and must be excluded.
    one_second[-1][6] = server_time + 999

    one_minute = {
        boundary_a: [row(boundary_a, "101.25", interval_ms=60_000, open_price="101.25")],
        boundary_b: [row(boundary_b, "102.50", interval_ms=60_000, open_price="102.50")],
    }

    def get(url, **kwargs):
        calls.append((url, kwargs))
        assert "headers" not in kwargs
        if url == f"{BINANCE_MARKET_DATA_BASE}/api/v3/time":
            return Response({"serverTime": server_time})
        assert url == f"{BINANCE_MARKET_DATA_BASE}/api/v3/klines"
        params = kwargs["params"]
        assert params["symbol"] == "BTCUSDT"
        if params["interval"] == "1s":
            assert params["limit"] == 122
            assert params["endTime"] == server_time
            return Response(one_second)
        assert params["interval"] == "1m"
        assert params["limit"] == 1
        assert params["endTime"] == params["startTime"] + 59_999
        return Response(one_minute[params["startTime"]])

    state = collect_btc_market_state(
        [boundary_b, boundary_a, boundary_a],
        get=get,
        observed_ts_ms=observed_time,
    )

    assert state.server_time_ms == server_time
    assert state.observed_ts_ms == observed_time
    assert state.spot == closes[-2]
    assert state.strikes == {
        boundary_a: Decimal("101.25"),
        boundary_b: Decimal("102.50"),
    }
    assert state.closed_one_second_bars == 121
    assert state.vol_30s >= 0
    assert state.vol_120s >= 0
    assert set(state.raw_response_sha256) == {"server_time", "one_second_klines", f"strike:{boundary_a}", f"strike:{boundary_b}"}
    assert all(len(value) == 64 for value in state.raw_response_sha256.values())
    assert len(calls) == 4


def test_exact_boundary_strike_fails_closed_when_binance_returns_another_minute():
    boundary = 1_800_000
    server_time = 5_000_000
    one_second = [row(4_879_000 + index * 1_000, str(100 + index / 10)) for index in range(121)]

    def get(url, **kwargs):
        if url.endswith("/time"):
            return Response({"serverTime": server_time})
        params = kwargs["params"]
        if params["interval"] == "1s":
            return Response(one_second)
        return Response([row(boundary + 60_000, "100", interval_ms=60_000)])

    with pytest.raises(ValueError, match="exact boundary"):
        collect_btc_market_state([boundary], get=get, observed_ts_ms=server_time)
