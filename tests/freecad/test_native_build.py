from pathlib import Path

import pytest

from jcc.freecad_adapter import build_scaffold_document, freecad_available
from jcc.kinematics import MechanismParameters, sample_fold_state
from jcc.variants import get_variant


pytestmark = pytest.mark.skipif(
    not freecad_available(), reason="FreeCAD Python modules are not installed"
)


def test_native_scaffold_builds_and_saves(tmp_path: Path) -> None:
    mechanism = MechanismParameters(180.0, 160.0, 12.0, 610.0)
    spec = get_variant("20std")
    state = sample_fold_state(spec, mechanism, 0.0)
    output = build_scaffold_document(
        spec, mechanism, state, tmp_path / "container_20std_deployed.FCStd"
    )
    assert output.exists()
    assert output.stat().st_size > 0
