import json
import subprocess
import sys
from pathlib import Path


def test_cli_emits_manifests_for_all_three_variants(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_variants.py",
            "--output-dir",
            str(tmp_path),
            "--samples",
            "5",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "generated 15 manifests" in completed.stdout
    manifests = sorted(tmp_path.glob("*.json"))
    assert len(manifests) == 15
    payload = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert payload["dimension_status"] == "nominal_unverified"
    assert payload["certification_release_allowed"] is False
