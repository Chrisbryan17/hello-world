# Jamaica-First Collapsible Freight Container — CI Mirror

Public execution mirror for the certification-oriented, Jamaica-manufacturable collapsible freight-container engineering project maintained on the `jamaica-collapsible-container` branch of `Chrisbryan17/Webots`.

## Required variants

| ID | Variant | Nominal external envelope | Maximum gross mass |
|---|---|---:|---:|
| `20std` | 20 ft standard | 6058 × 2438 × 2591 mm | 30,480 kg |
| `40std` | 40 ft standard | 12192 × 2438 × 2591 mm | 30,480 kg |
| `40hc` | 40 ft high cube | 12192 × 2438 × 2896 mm | 30,480 kg |

The dimensions remain `nominal_unverified`; the software blocks certification release until licensed standards data is entered into the controlled register. This phase produces deterministic geometry manifests and native FreeCAD major-body scaffolds. It does not claim structural adequacy or certification.

## Approved mechanism baseline

- rigid underframe;
- vertically lowering roof;
- inward-folding long walls;
- one conventional double-door end and one solid end;
- one forklift and two trained operators;
- no onboard actuation;
- four collapsed units per deployed-height envelope;
- no generative-image assets.

## Local regression

```bash
python -m pip install -e ".[test]"
python -m pytest -q
python scripts/build_variants.py --output-dir build/manifests --samples 21
```

## Native FreeCAD build

GitHub Actions downloads a checksum-pinned FreeCAD 1.1.1 AppImage, generates nine `.FCStd` documents—three fold states for each variant—validates their archive structure, and publishes the files as a workflow artifact.
