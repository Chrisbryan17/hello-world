from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from jcc.freecad_adapter import build_scaffold_document, freecad_available
from jcc.kinematics import MechanismParameters, sample_fold_cycle
from jcc.provenance import DataStatus
from jcc.variants import VARIANTS


DEFAULT_MECHANISM = MechanismParameters(180.0, 160.0, 12.0, 610.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=21)
    parser.add_argument("--fcstd", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for spec in VARIANTS.values():
        for index, state in enumerate(
            sample_fold_cycle(spec, DEFAULT_MECHANISM, args.samples)
        ):
            stem = f"{spec.variant_id}_{index:03d}_{state.progress:.3f}"
            payload = {
                "variant": asdict(spec),
                "mechanism": asdict(DEFAULT_MECHANISM),
                "state": asdict(state),
                "dimension_status": DataStatus.NOMINAL_UNVERIFIED,
                "certification_release_allowed": False,
            }
            (args.output_dir / f"{stem}.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
            )
            if args.fcstd:
                if not freecad_available():
                    raise SystemExit(
                        "--fcstd requires FreeCADCmd or FreeCAD Python modules"
                    )
                build_scaffold_document(
                    spec,
                    DEFAULT_MECHANISM,
                    state,
                    args.output_dir / f"{stem}.FCStd",
                )
            count += 1
    print(f"generated {count} manifests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
