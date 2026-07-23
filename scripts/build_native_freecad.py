from __future__ import annotations

import os
from pathlib import Path

from jcc.native_build import build_native_family


def main() -> int:
    output_dir = Path(os.environ.get("JCC_FREECAD_OUTPUT", "build/freecad"))
    samples = int(os.environ.get("JCC_FREECAD_SAMPLES", "3"))
    outputs = build_native_family(output_dir=output_dir, samples=samples)
    print(f"generated {len(outputs)} native FreeCAD documents")
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
