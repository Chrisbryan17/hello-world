from __future__ import annotations

from dataclasses import dataclass

from .variants import VariantSpec


@dataclass(frozen=True, slots=True)
class CollapseBudget:
    deployed_height_mm: float
    bundle_count: int
    collapsed_unit_height_mm: float
    inter_unit_clearance_mm: float
    top_bottom_allowance_mm: float
    bundle_height_mm: float
    margin_mm: float

    @property
    def fits(self) -> bool:
        return self.margin_mm >= 0.0


def calculate_collapse_budget(
    spec: VariantSpec,
    collapsed_unit_height_mm: float,
    inter_unit_clearance_mm: float,
    top_bottom_allowance_mm: float,
) -> CollapseBudget:
    values = (
        collapsed_unit_height_mm,
        inter_unit_clearance_mm,
        top_bottom_allowance_mm,
    )
    if any(value < 0 for value in values):
        raise ValueError("Collapse-budget dimensions must be non-negative.")
    bundle_height_mm = (
        spec.bundle_count * collapsed_unit_height_mm
        + (spec.bundle_count - 1) * inter_unit_clearance_mm
        + top_bottom_allowance_mm
    )
    return CollapseBudget(
        deployed_height_mm=float(spec.external_height_mm),
        bundle_count=spec.bundle_count,
        collapsed_unit_height_mm=collapsed_unit_height_mm,
        inter_unit_clearance_mm=inter_unit_clearance_mm,
        top_bottom_allowance_mm=top_bottom_allowance_mm,
        bundle_height_mm=bundle_height_mm,
        margin_mm=float(spec.external_height_mm) - bundle_height_mm,
    )
