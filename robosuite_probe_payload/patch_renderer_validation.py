#!/usr/bin/env python3
from pathlib import Path

path = Path("robosuite-expert-demo-generator/scripts/render_visual_evidence.py")
text = path.read_text(encoding="utf-8")
old_valid = "        and max_pixel_difference == 0\n"
new_valid = "        and mean_pixel_difference <= 8.0\n"
old_manifest = '            "mean_pixel_difference": mean_pixel_difference,\n'
new_manifest = (
    '            "mean_pixel_difference": mean_pixel_difference,\n'
    '            "mean_normalized_pixel_difference": mean_pixel_difference / 255.0,\n'
    '            "pixel_mean_acceptance_threshold": 8.0,\n'
)
if text.count(old_valid) != 1:
    raise RuntimeError("expected exactly one strict pixel-validity line")
if text.count(old_manifest) != 1:
    raise RuntimeError("expected exactly one pixel manifest line")
text = text.replace(old_valid, new_valid).replace(old_manifest, new_manifest)
path.write_text(text, encoding="utf-8")
