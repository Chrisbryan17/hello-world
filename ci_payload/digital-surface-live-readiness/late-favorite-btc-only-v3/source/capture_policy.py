from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from late_favorite_v3 import (
    FreezeViolation,
    FrozenPolicy,
    LedgerIntegrityError,
    LifecycleError,
    ProspectiveLifecycleLedger,
    evaluate_arrival,
    evaluate_signal,
)


class CaptureWindowError(LifecycleError):
    pass


def _validate_sha256(name: str, value: str) -> str:
    text = str(value).lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{name} must be a 64-character SHA-256 hex digest")
    return text


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True, slots=True)
class CapturePolicy:
    capture_policy_sha256: str
    valid_market_open_after_epoch_seconds: int
    signal_target_offset_ms: int
    arrival_target_offset_ms: int
    max_request_start_lateness_ms: int
    max_request_duration_ms: int
    max_book_age_at_request_completion_ms: int
    max_book_future_skew_ms: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capture_policy_sha256",
            _validate_sha256("capture_policy_sha256", self.capture_policy_sha256),
        )
        for name in (
            "valid_market_open_after_epoch_seconds",
            "signal_target_offset_ms",
            "arrival_target_offset_ms",
            "max_request_start_lateness_ms",
            "max_request_duration_ms",
            "max_book_age_at_request_completion_ms",
            "max_book_future_skew_ms",
        ):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.arrival_target_offset_ms <= self.signal_target_offset_ms:
            raise ValueError("arrival target must be after signal target")
        if self.max_request_duration_ms <= 0:
            raise ValueError("max_request_duration_ms must be positive")


def load_capture_policy(
    capture_policy_path: str | Path,
    capture_manifest_path: str | Path,
) -> CapturePolicy:
    policy_path = Path(capture_policy_path)
    raw = policy_path.read_bytes()
    payload = json.loads(raw)
    manifest = json.loads(Path(capture_manifest_path).read_text(encoding="utf-8"))
    got = hashlib.sha256(raw).hexdigest()
    wanted = _validate_sha256(
        "capture_policy_sha256", str(manifest.get("capture_policy_sha256", ""))
    )
    if got != wanted:
        raise FreezeViolation(f"capture policy SHA-256 mismatch: {got} != {wanted}")
    if payload.get("name") != "late_favorite_btc_only_v3_capture_policy":
        raise FreezeViolation("unexpected capture policy name")
    if payload.get("status") != "frozen_before_prospective_collection":
        raise FreezeViolation("capture policy is not frozen")
    transport = payload.get("transport", {})
    privileged = ("credentials_used", "authenticated_requests", "order_submissions")
    if any(int(transport.get(name, -1)) != 0 for name in privileged):
        raise FreezeViolation("capture policy permits privileged transport")
    freeze_text = str(manifest["valid_market_open_after_utc"])
    freeze_epoch = int(datetime.fromisoformat(freeze_text.replace("Z", "+00:00")).timestamp())
    event_time = payload["event_time"]
    windows = payload["request_windows"]
    freshness = payload["book_freshness"]
    return CapturePolicy(
        capture_policy_sha256=got,
        valid_market_open_after_epoch_seconds=freeze_epoch,
        signal_target_offset_ms=int(event_time["signal_target_offset_ms"]),
        arrival_target_offset_ms=int(event_time["arrival_target_offset_ms"]),
        max_request_start_lateness_ms=int(windows["max_request_start_lateness_ms"]),
        max_request_duration_ms=int(windows["max_request_duration_ms"]),
        max_book_age_at_request_completion_ms=int(
            freshness["max_book_age_at_request_completion_ms"]
        ),
        max_book_future_skew_ms=int(freshness["max_book_future_skew_ms"]),
    )


def _target_ms(
    capture_policy: CapturePolicy,
    market_open_epoch_seconds: int,
    *,
    phase: str,
) -> int:
    opening = int(market_open_epoch_seconds)
    if opening <= capture_policy.valid_market_open_after_epoch_seconds:
        raise FreezeViolation(
            f"market open {opening} is not strictly after capture freeze "
            f"{capture_policy.valid_market_open_after_epoch_seconds}"
        )
    offset = (
        capture_policy.signal_target_offset_ms
        if phase == "signal"
        else capture_policy.arrival_target_offset_ms
    )
    return opening * 1000 + offset


