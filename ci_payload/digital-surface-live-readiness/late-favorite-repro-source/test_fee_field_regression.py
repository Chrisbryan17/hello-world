from __future__ import annotations

import pytest

from late_favorite_transfer import evaluate_market, fee_per_share


def test_unlabeled_hypothetical_fill_still_records_execution_fee() -> None:
    result = evaluate_market(
        {"au": 0.90, "ad": 0.12},
        {"au": 0.90, "ad": 0.12, "sau": 5.0, "sad": 5.0},
        outcome=None,
    )

    assert result["decision"] == "hypothetical_fok_fill"
    assert result["hypothetical_fok_fill"] is True
    assert result["fee_per_share"] == pytest.approx(fee_per_share(0.90))
    assert result["won"] is None
    assert result["pnl_per_share"] is None
    assert result["pnl_at_five_shares"] is None
