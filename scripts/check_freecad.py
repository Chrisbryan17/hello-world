from __future__ import annotations

from jcc.freecad_adapter import FreeCADUnavailable, _modules


def main() -> int:
    try:
        app, _ = _modules()
    except FreeCADUnavailable as exc:
        print(str(exc))
        return 2
    print(f"FreeCAD {'.'.join(str(part) for part in app.Version())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
