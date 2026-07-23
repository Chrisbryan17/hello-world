import pytest

from jcc.geometry import calculate_collapse_budget
from jcc.variants import VariantId, get_variant


def test_four_units_fit_when_budget_is_positive() -> None:
    budget = calculate_collapse_budget(
        get_variant(VariantId.CONTAINER_20_STD),
        collapsed_unit_height_mm=610.0,
        inter_unit_clearance_mm=20.0,
        top_bottom_allowance_mm=70.0,
    )
    assert budget.bundle_height_mm == pytest.approx(2570.0)
    assert budget.margin_mm == pytest.approx(21.0)
    assert budget.fits is True


def test_bundle_is_rejected_when_height_exceeds_envelope() -> None:
    budget = calculate_collapse_budget(
        get_variant(VariantId.CONTAINER_40_HC),
        collapsed_unit_height_mm=700.0,
        inter_unit_clearance_mm=25.0,
        top_bottom_allowance_mm=40.0,
    )
    assert budget.fits is False
    assert budget.margin_mm < 0


def test_invalid_clearances_are_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        calculate_collapse_budget(get_variant("20std"), 600.0, -1.0, 50.0)
