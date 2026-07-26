from __future__ import annotations

import math

import pytest

from late_favorite_transfer import evaluate_market, fee_per_share, frozen_policy


def signal(up: float, down: float) -> dict[str, float]:
    return {"au": up, "ad": down}


def arrival(up: float, down: float, up_size: float = 5.0, down_size: float = 5.0) -> dict[str, float]:
    return {"au": up, "ad": down, "sau": up_size, "sad": down_size}


def test_frozen_policy_matches_the_reviewed_candidate() -> None:
    assert frozen_policy() == {
        "assets": ("btc", "eth"),
        "entry_second": 210,
        "signal_ask_min": 0.85,
        "latency_seconds": 1,
        "fok_limit": "signal_ask",
        "shares": 5,
        "cancel_below_signal_by_more_than": 0.01,
        "hold": "settlement",
        "fee_rate": 0.07,
        "live_submission": "disabled",
    }


def test_fee_uses_reviewed_polymarket_curve() -> None:
    assert fee_per_share(0.9) == pytest.approx(0.07 * 0.9 * 0.1)


def test_fills_at_frozen_limit_with_sufficient_displayed_depth() -> None:
    result = evaluate_market(signal(0.90, 0.12), arrival(0.90, 0.12), outcome="Up")
    assert result["decision"] == "hypothetical_fok_fill"
    assert result["selected_side"] == "Up"
    assert result["hypothetical_fok_fill"] is True
    assert result["pnl_per_share"] == pytest.approx(1.0 - 0.90 - fee_per_share(0.90))


def test_cancels_when_price_improves_by_more_than_one_cent() -> None:
    result = evaluate_market(signal(0.90, 0.12), arrival(0.88, 0.12), outcome="Up")
    assert result["decision"] == "cancel_adverse_move"
    assert result["hypothetical_fok_fill"] is False


def test_one_cent_improvement_remains_eligible() -> None:
    result = evaluate_market(signal(0.90, 0.12), arrival(0.89, 0.12), outcome="Up")
    assert result["decision"] == "hypothetical_fok_fill"


def test_rejects_arrival_ask_above_frozen_limit() -> None:
    result = evaluate_market(signal(0.90, 0.12), arrival(0.91, 0.12), outcome="Up")
    assert result["decision"] == "no_fill_ask_above_frozen_limit"


def test_rejects_insufficient_displayed_depth() -> None:
    result = evaluate_market(signal(0.90, 0.12), arrival(0.90, 0.12, up_size=4.99), outcome="Up")
    assert result["decision"] == "no_fill_insufficient_displayed_depth"


def test_tied_favorite_fails_closed() -> None:
    result = evaluate_market(signal(0.50, 0.50), arrival(0.50, 0.50), outcome="Up")
    assert result["decision"] == "no_signal_tied_favorite"
    assert result["signal"] is False


def test_signal_below_threshold_is_not_traded() -> None:
    result = evaluate_market(signal(0.84, 0.18), arrival(0.84, 0.18), outcome="Up")
    assert result["decision"] == "no_signal_below_threshold"


def test_loss_pnl_uses_executable_ask_and_fee() -> None:
    result = evaluate_market(signal(0.90, 0.12), arrival(0.90, 0.12), outcome="Down")
    assert result["won"] is False
    assert result["pnl_per_share"] == pytest.approx(-0.90 - fee_per_share(0.90))
    assert math.isclose(result["pnl_at_five_shares"], result["pnl_per_share"] * 5)
