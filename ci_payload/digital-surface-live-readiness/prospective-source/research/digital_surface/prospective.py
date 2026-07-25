from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


class ProspectiveContaminationError(RuntimeError):
    pass


class ProspectiveIntegrityError(RuntimeError):
    pass


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _validate_sha256(name: str, value: str) -> str:
    text = str(value).lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError(f"{name} must be a 64-character SHA-256 hex digest")
    return text


class ProspectiveLedger:
    def __init__(self, path: str | Path, *, diagnostic_market_ids: Iterable[str]) -> None:
        self.path = Path(path)
        self.diagnostic_market_ids = {str(value) for value in diagnostic_market_ids}
        self._rows: list[dict[str, Any]] = []
        self.market_ids: set[str] = set()
        self.head_hash = "0" * 64
        if self.path.exists():
            self._load_and_verify()

    def _load_and_verify(self) -> None:
        previous = "0" * 64
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProspectiveIntegrityError(f"invalid JSON at line {line_number}") from exc
            stored_hash = str(row.get("record_hash", ""))
            payload = dict(row)
            payload.pop("record_hash", None)
            if payload.get("previous_hash") != previous:
                raise ProspectiveIntegrityError(f"hash chain mismatch at line {line_number}")
            expected = hashlib.sha256(_canonical_json(payload)).hexdigest()
            if stored_hash != expected:
                raise ProspectiveIntegrityError(f"record hash mismatch at line {line_number}")
            market_id = str(payload.get("market_id", ""))
            if not market_id or market_id in seen:
                raise ProspectiveIntegrityError(f"duplicate or empty market_id at line {line_number}")
            _validate_sha256("policy_sha256", str(payload.get("policy_sha256", "")))
            _validate_sha256("source_sha256", str(payload.get("source_sha256", "")))
            seen.add(market_id)
            rows.append(row)
            previous = stored_hash
        self._rows = rows
        self.market_ids = seen
        self.head_hash = previous

    def append_observation(
        self,
        *,
        market_id: str,
        first_seen_ts_ms: int,
        policy_sha256: str,
        source_sha256: str,
    ) -> dict[str, Any]:
        market = str(market_id)
        if not market:
            raise ValueError("market_id must be non-empty")
        if market in self.diagnostic_market_ids:
            raise ProspectiveContaminationError(f"market {market!r} appeared in diagnostic data")
        if market in self.market_ids:
            raise ProspectiveContaminationError(f"market {market!r} was already observed")
        policy = _validate_sha256("policy_sha256", policy_sha256)
        source = _validate_sha256("source_sha256", source_sha256)
        timestamp = int(first_seen_ts_ms)
        if timestamp < 0:
            raise ValueError("first_seen_ts_ms must be non-negative")
        payload = {
            "first_seen_ts_ms": timestamp,
            "market_id": market,
            "policy_sha256": policy,
            "previous_hash": self.head_hash,
            "source_sha256": source,
            "state": "observed",
        }
        record = {**payload, "record_hash": hashlib.sha256(_canonical_json(payload)).hexdigest()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
        self._rows.append(record)
        self.market_ids.add(market)
        self.head_hash = record["record_hash"]
        return dict(record)
