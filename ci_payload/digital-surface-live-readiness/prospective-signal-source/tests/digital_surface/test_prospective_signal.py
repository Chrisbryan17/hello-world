import json
from decimal import Decimal

from research.digital_surface.binance_public import BTCMarketState
from research.digital_surface.market_discovery import GammaMarketRecord
from research.digital_surface.prospective_signal import (
    FrozenSurfacePolicy,
    generate_prospective_candidates,
    load_frozen_surface_policy,
)
from research.digital_surface.public_books import parse_public_order_book


def market(condition, *, epoch, duration, token_prefix):
    return GammaMarketRecord(
        condition_id=condition,
        slug=f"btc-updown-{duration // 60}m-{epoch}",
        question="Bitcoin Up or Down",
        yes_token_id=f"yes-{token_prefix}",
        no_token_id=f"no-{token_prefix}",
        duration_seconds=duration,
        open_epoch_seconds=epoch,
        end_date="2030-01-01T00:00:00Z",
        tick_size=Decimal("0.01"),
    )


def book(token, condition, yes_ask="0.45", no_ask="0.45", size="10"):
    ask = yes_ask if token.startswith("yes-") else no_ask
    return parse_public_order_book({
        "market": condition,
        "asset_id": token,
        "timestamp": "1250000",
        "hash": f"hash-{token}",
        "bids": [{"price": "0.40", "size": size}],
        "asks": [{"price": ask, "size": size}],
        "min_order_size": "1",
        "tick_size": "0.01",
        "neg_risk": False,
    })


def policy_payload():
    return {
        "version": 1,
        "model": {
            "coefficients": [0.0, 1.0, 0.0, 0.0],
            "training_rows": 1000,
            "training_contracts": 500,
        },
        "candidate": {
            "min_edge": 0.02,
            "max_total_cost": 1.25,
            "min_tau_s": 3.0,
            "max_tau_s": 60.0,
            "decision_cadence_s": 5,
            "pair_gap_ms": 2000,
            "slippage": 0.01,
            "uncertainty_penalty": 0.0,
        },
        "selection": "first_trigger_per_expiry",
        "flow_assumption": "zero_without_public_causal_trade_flow",
    }


def setup_case():
    five = market("five", epoch=1_000, duration=300, token_prefix="five")
    fifteen = market("fifteen", epoch=400, duration=900, token_prefix="fifteen")
    books = {
        five.yes_token_id: book(five.yes_token_id, five.condition_id),
        five.no_token_id: book(five.no_token_id, five.condition_id),
        fifteen.yes_token_id: book(fifteen.yes_token_id, fifteen.condition_id),
        fifteen.no_token_id: book(fifteen.no_token_id, fifteen.condition_id),
    }
    state = BTCMarketState(
        symbol="BTCUSDT",
        server_time_ms=1_250_000,
        observed_ts_ms=1_250_000,
        spot=Decimal("100"),
        vol_30s=0.001,
        vol_120s=0.0015,
        strikes={1_000_000: Decimal("99"), 400_000: Decimal("101")},
        closed_one_second_bars=121,
        raw_response_sha256={
            "server_time": "a"*64,
            "one_second_klines": "b"*64,
            "strike:1000000": "c"*64,
            "strike:400000": "d"*64,
        },
    )
    return [five, fifteen], books, state


def test_loads_frozen_policy_and_hashes_exact_file_bytes(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy_payload(), indent=2, sort_keys=True) + "\n")
    policy = load_frozen_surface_policy(path)
    assert isinstance(policy, FrozenSurfacePolicy)
    assert policy.config.config_id == "e0.0200-c1.2500-tau3-60-cad5-slip0.010-u0.00"
    assert len(policy.policy_sha256) == 64
    assert policy.training_contracts == 500


def test_generates_original_same_expiry_lower_yes_higher_no_candidate():
    markets, books, state = setup_case()
    policy = FrozenSurfacePolicy.from_payload(policy_payload(), policy_sha256="1"*64)
    candidates, summary = generate_prospective_candidates(
        markets,
        books,
        state,
        book_observed_ts_ms=1_250_000,
        policy=policy,
        prospective_head_sha256="2"*64,
        book_ledger_head_sha256="3"*64,
        spot_state_head_sha256="4"*64,
    )
    assert len(candidates) == 1
    row = candidates.iloc[0]
    assert row["low_condition_id"] == "five"
    assert row["high_condition_id"] == "fifteen"
    assert row["low_yes_token_id"] == "yes-five"
    assert row["high_no_token_id"] == "no-fifteen"
    assert row["low_strike"] == 99.0
    assert row["high_strike"] == 101.0
    assert row["theoretical_edge"] >= 0.02
    assert row["policy_sha256"] == "1"*64
    assert row["prospective_head_sha256"] == "2"*64
    assert bool(row["transactionally_atomic"]) is False
    assert summary["candidates_selected"] == 1
    assert summary["future_outcomes_used"] == 0


def test_fails_closed_on_missing_exact_strike_or_stale_book_evidence():
    markets, books, state = setup_case()
    policy = FrozenSurfacePolicy.from_payload(policy_payload(), policy_sha256="1"*64)
    broken = BTCMarketState(
        symbol=state.symbol,
        server_time_ms=state.server_time_ms,
        observed_ts_ms=state.observed_ts_ms,
        spot=state.spot,
        vol_30s=state.vol_30s,
        vol_120s=state.vol_120s,
        strikes={1_000_000: Decimal("99")},
        closed_one_second_bars=state.closed_one_second_bars,
        raw_response_sha256=state.raw_response_sha256,
    )
    try:
        generate_prospective_candidates(
            markets, books, broken, book_observed_ts_ms=1_250_000, policy=policy,
            prospective_head_sha256="2"*64, book_ledger_head_sha256="3"*64,
            spot_state_head_sha256="4"*64,
        )
    except ValueError as exc:
        assert "missing exact strike" in str(exc)
    else:
        raise AssertionError("missing strike did not fail closed")

    try:
        generate_prospective_candidates(
            markets, books, state, book_observed_ts_ms=1_240_000, policy=policy,
            prospective_head_sha256="2"*64, book_ledger_head_sha256="3"*64,
            spot_state_head_sha256="4"*64, max_evidence_age_ms=2_000,
        )
    except ValueError as exc:
        assert "stale evidence" in str(exc)
    else:
        raise AssertionError("stale evidence did not fail closed")
