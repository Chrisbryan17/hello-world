from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from capture_policy import CaptureBoundLifecycleLedger, CapturePolicy
from late_favorite_v3 import FrozenPolicy, settle_fill
from public_collector import (
    GAMMA_BASE,
    PublicHttpClient,
    PublicResponseError,
    RawEvidenceStore,
)


def _json_string_list(value: object, name: str) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name} is not valid JSON") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a string list")
    return list(value)


def parse_terminal_outcome(
    payload: Mapping[str, Any],
    expected_open_epoch_seconds: int,
    expected_condition_id: str,
) -> str:
    opening = int(expected_open_epoch_seconds)
    if str(payload.get("slug")) != f"btc-updown-5m-{opening}":
        raise ValueError("terminal Gamma slug mismatch")
    if str(payload.get("conditionId") or "") != str(expected_condition_id):
        raise ValueError("terminal Gamma condition mismatch")
    if payload.get("closed") is not True:
        raise ValueError("Gamma market is not closed")
    outcomes = _json_string_list(payload.get("outcomes"), "outcomes")
    raw_prices = payload.get("outcomePrices")
    if isinstance(raw_prices, str):
        try:
            raw_prices = json.loads(raw_prices)
        except json.JSONDecodeError as exc:
            raise ValueError("outcomePrices is not valid JSON") from exc
    if not isinstance(raw_prices, list) or len(raw_prices) != len(outcomes):
        raise ValueError("outcomePrices must align with outcomes")
    try:
        prices = [Decimal(str(value)) for value in raw_prices]
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("outcomePrices contains a non-decimal value") from exc
    if set(outcomes) != {"Up", "Down"} or len(outcomes) != 2:
        raise ValueError("terminal market must contain Up and Down")
    winners = [outcome for outcome, price in zip(outcomes, prices, strict=True) if price == 1]
    losers = [outcome for outcome, price in zip(outcomes, prices, strict=True) if price == 0]
    if len(winners) != 1 or len(losers) != 1:
        raise ValueError("outcomePrices are not terminal binary prices")
    return winners[0]


class SingleMarketResolver:
    def __init__(
        self,
        *,
        client: PublicHttpClient,
        evidence_store: RawEvidenceStore,
        ledger: CaptureBoundLifecycleLedger,
        trading_policy: FrozenPolicy,
        capture_policy: CapturePolicy,
    ) -> None:
        self.client = client
        self.evidence_store = evidence_store
        self.ledger = ledger
        self.trading_policy = trading_policy
        self.capture_policy = capture_policy

    def _event_payload(self, condition_id: str, event_type: str) -> Mapping[str, Any] | None:
        for record in reversed(self.ledger.records):
            if record["condition_id"] == condition_id and record["event_type"] == event_type:
                payload = record["payload"]
                if not isinstance(payload, Mapping):
                    raise RuntimeError("lifecycle payload is not an object")
                return payload
        return None

    def _opening(self, condition_id: str) -> int:
        for record in self.ledger.records:
            if record["condition_id"] == condition_id:
                return int(record["market_open_epoch_seconds"])
        raise KeyError(f"unknown condition_id: {condition_id}")

    def resolve(self, condition_id: str) -> dict[str, Any]:
        condition = str(condition_id)
        opening = self._opening(condition)
        discovered = self._event_payload(condition, "discovered")
        signal = self._event_payload(condition, "signal")
        arrival = self._event_payload(condition, "arrival")
        if discovered is None or signal is None:
            raise RuntimeError("resolution requires discovered and signal lifecycle events")
        slug = str(discovered.get("slug") or f"btc-updown-5m-{opening}")
        evidence = self.client.request_json("GET", f"{GAMMA_BASE}/markets/slug/{slug}")
        manifest = self.evidence_store.append(evidence, purpose="official_resolution")
        if not isinstance(evidence.payload, Mapping):
            raise PublicResponseError("Gamma terminal response must be an object")
        outcome = parse_terminal_outcome(evidence.payload, opening, condition)
        if arrival is not None and arrival.get("decision") == "hypothetical_fok_fill":
            resolution = settle_fill(
                arrival,
                official_outcome=outcome,
                resolution_payload_sha256=evidence.response_body_sha256,
            )
            resolution["decision"] = "resolved_fill"
        else:
            resolution = {
                "event_type": "resolution",
                "condition_id": condition,
                "market_open_epoch_seconds": opening,
                "policy_sha256": self.trading_policy.policy_sha256,
                "source_sha256": self.trading_policy.source_sha256,
                "capture_policy_sha256": self.capture_policy.capture_policy_sha256,
                "decision": "resolved_no_fill",
                "official_outcome": outcome,
                "official_won": None,
                "resolution_payload_sha256": evidence.response_body_sha256,
                "pnl_per_share": None,
                "pnl_total": None,
            }
        resolution["gamma_evidence_record_hash"] = manifest["record_hash"]
        self.ledger.append(
            condition_id=condition,
            market_open_epoch_seconds=opening,
            event_type="resolution",
            observed_ts_ms=evidence.request_completed_ts_ms,
            payload=resolution,
        )
        return resolution
