from __future__ import annotations

import pytest

from official_transfer import (
    parse_clob_terminal,
    parse_gamma_terminal,
    reconcile_terminal_sources,
)


CONDITION = "0x" + "ab" * 32


def gamma_payload(**overrides):
    payload = {
        "conditionId": CONDITION,
        "closed": True,
        "umaResolutionStatus": "resolved",
        "outcomes": '["Up", "Down"]',
        "outcomePrices": '["1", "0"]',
    }
    payload.update(overrides)
    return payload


def clob_payload(**overrides):
    payload = {
        "condition_id": CONDITION,
        "closed": True,
        "tokens": [
            {"outcome": "Up", "price": 1, "winner": True},
            {"outcome": "Down", "price": 0, "winner": False},
        ],
    }
    payload.update(overrides)
    return payload


def test_gamma_accepts_json_string_arrays_and_one_hot_terminal_prices() -> None:
    result = parse_gamma_terminal(gamma_payload(), expected_condition_id=CONDITION)
    assert result["classification"] == "terminal"
    assert result["official_outcome"] == "Up"
    assert result["closed"] is True
    assert result["uma_resolution_status"] == "resolved"


def test_gamma_accepts_native_arrays() -> None:
    result = parse_gamma_terminal(
        gamma_payload(outcomes=["Up", "Down"], outcomePrices=[0, 1]),
        expected_condition_id=CONDITION,
    )
    assert result["classification"] == "terminal"
    assert result["official_outcome"] == "Down"


def test_gamma_fails_closed_on_condition_id_mismatch() -> None:
    result = parse_gamma_terminal(gamma_payload(conditionId="0x" + "cd" * 32), expected_condition_id=CONDITION)
    assert result["classification"] == "mismatched_condition_id"
    assert result["official_outcome"] is None


def test_gamma_fails_closed_when_market_is_not_closed() -> None:
    result = parse_gamma_terminal(gamma_payload(closed=False), expected_condition_id=CONDITION)
    assert result["classification"] == "not_closed"


def test_gamma_rejects_non_one_hot_prices() -> None:
    result = parse_gamma_terminal(
        gamma_payload(outcomePrices='["0.999", "0.001"]'),
        expected_condition_id=CONDITION,
    )
    assert result["classification"] == "ambiguous_terminal_prices"
    assert result["official_outcome"] is None


def test_gamma_rejects_malformed_array_encoding() -> None:
    result = parse_gamma_terminal(gamma_payload(outcomes="not-json"), expected_condition_id=CONDITION)
    assert result["classification"] == "malformed_gamma_payload"


def test_gamma_rejects_duplicate_outcome_labels() -> None:
    result = parse_gamma_terminal(
        gamma_payload(outcomes='["Up", "Up"]'),
        expected_condition_id=CONDITION,
    )
    assert result["classification"] == "malformed_gamma_payload"


def test_clob_requires_exactly_one_winner() -> None:
    result = parse_clob_terminal(clob_payload(), expected_condition_id=CONDITION)
    assert result["classification"] == "terminal"
    assert result["official_outcome"] == "Up"


def test_clob_rejects_multiple_winners() -> None:
    result = parse_clob_terminal(
        clob_payload(
            tokens=[
                {"outcome": "Up", "winner": True},
                {"outcome": "Down", "winner": True},
            ]
        ),
        expected_condition_id=CONDITION,
    )
    assert result["classification"] == "ambiguous_winner_flags"


def test_clob_fails_closed_on_condition_id_mismatch() -> None:
    result = parse_clob_terminal(
        clob_payload(condition_id="0x" + "ef" * 32),
        expected_condition_id=CONDITION,
    )
    assert result["classification"] == "mismatched_condition_id"


def test_reconciliation_confirms_matching_terminal_sources() -> None:
    result = reconcile_terminal_sources(
        parse_gamma_terminal(gamma_payload(), expected_condition_id=CONDITION),
        parse_clob_terminal(clob_payload(), expected_condition_id=CONDITION),
    )
    assert result["classification"] == "terminal_confirmed_both"
    assert result["official_outcome"] == "Up"


def test_reconciliation_marks_source_disagreement() -> None:
    result = reconcile_terminal_sources(
        parse_gamma_terminal(gamma_payload(), expected_condition_id=CONDITION),
        parse_clob_terminal(
            clob_payload(
                tokens=[
                    {"outcome": "Up", "winner": False},
                    {"outcome": "Down", "winner": True},
                ]
            ),
            expected_condition_id=CONDITION,
        ),
    )
    assert result["classification"] == "source_disagreement"
    assert result["official_outcome"] is None


def test_reconciliation_allows_gamma_terminal_when_clob_is_unavailable() -> None:
    result = reconcile_terminal_sources(
        parse_gamma_terminal(gamma_payload(), expected_condition_id=CONDITION),
        {"classification": "unavailable", "official_outcome": None},
    )
    assert result["classification"] == "terminal_gamma_only"
    assert result["official_outcome"] == "Up"


def test_reconciliation_never_promotes_clob_only_to_primary_official_label() -> None:
    result = reconcile_terminal_sources(
        {"classification": "unavailable", "official_outcome": None},
        parse_clob_terminal(clob_payload(), expected_condition_id=CONDITION),
    )
    assert result["classification"] == "clob_only_unconfirmed"
    assert result["official_outcome"] is None
