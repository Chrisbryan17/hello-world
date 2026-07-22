#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
OUT_DIR="${1:-${REPO_ROOT}/dist/v0.8}"
HEAD_SHA="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
SHORT_SHA="${HEAD_SHA:0:12}"
PACKAGE_NAME="erdos-gyarfas-equality-v0.8-${SHORT_SHA}"
SOURCE_EPOCH="$(git -C "${REPO_ROOT}" show -s --format=%ct HEAD)"
STAGE_ROOT="$(mktemp -d)"
VERIFY_ROOT="$(mktemp -d)"
PACKAGE_ROOT="${STAGE_ROOT}/${PACKAGE_NAME}"
ZIP_PATH="${OUT_DIR}/${PACKAGE_NAME}.zip"
CHECKSUM_PATH="${ZIP_PATH}.sha256"
REPORT_PATH="${OUT_DIR}/${PACKAGE_NAME}.verification.txt"

cleanup() {
  rm -rf "${STAGE_ROOT}" "${VERIFY_ROOT}"
}
trap cleanup EXIT

mkdir -p "${OUT_DIR}" "${PACKAGE_ROOT}/CI"

# Stage only tracked files from the exact commit. This deliberately excludes
# .lake caches, compiler outputs, and all untracked workspace state.
git -C "${REPO_ROOT}" archive --format=tar HEAD \
  lean-bridge \
  .github/workflows/lean-equality-case.yml \
  .github/workflows/lean-simplegraph-bridge.yml \
  release/v0.8 \
  | tar -xf - -C "${PACKAGE_ROOT}"

export PACKAGE_ROOT HEAD_SHA SOURCE_EPOCH
python3 - <<'PY'
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

root = Path(os.environ["PACKAGE_ROOT"])
head = os.environ["HEAD_SHA"]
lakefile = (root / "lean-bridge/lakefile.lean").read_text(encoding="utf-8")
toolchain = (root / "lean-bridge/lean-toolchain").read_text(encoding="utf-8").strip()
mathlib_match = re.search(r'mathlib4\.git"\s*@\s*"([^"]+)"', lakefile)
version_match = re.search(r'version\s*:=\s*v!"([^"]+)"', lakefile)
metadata = {
    "package": "erdos-gyarfas-equality-case",
    "release_version": version_match.group(1) if version_match else "0.8.0",
    "repository": os.environ.get("GITHUB_REPOSITORY", "Chrisbryan17/hello-world"),
    "source_commit": head,
    "source_commit_short": head[:12],
    "source_branch": os.environ.get("GITHUB_REF_NAME", "detached-or-local"),
    "source_event": os.environ.get("GITHUB_EVENT_NAME", "local"),
    "source_date_epoch": int(os.environ["SOURCE_EPOCH"]),
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "lean_toolchain": toolchain,
    "mathlib_ref": mathlib_match.group(1) if mathlib_match else None,
}
(root / "SOURCE_METADATA.json").write_text(
    json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)

