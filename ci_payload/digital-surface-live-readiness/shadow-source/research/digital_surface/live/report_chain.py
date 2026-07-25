from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .report import ShadowCanaryMetrics, evaluate_shadow_admission


class ShadowReportIntegrityError(RuntimeError):
    """Raised when an append-only shadow report ledger has been altered."""


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(name: str, value: str) -> str:
    text = str(value).lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError(f"{name} must be a 64-character SHA-256 hex digest")
    return text


class ShadowReportLedger:
    """Append-only reports bound to immutable policy, source, and market-ledger state."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.head_hash = "0" * 64
        self.rows: list[dict[str, Any]] = []
        if self.path.exists():
            self._load_and_verify()

    def _load_and_verify(self) -> None:
        previous = "0" * 64
        rows: list[dict[str, Any]] = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ShadowReportIntegrityError(f"invalid JSON at line {line_number}") from exc
            stored = str(record.get("report_hash", ""))
            payload = dict(record)
            payload.pop("report_hash", None)
            if payload.get("previous_report_hash") != previous:
                raise ShadowReportIntegrityError(f"report chain mismatch at line {line_number}")
            for field in ("policy_sha256", "source_sha256", "prospective_head_sha256"):
                try:
                    _sha256(field, str(payload.get(field, "")))
                except ValueError as exc:
                    raise ShadowReportIntegrityError(f"invalid {field} at line {line_number}") from exc
            expected = hashlib.sha256(_canonical_json(payload)).hexdigest()
            if stored != expected:
                raise ShadowReportIntegrityError(f"report hash mismatch at line {line_number}")
            metrics = ShadowCanaryMetrics(**payload["metrics"])
            expected_decision = evaluate_shadow_admission(metrics)
            if payload.get("decision") != expected_decision:
                raise ShadowReportIntegrityError(f"decision mismatch at line {line_number}")
            rows.append(record)
            previous = stored
        self.rows = rows
        self.head_hash = previous

    def append(
        self,
        *,
        generated_ts_ms: int,
        metrics: ShadowCanaryMetrics,
        policy_sha256: str,
        source_sha256: str,
        prospective_head_sha256: str,
    ) -> dict[str, Any]:
        timestamp = int(generated_ts_ms)
        if timestamp < 0:
            raise ValueError("generated_ts_ms must be non-negative")
        policy = _sha256("policy_sha256", policy_sha256)
        source = _sha256("source_sha256", source_sha256)
        prospective = _sha256("prospective_head_sha256", prospective_head_sha256)
        payload = {
            "decision": evaluate_shadow_admission(metrics),
            "generated_ts_ms": timestamp,
            "metrics": asdict(metrics),
            "policy_sha256": policy,
            "previous_report_hash": self.head_hash,
            "prospective_head_sha256": prospective,
            "source_sha256": source,
        }
        report_hash = hashlib.sha256(_canonical_json(payload)).hexdigest()
        record = {**payload, "report_hash": report_hash}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
        self.rows.append(record)
        self.head_hash = report_hash
        return dict(record)
