from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .binance_public import BTCMarketState


class SpotStateIntegrityError(RuntimeError):
    """Raised when the append-only BTC state ledger cannot be verified."""


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(name: str, value: str) -> str:
    text = str(value).lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{name} must be a 64-character SHA-256 hex digest")
    return text


def _verify_state(state: object, *, line_number: int | None = None) -> dict[str, Any]:
    suffix = "" if line_number is None else f" at line {line_number}"
    if not isinstance(state, dict):
        raise SpotStateIntegrityError(f"missing BTC state{suffix}")
    required = {
        "symbol",
        "server_time_ms",
        "observed_ts_ms",
        "spot",
        "vol_30s",
        "vol_120s",
        "strikes",
        "closed_one_second_bars",
        "raw_response_sha256",
    }
    missing = sorted(required - set(state))
    if missing:
        raise SpotStateIntegrityError(f"BTC state missing fields {missing}{suffix}")
    if str(state["symbol"]) != "BTCUSDT":
        raise SpotStateIntegrityError(f"unexpected BTC state symbol{suffix}")
    if int(state["server_time_ms"]) < 0 or int(state["observed_ts_ms"]) < 0:
        raise SpotStateIntegrityError(f"invalid BTC state timestamps{suffix}")
    if int(state["closed_one_second_bars"]) < 121:
        raise SpotStateIntegrityError(f"insufficient closed one-second bars{suffix}")
    if not isinstance(state["strikes"], dict) or not isinstance(state["raw_response_sha256"], dict):
        raise SpotStateIntegrityError(f"invalid BTC state maps{suffix}")
    try:
        for value in state["raw_response_sha256"].values():
            _sha256("raw_response_sha256", str(value))
    except ValueError as exc:
        raise SpotStateIntegrityError(f"invalid raw response hash{suffix}") from exc
    return state


class SpotStateLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.rows: list[dict[str, Any]] = []
        self.observation_ids: set[str] = set()
        self.head_hash = "0" * 64
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
                raise SpotStateIntegrityError(f"invalid JSON at line {line_number}") from exc
            stored_hash = str(record.get("record_hash", ""))
            payload = dict(record)
            payload.pop("record_hash", None)
            if payload.get("previous_hash") != previous:
                raise SpotStateIntegrityError(f"BTC state chain mismatch at line {line_number}")
            expected_record_hash = hashlib.sha256(_canonical_json(payload)).hexdigest()
            if stored_hash != expected_record_hash:
                raise SpotStateIntegrityError(f"record hash mismatch at line {line_number}")
            state = _verify_state(payload.get("state"), line_number=line_number)
            expected_state_hash = hashlib.sha256(_canonical_json(state)).hexdigest()
            if payload.get("state_sha256") != expected_state_hash:
                raise SpotStateIntegrityError(f"state hash mismatch at line {line_number}")
            observation_id = str(payload.get("observation_id") or "")
            expected_observation = hashlib.sha256(
                f"{state['server_time_ms']}\0{state['observed_ts_ms']}\0{expected_state_hash}".encode()
            ).hexdigest()
            if observation_id != expected_observation:
                raise SpotStateIntegrityError(f"observation identity mismatch at line {line_number}")
            if observation_id in seen:
                raise SpotStateIntegrityError(f"duplicate BTC state snapshot at line {line_number}")
            for field in ("policy_sha256", "source_sha256", "prospective_head_sha256"):
                try:
                    _sha256(field, str(payload.get(field, "")))
                except ValueError as exc:
                    raise SpotStateIntegrityError(f"invalid {field} at line {line_number}") from exc
            rows.append(record)
            seen.add(observation_id)
            previous = stored_hash
        self.rows = rows
        self.observation_ids = seen
        self.head_hash = previous

    def append(
        self,
        state: BTCMarketState,
        *,
        policy_sha256: str,
        source_sha256: str,
        prospective_head_sha256: str,
    ) -> dict[str, Any]:
        state_json = state.as_json()
        _verify_state(state_json)
        state_hash = hashlib.sha256(_canonical_json(state_json)).hexdigest()
        observation_id = hashlib.sha256(
            f"{state.server_time_ms}\0{state.observed_ts_ms}\0{state_hash}".encode()
        ).hexdigest()
        if observation_id in self.observation_ids:
            raise ValueError("duplicate BTC state snapshot")
        payload = {
            "observation_id": observation_id,
            "policy_sha256": _sha256("policy_sha256", policy_sha256),
            "previous_hash": self.head_hash,
            "prospective_head_sha256": _sha256("prospective_head_sha256", prospective_head_sha256),
            "source_sha256": _sha256("source_sha256", source_sha256),
            "state": state_json,
            "state_sha256": state_hash,
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