def _transport_evidence(
    capture_policy: CapturePolicy,
    *,
    market_open_epoch_seconds: int,
    phase: str,
    request_started_ts_ms: int,
    request_completed_ts_ms: int,
    response_payload_sha256: str,
) -> tuple[dict[str, Any], str | None]:
    target = _target_ms(capture_policy, market_open_epoch_seconds, phase=phase)
    started = int(request_started_ts_ms)
    completed = int(request_completed_ts_ms)
    response_sha = _validate_sha256("response_payload_sha256", response_payload_sha256)
    if started < target:
        raise CaptureWindowError(
            f"{phase} request started before target: {started} < {target}"
        )
    if completed < started:
        raise CaptureWindowError("request completion precedes request start")
    base = {
        "capture_policy_sha256": capture_policy.capture_policy_sha256,
        "target_ts_ms": target,
        "request_started_ts_ms": started,
        "request_completed_ts_ms": completed,
        "request_duration_ms": completed - started,
        "response_payload_sha256": response_sha,
    }
    if started - target > capture_policy.max_request_start_lateness_ms:
        return base, f"missed_{phase}_window"
    if completed - started > capture_policy.max_request_duration_ms:
        return base, f"{phase}_request_timeout"
    return base, None


def _book_timestamp_decision(
    capture_policy: CapturePolicy,
    books: Sequence[Mapping[str, Any]],
    *,
    request_completed_ts_ms: int,
    phase: str,
) -> tuple[list[int], str | None]:
    timestamps: list[int] = []
    for book in books:
        try:
            timestamp = int(str(book.get("timestamp")))
        except (TypeError, ValueError):
            return [], f"no_{phase}_invalid_book_timestamp"
        timestamps.append(timestamp)
        age = int(request_completed_ts_ms) - timestamp
        if age > capture_policy.max_book_age_at_request_completion_ms:
            return timestamps, f"no_{phase}_stale_book"
        if timestamp - int(request_completed_ts_ms) > capture_policy.max_book_future_skew_ms:
            return timestamps, f"no_{phase}_future_book"
    return timestamps, None


def evaluate_signal_capture(
    policy: FrozenPolicy,
    capture_policy: CapturePolicy,
    *,
    condition_id: str,
    market_open_epoch_seconds: int,
    up_token_id: str,
    down_token_id: str,
    up_book: Mapping[str, Any],
    down_book: Mapping[str, Any],
    request_started_ts_ms: int,
    request_completed_ts_ms: int,
    response_payload_sha256: str,
) -> dict[str, Any]:
    transport, transport_decision = _transport_evidence(
        capture_policy,
        market_open_epoch_seconds=market_open_epoch_seconds,
        phase="signal",
        request_started_ts_ms=request_started_ts_ms,
        request_completed_ts_ms=request_completed_ts_ms,
        response_payload_sha256=response_payload_sha256,
    )
    fail_base = {
        "event_type": "signal",
        "condition_id": str(condition_id),
        "market_open_epoch_seconds": int(market_open_epoch_seconds),
        "observed_ts_ms": transport["target_ts_ms"],
        "policy_sha256": policy.policy_sha256,
        "source_sha256": policy.source_sha256,
        "signal": False,
        "selected_side": None,
        "selected_token_id": None,
        "signal_ask": None,
        **transport,
    }
    if transport_decision is not None:
        return {**fail_base, "decision": transport_decision}
    timestamps, book_decision = _book_timestamp_decision(
        capture_policy,
        [up_book, down_book],
        request_completed_ts_ms=request_completed_ts_ms,
        phase="signal",
    )
    if book_decision is not None:
        return {**fail_base, "decision": book_decision, "book_timestamps_ms": timestamps}
    result = evaluate_signal(
        policy,
        condition_id=condition_id,
        market_open_epoch_seconds=market_open_epoch_seconds,
        up_token_id=up_token_id,
        down_token_id=down_token_id,
        up_book=up_book,
        down_book=down_book,
        observed_ts_ms=transport["target_ts_ms"],
    )
    return {**result, **transport, "book_timestamps_ms": timestamps}


