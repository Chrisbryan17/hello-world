from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .public_books import PublicOrderBook


class BookLedgerIntegrityError(RuntimeError):
    pass


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(name: str, value: str) -> str:
    text = str(value).lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError(f"{name} must be a 64-character SHA-256 hex digest")
    return text


class PublicBookLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.rows: list[dict[str, Any]] = []
        self.head_hash = "0" * 64
        self.observation_ids: set[str] = set()
        if self.path.exists():
            self._load_and_verify()

    def _load_and_verify(self) -> None:
        previous = "0" * 64
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BookLedgerIntegrityError(f"invalid JSON at line {line_number}") from exc
            stored = str(record.get("record_hash", ""))
            payload = dict(record)
            payload.pop("record_hash", None)
            if payload.get("previous_hash") != previous:
                raise BookLedgerIntegrityError(f"book chain mismatch at line {line_number}")
            expected = hashlib.sha256(_canonical_json(payload)).hexdigest()
            if stored != expected:
                raise BookLedgerIntegrityError(f"book record hash mismatch at line {line_number}")
            observation_id = str(payload.get("observation_id") or "")
            if not observation_id or observation_id in seen:
                raise BookLedgerIntegrityError(f"duplicate or empty observation_id at line {line_number}")
            for field in ("policy_sha256", "source_sha256", "prospective_head_sha256"):
                try:
                    _sha256(field, str(payload.get(field, "")))
                except ValueError as exc:
                    raise BookLedgerIntegrityError(f"invalid {field} at line {line_number}") from exc
            book = payload.get("book")
            if not isinstance(book, dict):
                raise BookLedgerIntegrityError(f"missing book payload at line {line_number}")
            payload_sha = str(book.get("payload_sha256") or "")
            _sha256("payload_sha256", payload_sha)
            rows.append(record)
            seen.add(observation_id)
            previous = stored
        self.rows = rows
        self.observation_ids = seen
        self.head_hash = previous

    def append(
        self,
        *,
        condition_id: str,
        outcome: str,
        observed_ts_ms: int,
        book: PublicOrderBook,
        policy_sha256: str,
        source_sha256: str,
        prospective_head_sha256: str,
    ) -> dict[str, Any]:
        timestamp = int(observed_ts_ms)
        if timestamp < 0:
            raise ValueError("observed_ts_ms must be non-negative")
        side = str(outcome).lower()
        if side not in {"yes", "no"}:
            raise ValueError("outcome must be yes or no")
        condition = str(condition_id)
        if book.condition_id != condition:
            raise ValueError(f"book condition mismatch: {book.condition_id} != {condition}")
        observation_id = hashlib.sha256(
            f"{condition}\0{book.token_id}\0{timestamp}\0{book.payload_sha256}".encode()
        ).hexdigest()
        if observation_id in self.observation_ids:
            raise ValueError("duplicate book observation")
        payload = {
            "book": book.as_json(),
            "condition_id": condition,
            "observation_id": observation_id,
            "observed_ts_ms": timestamp,
            "outcome": side,
            "policy_sha256": _sha256("policy_sha256", policy_sha256),
            "previous_hash": self.head_hash,
            "prospective_head_sha256": _sha256("prospective_head_sha256", prospective_head_sha256),
            "source_sha256": _sha256("source_sha256", source_sha256),
        }
        record = {**payload, "record_hash": hashlib.sha256(_canonical_json(payload)).hexdigest()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
        self.rows.append(record)
        self.observation_ids.add(observation_id)
        self.head_hash = record["record_hash"]
        return dict(record)
