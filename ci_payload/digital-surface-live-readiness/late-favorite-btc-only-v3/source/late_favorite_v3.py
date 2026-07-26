from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence


class FreezeViolation(RuntimeError):
    pass


class LifecycleError(RuntimeError):
    pass


class LedgerIntegrityError(RuntimeError):
    pass


def _validate_sha256(name: str, value: str) -> str:
    text = str(value).lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{name} must be a 64-character SHA-256 hex digest")
    return text


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _decimal(value: object, name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a decimal") from exc
    if not number.is_finite():
        raise ValueError(f"{name} must be finite")
    return number


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


@dataclass(frozen=True, slots=True)
class FrozenPolicy:
    policy_sha256: str
    source_sha256: str
    valid_market_open_after_epoch_seconds: int
    signal_ask_min: Decimal
    entry_second: int
    latency_seconds: int
    shares: Decimal
    adverse_move_cancel: Decimal
    fee_rate: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_sha256", _validate_sha256("policy_sha256", self.policy_sha256))
        object.__setattr__(self, "source_sha256", _validate_sha256("source_sha256", self.source_sha256))
        if int(self.valid_market_open_after_epoch_seconds) < 0:
            raise ValueError("valid_market_open_after_epoch_seconds must be non-negative")
        if int(self.entry_second) < 0:
            raise ValueError("entry_second must be non-negative")
        if int(self.latency_seconds) <= 0:
            raise ValueError("latency_seconds must be positive")
        for name in ("signal_ask_min", "shares", "adverse_move_cancel", "fee_rate"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be a positive finite Decimal")
        if not Decimal("0") < self.signal_ask_min < Decimal("1"):
            raise ValueError("signal_ask_min must be between zero and one")


def load_frozen_policy(
    candidate_spec_path: str | Path,
    freeze_manifest_path: str | Path,
    *,
    source_sha256: str,
) -> FrozenPolicy:
    from datetime import datetime

    spec_path = Path(candidate_spec_path)
    manifest_path = Path(freeze_manifest_path)
    spec_raw = spec_path.read_bytes()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    spec = json.loads(spec_raw)
    got = hashlib.sha256(spec_raw).hexdigest()
    wanted = _validate_sha256("manifest policy_sha256", str(manifest.get("policy_sha256", "")))
    if got != wanted:
        raise FreezeViolation(f"candidate policy SHA-256 mismatch: {got} != {wanted}")
    if spec.get("name") != manifest.get("candidate_name"):
        raise FreezeViolation("candidate name does not match freeze manifest")
    if spec.get("status") != "prospective_shadow_only":
        raise FreezeViolation("candidate is not prospective_shadow_only")
    if spec.get("observation_contract", {}).get("live_submission") != "physically_absent":
        raise FreezeViolation("live submission boundary is not physically absent")
    freeze_text = str(manifest["contamination_boundary"]["valid_market_open_after_utc"])
    freeze_epoch = int(datetime.fromisoformat(freeze_text.replace("Z", "+00:00")).timestamp())
    return FrozenPolicy(
        policy_sha256=got,
        source_sha256=source_sha256,
        valid_market_open_after_epoch_seconds=freeze_epoch,
        signal_ask_min=_decimal(spec["signal"]["signal_ask_min"], "signal_ask_min"),
        entry_second=int(spec["signal"]["entry_second"]),
        latency_seconds=int(spec["arrival"]["latency_seconds"]),
        shares=_decimal(spec["arrival"]["shares"], "shares"),
        adverse_move_cancel=Decimal("0.01"),
        fee_rate=Decimal("0.07"),
    )


def _normalized_book(
    payload: Mapping[str, Any],
    *,
    expected_condition_id: str,
    expected_token_id: str,
) -> dict[str, Any]:
    condition_id = str(payload.get("market") or "")
    token_id = str(payload.get("asset_id") or "")
    if condition_id != expected_condition_id:
        raise LifecycleError(f"book condition mismatch: {condition_id} != {expected_condition_id}")
    if token_id != expected_token_id:
        raise LifecycleError(f"book token mismatch: {token_id} != {expected_token_id}")
    raw_asks = payload.get("asks", [])
    if not isinstance(raw_asks, Sequence) or isinstance(raw_asks, (str, bytes)):
        raise LifecycleError("book asks must be a sequence")
    asks: list[dict[str, str]] = []
    for index, row in enumerate(raw_asks):
        if not isinstance(row, Mapping):
            raise LifecycleError(f"ask level {index} is not an object")
        price = _decimal(row.get("price"), f"ask[{index}].price")
        size = _decimal(row.get("size"), f"ask[{index}].size")
        if not Decimal("0") < price < Decimal("1"):
            raise LifecycleError("ask price must be strictly between zero and one")
        if size < 0:
            raise LifecycleError("ask size must be non-negative")
        if size > 0:
            asks.append({"price": _decimal_text(price), "size": _decimal_text(size)})
    asks.sort(key=lambda row: Decimal(row["price"]))
    normalized = {
        "market": condition_id,
        "asset_id": token_id,
        "timestamp": str(payload.get("timestamp") or ""),
        "hash": str(payload.get("hash") or ""),
        "asks": asks,
        "bids": payload.get("bids", []),
        "min_order_size": str(payload.get("min_order_size") or "0"),
        "tick_size": str(payload.get("tick_size") or "0.01"),
        "neg_risk": bool(payload.get("neg_risk", False)),
        "last_trade_price": None if payload.get("last_trade_price") in (None, "") else str(payload.get("last_trade_price")),
    }
    normalized["payload_sha256"] = hashlib.sha256(_canonical_json(dict(payload))).hexdigest()
    return normalized


def _best_ask(book: Mapping[str, Any]) -> Decimal | None:
    asks = book.get("asks", [])
    if not asks:
        return None
    return Decimal(str(asks[0]["price"]))


def _assert_post_freeze(policy: FrozenPolicy, market_open_epoch_seconds: int) -> int:
    opening = int(market_open_epoch_seconds)
    if opening <= int(policy.valid_market_open_after_epoch_seconds):
        raise FreezeViolation(
            f"market open {opening} is not strictly after freeze {policy.valid_market_open_after_epoch_seconds}"
        )
    return opening


def evaluate_signal(
    policy: FrozenPolicy,
    *,
    condition_id: str,
    market_open_epoch_seconds: int,
    up_token_id: str,
    down_token_id: str,
    up_book: Mapping[str, Any],
    down_book: Mapping[str, Any],
    observed_ts_ms: int,
) -> dict[str, Any]:
    opening = _assert_post_freeze(policy, market_open_epoch_seconds)
    expected_ts_ms = (opening + int(policy.entry_second)) * 1000
    observed = int(observed_ts_ms)
    if observed != expected_ts_ms:
        raise LifecycleError(f"signal observation must be at {expected_ts_ms}, got {observed}")
    condition = str(condition_id)
    if not condition:
        raise ValueError("condition_id must be non-empty")
    up = _normalized_book(up_book, expected_condition_id=condition, expected_token_id=str(up_token_id))
    down = _normalized_book(down_book, expected_condition_id=condition, expected_token_id=str(down_token_id))
    up_ask = _best_ask(up)
    down_ask = _best_ask(down)
    base = {
        "event_type": "signal",
        "condition_id": condition,
        "market_open_epoch_seconds": opening,
        "observed_ts_ms": observed,
        "policy_sha256": policy.policy_sha256,
        "source_sha256": policy.source_sha256,
        "up_token_id": str(up_token_id),
        "down_token_id": str(down_token_id),
        "up_book": up,
        "down_book": down,
        "up_book_sha256": up["payload_sha256"],
        "down_book_sha256": down["payload_sha256"],
        "signal": False,
        "selected_side": None,
        "selected_token_id": None,
        "signal_ask": None,
    }
    if up_ask is None or down_ask is None:
        return {**base, "decision": "no_signal_empty_book"}
    if up_ask == down_ask:
        return {**base, "decision": "no_signal_tied_favorite"}
    selected_side = "Up" if up_ask > down_ask else "Down"
    selected_token_id = str(up_token_id) if selected_side == "Up" else str(down_token_id)
    signal_ask = up_ask if selected_side == "Up" else down_ask
    selected = {
        **base,
        "selected_side": selected_side,
        "selected_token_id": selected_token_id,
        "signal_ask": _decimal_text(signal_ask),
    }
    if signal_ask < policy.signal_ask_min:
        return {**selected, "decision": "no_signal_below_threshold"}
    return {**selected, "decision": "signal", "signal": True}


def _fee_per_share(policy: FrozenPolicy, price: Decimal) -> Decimal:
    return policy.fee_rate * price * (Decimal("1") - price)


def evaluate_arrival(
    policy: FrozenPolicy,
    signal_record: Mapping[str, Any],
    selected_book: Mapping[str, Any],
    *,
    observed_ts_ms: int,
) -> dict[str, Any]:
    if signal_record.get("decision") != "signal" or signal_record.get("signal") is not True:
        raise LifecycleError("arrival requires an active signal")
    if str(signal_record.get("policy_sha256")) != policy.policy_sha256:
        raise LifecycleError("signal policy hash mismatch")
    expected = int(signal_record["observed_ts_ms"]) + int(policy.latency_seconds) * 1000
    observed = int(observed_ts_ms)
    if observed != expected:
        raise LifecycleError(f"arrival observation must be at {expected}, got {observed}")
    condition = str(signal_record["condition_id"])
    token_id = str(signal_record["selected_token_id"])
    book = _normalized_book(selected_book, expected_condition_id=condition, expected_token_id=token_id)
    best_ask = _best_ask(book)
    base = {
        "event_type": "arrival",
        "condition_id": condition,
        "market_open_epoch_seconds": int(signal_record["market_open_epoch_seconds"]),
        "observed_ts_ms": observed,
        "policy_sha256": policy.policy_sha256,
        "source_sha256": policy.source_sha256,
        "selected_side": str(signal_record["selected_side"]),
        "selected_token_id": token_id,
        "signal_ask": str(signal_record["signal_ask"]),
        "arrival_book": book,
        "arrival_book_sha256": book["payload_sha256"],
        "arrival_best_ask": None if best_ask is None else _decimal_text(best_ask),
        "hypothetical_fok_fill": False,
        "filled_shares": "0",
        "execution_levels": [],
        "execution_vwap": None,
        "fee_per_share": None,
        "all_in_cost_per_share": None,
    }
    if best_ask is None:
        return {**base, "decision": "no_fill_empty_arrival_book"}
    signal_ask = Decimal(str(signal_record["signal_ask"]))
    if best_ask < signal_ask - policy.adverse_move_cancel:
        return {**base, "decision": "cancel_adverse_move"}
    if best_ask > signal_ask:
        return {**base, "decision": "no_fill_ask_above_limit"}

    remaining = policy.shares
    notional = Decimal("0")
    fee_total = Decimal("0")
    execution_levels: list[dict[str, str]] = []
    for row in book["asks"]:
        price = Decimal(row["price"])
        if price > signal_ask:
            break
        available = Decimal(row["size"])
        take = min(remaining, available)
        if take <= 0:
            continue
        execution_levels.append({"price": _decimal_text(price), "size": _decimal_text(take)})
        notional += price * take
        fee_total += _fee_per_share(policy, price) * take
        remaining -= take
        if remaining == 0:
            break
    if remaining > 0:
        return {**base, "decision": "no_fill_insufficient_depth"}
    vwap = notional / policy.shares
    fee = fee_total / policy.shares
    return {
        **base,
        "decision": "hypothetical_fok_fill",
        "hypothetical_fok_fill": True,
        "filled_shares": _decimal_text(policy.shares),
        "execution_levels": execution_levels,
        "execution_vwap": _decimal_text(vwap),
        "fee_per_share": _decimal_text(fee),
        "all_in_cost_per_share": _decimal_text(vwap + fee),
    }


def settle_fill(
    fill_record: Mapping[str, Any],
    *,
    official_outcome: str,
    resolution_payload_sha256: str,
) -> dict[str, Any]:
    if fill_record.get("decision") != "hypothetical_fok_fill":
        raise LifecycleError("settlement requires a hypothetical FOK fill")
    outcome = str(official_outcome).title()
    if outcome not in {"Up", "Down"}:
        raise ValueError("official_outcome must be Up or Down")
    resolution_sha = _validate_sha256("resolution_payload_sha256", resolution_payload_sha256)
    selected_side = str(fill_record["selected_side"])
    won = selected_side == outcome
    vwap = Decimal(str(fill_record["execution_vwap"]))
    fee = Decimal(str(fill_record["fee_per_share"]))
    shares = Decimal(str(fill_record["filled_shares"]))
    pnl_per_share = Decimal(int(won)) - vwap - fee
    return {
        "event_type": "resolution",
        "condition_id": str(fill_record["condition_id"]),
        "market_open_epoch_seconds": int(fill_record["market_open_epoch_seconds"]),
        "policy_sha256": str(fill_record["policy_sha256"]),
        "source_sha256": str(fill_record["source_sha256"]),
        "selected_side": selected_side,
        "official_outcome": outcome,
        "official_won": won,
        "resolution_payload_sha256": resolution_sha,
        "execution_vwap": _decimal_text(vwap),
        "fee_per_share": _decimal_text(fee),
        "pnl_per_share": _decimal_text(pnl_per_share),
        "pnl_total": _decimal_text(pnl_per_share * shares),
    }


_ALLOWED_EVENT_TYPES = {"discovered", "signal", "arrival", "resolution"}


class ProspectiveLifecycleLedger:
    def __init__(self, path: str | Path, policy: FrozenPolicy) -> None:
        self.path = Path(path)
        self.policy = policy
        self.records: list[dict[str, Any]] = []
        self.head_hash = "0" * 64
        self._events: dict[str, list[str]] = {}
        self._payloads: dict[str, dict[str, Mapping[str, Any]]] = {}
        if self.path.exists():
            self._load_and_verify()

    def _validate_order(self, condition_id: str, event_type: str, payload: Mapping[str, Any]) -> None:
        sequence = self._events.get(condition_id, [])
        if event_type in sequence:
            raise LifecycleError(f"duplicate {event_type} event for {condition_id}")
        if event_type == "discovered":
            if sequence:
                raise LifecycleError("discovered must be the first event")
            return
        if not sequence or sequence[0] != "discovered":
            raise LifecycleError(f"{event_type} requires a discovered event")
        if event_type == "signal":
            if sequence != ["discovered"]:
                raise LifecycleError("signal must follow discovered")
            return
        signal_payload = self._payloads.get(condition_id, {}).get("signal", {})
        if event_type == "arrival":
            if sequence != ["discovered", "signal"]:
                raise LifecycleError("arrival must follow signal")
            if signal_payload.get("decision") != "signal":
                raise LifecycleError("arrival is invalid after a no-signal decision")
            return
        if event_type == "resolution":
            if signal_payload.get("decision") == "signal":
                if "arrival" not in sequence:
                    raise LifecycleError("resolution requires arrival after an active signal")
            elif sequence != ["discovered", "signal"]:
                raise LifecycleError("no-signal resolution must follow signal")
            return
        raise LifecycleError(f"unsupported event_type: {event_type}")

    def _accept_record(self, record: Mapping[str, Any]) -> None:
        condition = str(record["condition_id"])
        event_type = str(record["event_type"])
        payload = record["payload"]
        self._validate_order(condition, event_type, payload)
        self._events.setdefault(condition, []).append(event_type)
        self._payloads.setdefault(condition, {})[event_type] = payload
        self.records.append(dict(record))
        self.head_hash = str(record["record_hash"])

    def _load_and_verify(self) -> None:
        previous = "0" * 64
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LedgerIntegrityError(f"invalid JSON at line {line_number}") from exc
            stored = str(record.get("record_hash", ""))
            payload_for_hash = dict(record)
            payload_for_hash.pop("record_hash", None)
            if payload_for_hash.get("previous_hash") != previous:
                raise LedgerIntegrityError(f"hash chain mismatch at line {line_number}")
            expected = hashlib.sha256(_canonical_json(payload_for_hash)).hexdigest()
            if stored != expected:
                raise LedgerIntegrityError(f"record hash mismatch at line {line_number}")
            if record.get("policy_sha256") != self.policy.policy_sha256:
                raise LedgerIntegrityError(f"policy hash mismatch at line {line_number}")
            if record.get("source_sha256") != self.policy.source_sha256:
                raise LedgerIntegrityError(f"source hash mismatch at line {line_number}")
            try:
                _assert_post_freeze(self.policy, int(record["market_open_epoch_seconds"]))
                self._accept_record(record)
            except (FreezeViolation, LifecycleError, KeyError, TypeError, ValueError) as exc:
                raise LedgerIntegrityError(f"invalid lifecycle record at line {line_number}") from exc
            previous = stored

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
        opening = _assert_post_freeze(self.policy, market_open_epoch_seconds)
        event = str(event_type)
        if event not in _ALLOWED_EVENT_TYPES:
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
