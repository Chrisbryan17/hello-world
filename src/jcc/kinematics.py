from __future__ import annotations

from dataclasses import dataclass

from .variants import VariantSpec


@dataclass(frozen=True, slots=True)
class MechanismParameters:
    underframe_height_mm: float
    roof_depth_mm: float
    wall_leaf_clearance_mm: float
    target_collapsed_height_mm: float

    def __post_init__(self) -> None:
        if min(
            self.underframe_height_mm,
            self.roof_depth_mm,
            self.wall_leaf_clearance_mm,
            self.target_collapsed_height_mm,
        ) <= 0:
            raise ValueError("Mechanism dimensions must be positive.")


@dataclass(frozen=True, slots=True)
class FoldState:
    progress: float
    roof_elevation_mm: float
    overall_height_mm: float
    wall_fold_angle_deg: float
    nominal_side_clearance_mm: float


def sample_fold_state(
    spec: VariantSpec,
    mechanism: MechanismParameters,
    progress: float,
) -> FoldState:
    if not 0.0 <= progress <= 1.0:
        raise ValueError("Fold progress must be between 0 and 1 inclusive.")
    overall_height = (
        spec.external_height_mm
        + progress * (mechanism.target_collapsed_height_mm - spec.external_height_mm)
    )
    return FoldState(
        progress=progress,
        roof_elevation_mm=overall_height,
        overall_height_mm=overall_height,
        wall_fold_angle_deg=180.0 * progress,
        nominal_side_clearance_mm=mechanism.wall_leaf_clearance_mm,
    )


def sample_fold_cycle(
    spec: VariantSpec,
    mechanism: MechanismParameters,
    samples: int = 21,
) -> tuple[FoldState, ...]:
    if samples < 2:
        raise ValueError("At least two fold samples are required.")
    return tuple(
        sample_fold_state(spec, mechanism, index / (samples - 1))
        for index in range(samples)
    )
