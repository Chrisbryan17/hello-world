#!/usr/bin/env python3
"""Verify a v0.8 extracted release tree against MANIFEST.sha256."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path, PurePosixPath

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_manifest(manifest: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line_number, raw_line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            digest, relative = raw_line.split("  ", 1)
        except ValueError as exc:
            raise ValueError(f"Malformed manifest line {line_number}: {raw_line!r}") from exc
        relative = relative.removeprefix("./")
        pure = PurePosixPath(relative)
        if not SHA256_RE.fullmatch(digest):
            raise ValueError(f"Invalid SHA-256 on line {line_number}: {digest!r}")
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise ValueError(f"Unsafe path on line {line_number}: {relative!r}")
        normalized = pure.as_posix()
        if normalized == "MANIFEST.sha256":
            raise ValueError("MANIFEST.sha256 must not list itself")
        if normalized in entries:
            raise ValueError(f"Duplicate manifest path: {normalized}")
        entries[normalized] = digest
    if not entries:
        raise ValueError("Manifest contains no entries")
    return entries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".", help="Extracted package root")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    manifest = root / "MANIFEST.sha256"
    if not root.is_dir():
        print(f"ERROR: package root is not a directory: {root}", file=sys.stderr)
        return 2
    if not manifest.is_file():
        print(f"ERROR: missing manifest: {manifest}", file=sys.stderr)
        return 2

    try:
        expected = parse_manifest(manifest)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != manifest
    }
    expected_paths = set(expected)

    missing = sorted(expected_paths - actual)
    unexpected = sorted(actual - expected_paths)
    mismatched: list[tuple[str, str, str]] = []

    for relative in sorted(expected_paths & actual):
        observed = sha256_file(root / relative)
        wanted = expected[relative]
        if observed != wanted:
            mismatched.append((relative, wanted, observed))

    if missing or unexpected or mismatched:
        for relative in missing:
            print(f"MISSING: {relative}", file=sys.stderr)
        for relative in unexpected:
            print(f"UNEXPECTED: {relative}", file=sys.stderr)
        for relative, wanted, observed in mismatched:
            print(
                f"HASH_MISMATCH: {relative}\n  expected {wanted}\n  observed {observed}",
                file=sys.stderr,
            )
        return 1

    print(f"ARCHIVE_CONTENT_VERIFICATION=PASS files={len(expected_paths)} root={root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
