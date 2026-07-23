from __future__ import annotations

from pathlib import Path
from typing import Any

from .kinematics import FoldState, MechanismParameters
from .variants import VariantSpec


class FreeCADUnavailable(RuntimeError):
    """Raised when native FreeCAD modules are not available in the interpreter."""


def _modules() -> tuple[Any, Any]:
    try:
        import FreeCAD as App  # type: ignore[import-not-found]
        import Part  # type: ignore[import-not-found]
    except ImportError as exc:
        raise FreeCADUnavailable(
            "FreeCAD Python modules are unavailable; run with FreeCADCmd or install FreeCAD."
        ) from exc
    return App, Part


def freecad_available() -> bool:
    try:
        _modules()
    except FreeCADUnavailable:
        return False
    return True


def build_scaffold_document(
    spec: VariantSpec,
    mechanism: MechanismParameters,
    state: FoldState,
    output_path: str | Path,
) -> Path:
    """Build the native major-body scaffold for one variant and fold state."""
    App, Part = _modules()
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    document = App.newDocument(f"JCC_{spec.variant_id}_{state.progress:.3f}")

    underframe = document.addObject("Part::Feature", "Underframe")
    underframe.Label = "Rigid underframe scaffold"
    underframe.Shape = Part.makeBox(
        spec.external_length_mm,
        spec.external_width_mm,
        mechanism.underframe_height_mm,
    )

    roof = document.addObject("Part::Feature", "Roof")
    roof.Label = "Vertically guided roof scaffold"
    roof.Shape = Part.makeBox(
        spec.external_length_mm,
        spec.external_width_mm,
        mechanism.roof_depth_mm,
        App.Vector(0, 0, state.roof_elevation_mm - mechanism.roof_depth_mm),
    )

    wall_thickness = 40.0
    wall_height = max(
        1.0,
        state.overall_height_mm
        - mechanism.underframe_height_mm
        - mechanism.roof_depth_mm,
    )
    for name, y in (
        ("LeftWall", 0.0),
        ("RightWall", spec.external_width_mm - wall_thickness),
    ):
        wall = document.addObject("Part::Feature", name)
        wall.Label = f"{name} articulated-envelope scaffold"
        wall.Shape = Part.makeBox(
            spec.external_length_mm,
            wall_thickness,
            wall_height,
            App.Vector(0, y, mechanism.underframe_height_mm),
        )

    end_thickness = 60.0
    for name, x in (
        ("DoorEnd", 0.0),
        ("SolidEnd", spec.external_length_mm - end_thickness),
    ):
        end = document.addObject("Part::Feature", name)
        end.Label = f"{name} structural-frame scaffold"
        end.Shape = Part.makeBox(
            end_thickness,
            spec.external_width_mm,
            wall_height,
            App.Vector(x, 0, mechanism.underframe_height_mm),
        )

    document.recompute()
    document.saveAs(str(output))
    App.closeDocument(document.Name)
    return output