gates = [
    "reject source placeholders: sorry/admit",
    "install pinned Lean toolchain",
    "resolve Lake dependencies",
    "fetch mathlib build cache",
    "full lake build",
    "compile BridgeTest.lean",
    "compile EqualityTest.lean",
    "print audited theorem axioms",
    "reject sorryAx dependencies",
]
evidence = {
    "workflow": os.environ.get("GITHUB_WORKFLOW", "local release build"),
    "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
    "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    "workflow_run_url": (
        f"https://github.com/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/"
        f"{os.environ.get('GITHUB_RUN_ID')}"
        if os.environ.get("GITHUB_REPOSITORY") and os.environ.get("GITHUB_RUN_ID")
        else None
    ),
    "verification_job_result": os.environ.get("VERIFICATION_JOB_RESULT", "local-not-attested"),
    "source_commit": head,
    "gates_completed_before_packaging": gates,
    "attestation_basis": (
        "The package job depends on the verification job and runs only after that job succeeds."
        if os.environ.get("VERIFICATION_JOB_RESULT") == "success"
        else "Local package build; consult the referenced CI run for formal verification evidence."
    ),
}
(root / "CI/CI_EVIDENCE.json").write_text(
    json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
PY

if command -v gh >/dev/null 2>&1 && [[ -n "${GH_TOKEN:-}" ]]; then
  gh pr view 35 --repo "${GITHUB_REPOSITORY:-Chrisbryan17/hello-world}" \
    --json number,state,isDraft,headRefName,headRefOid,baseRefName,baseRefOid,title,url,mergedAt \
    > "${PACKAGE_ROOT}/CI/PR_SNAPSHOT.json"
else
  printf '%s\n' '{"available":false,"reason":"GitHub CLI authentication was not available during packaging"}' \
    > "${PACKAGE_ROOT}/CI/PR_SNAPSHOT.json"
fi

(
  cd "${PACKAGE_ROOT}"
  find . -type f ! -name MANIFEST.sha256 -print0 \
    | LC_ALL=C sort -z \
    | xargs -0 sha256sum \
    > MANIFEST.sha256
)

rm -f "${ZIP_PATH}" "${CHECKSUM_PATH}" "${REPORT_PATH}"
export STAGE_ROOT PACKAGE_NAME ZIP_PATH
python3 - <<'PY'
from __future__ import annotations

import os
import zipfile
from pathlib import Path

stage = Path(os.environ["STAGE_ROOT"])
package_name = os.environ["PACKAGE_NAME"]
source = stage / package_name
zip_path = Path(os.environ["ZIP_PATH"])
zip_path.parent.mkdir(parents=True, exist_ok=True)

# Fixed ZIP timestamps and sorted paths make repeated builds from identical
# package bytes deterministic.
fixed_time = (1980, 1, 1, 0, 0, 0)
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        relative = Path(package_name) / path.relative_to(source)
        info = zipfile.ZipInfo(relative.as_posix(), fixed_time)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (0o100644 & 0xFFFF) << 16
        archive.writestr(info, path.read_bytes())
PY

python3 - "${ZIP_PATH}" "${VERIFY_ROOT}" <<'PY'
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

archive = Path(sys.argv[1])
destination = Path(sys.argv[2])
with zipfile.ZipFile(archive) as zf:
    bad = zf.testzip()
    if bad is not None:
        raise SystemExit(f"ZIP CRC verification failed at {bad}")
    for member in zf.infolist():
        target = (destination / member.filename).resolve()
        if destination.resolve() not in target.parents and target != destination.resolve():
            raise SystemExit(f"Unsafe ZIP member: {member.filename}")
    zf.extractall(destination)
PY

python3 "${VERIFY_ROOT}/${PACKAGE_NAME}/release/v0.8/verify_archive.py" \
  "${VERIFY_ROOT}/${PACKAGE_NAME}"

ARCHIVE_SHA="$(sha256sum "${ZIP_PATH}" | awk '{print $1}')"
printf '%s  %s\n' "${ARCHIVE_SHA}" "$(basename "${ZIP_PATH}")" > "${CHECKSUM_PATH}"
FILE_COUNT="$(wc -l < "${PACKAGE_ROOT}/MANIFEST.sha256" | tr -d ' ')"
cat > "${REPORT_PATH}" <<EOF
ARCHIVE_VERIFICATION=PASS
package=${PACKAGE_NAME}
source_commit=${HEAD_SHA}
archive=$(basename "${ZIP_PATH}")
archive_sha256=${ARCHIVE_SHA}
manifest_file_count=${FILE_COUNT}
verification_method=clean extraction + ZIP CRC test + safe-path test + exact file-set comparison + SHA-256 manifest verification
EOF

printf 'RELEASE_BUILD=PASS\n'
printf 'ZIP=%s\n' "${ZIP_PATH}"
printf 'SHA256=%s\n' "${ARCHIVE_SHA}"
printf 'REPORT=%s\n' "${REPORT_PATH}"
