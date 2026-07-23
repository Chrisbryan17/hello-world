import pytest

from jcc.kinematics import MechanismParameters, sample_fold_cycle, sample_fold_state
from jcc.variants import get_variant


MECHANISM = MechanismParameters(
    underframe_height_mm=180.0,
    roof_depth_mm=160.0,
    wall_leaf_clearance_mm=12.0,
    target_collapsed_height_mm=610.0,
)


def test_deployed_and_collapsed_end_states_match_targets() -> None:
    spec = get_variant("20std")
    deployed = sample_fold_state(spec, MECHANISM, progress=0.0)
    collapsed = sample_fold_state(spec, MECHANISM, progress=1.0)
    assert deployed.roof_elevation_mm == pytest.approx(spec.external_height_mm)
    assert collapsed.overall_height_mm == pytest.approx(610.0)
    assert deployed.wall_fold_angle_deg == pytest.approx(0.0)
    assert collapsed.wall_fold_angle_deg == pytest.approx(180.0)


def test_roof_motion_is_monotonic_over_cycle() -> None:
    states = sample_fold_cycle(get_variant("40std"), MECHANISM, samples=21)
    elevations = [state.roof_elevation_mm for state in states]
    assert elevations == sorted(elevations, reverse=True)


def test_progress_outside_closed_interval_is_rejected() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        sample_fold_state(get_variant("40hc"), MECHANISM, progress=1.01)