def evaluate_arrival_capture(
    policy: FrozenPolicy,
    capture_policy: CapturePolicy,
    signal_record: Mapping[str, Any],
    selected_book: Mapping[str, Any],
    *,
    request_started_ts_ms: int,
    request_completed_ts_ms: int,
    response_payload_sha256: str,
) -> dict[str, Any]:
    opening = int(signal_record["market_open_epoch_seconds"])
    transport, transport_decision = _transport_evidence(
        capture_policy,
        market_open_epoch_seconds=opening,
        phase="arrival",
        request_started_ts_ms=request_started_ts_ms,
        request_completed_ts_ms=request_completed_ts_ms,
        response_payload_sha256=response_payload_sha256,
    )
    fail_base = {
        "event_type": "arrival",
        "condition_id": str(signal_record["condition_id"]),
        "market_open_epoch_seconds": opening,
        "observed_ts_ms": transport["target_ts_ms"],
        "policy_sha256": policy.policy_sha256,
        "source_sha256": policy.source_sha256,
        "selected_side": signal_record.get("selected_side"),
        "selected_token_id": signal_record.get("selected_token_id"),
        "signal_ask": signal_record.get("signal_ask"),
        "hypothetical_fok_fill": False,
        "filled_shares": "0",
        "execution_levels": [],
        "execution_vwap": None,
        "fee_per_share": None,
        "all_in_cost_per_share": None,
        **transport,
    }
    if transport_decision is not None:
        return {**fail_base, "decision": transport_decision}
    timestamps, book_decision = _book_timestamp_decision(
        capture_policy,
        [selected_book],
        request_completed_ts_ms=request_completed_ts_ms,
        phase="arrival",
    )
    if book_decision is not None:
        decision = book_decision.replace("no_arrival_", "no_fill_")
        return {**fail_base, "decision": decision, "book_timestamps_ms": timestamps}
    result = evaluate_arrival(
        policy,
        signal_record,
        selected_book,
        observed_ts_ms=transport["target_ts_ms"],
    )
    return {**result, **transport, "book_timestamps_ms": timestamps}


class CaptureBoundLifecycleLedger(ProspectiveLifecycleLedger):
    def __init__(
        self,
        path: str | Path,
        policy: FrozenPolicy,
        capture_policy: CapturePolicy,
    ) -> None:
        super().__init__(path, policy)
        self.capture_policy = capture_policy
        for line_number, record in enumerate(self.records, start=1):
            if record.get("capture_policy_sha256") != capture_policy.capture_policy_sha256:
                raise LedgerIntegrityError(
                    f"capture policy hash mismatch at line {line_number}"
                )
            if int(record["market_open_epoch_seconds"]) <= capture_policy.valid_market_open_after_epoch_seconds:
                raise LedgerIntegrityError(
                    f"capture freeze violation at line {line_number}"
                )

    def append(
        self,
        *,
        condition_id: str,
        market_open_epoch_seconds: int,
        event_type: str,
        observed_ts_ms: int,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        condition = str(condition_id)
        if not condition:
            raise ValueError("condition_id must be non-empty")
        opening = int(market_open_epoch_seconds)
        _target_ms(self.capture_policy, opening, phase="signal")
        event = str(event_type)
        if event not in {"discovered", "signal", "arrival", "resolution"}:
            raise LifecycleError(f"unsupported event_type: {event}")
        observed = int(observed_ts_ms)
        if observed < 0:
            raise ValueError("observed_ts_ms must be non-negative")
        try:
            canonical_payload = json.loads(_canonical_json(dict(payload)).decode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must be JSON serializable") from exc
        self._validate_order(condition, event, canonical_payload)
        payload_sha256 = hashlib.sha256(_canonical_json(canonical_payload)).hexdigest()
        event_id = hashlib.sha256(
            f"{condition}\0{event}\0{observed}\0{payload_sha256}".encode("utf-8")
        ).hexdigest()
        record_without_hash = {
            "capture_policy_sha256": self.capture_policy.capture_policy_sha256,
            "condition_id": condition,
            "event_id": event_id,
            "event_type": event,
            "market_open_epoch_seconds": opening,
            "observed_ts_ms": observed,
            "payload": canonical_payload,
            "payload_sha256": payload_sha256,
            "policy_sha256": self.policy.policy_sha256,
            "previous_hash": self.head_hash,
            "source_sha256": self.policy.source_sha256,
        }
        record = {
            **record_without_hash,
            "record_hash": hashlib.sha256(_canonical_json(record_without_hash)).hexdigest(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
        self._accept_record(record)
        return dict(record)
