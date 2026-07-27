from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse

import requests

from capture_policy import (
    CaptureBoundLifecycleLedger,
    CapturePolicy,
    evaluate_arrival_capture,
    evaluate_signal_capture,
)
from late_favorite_v3 import FrozenPolicy

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"


class PublicEndpointViolation(RuntimeError):
    pass


class PublicResponseError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PublicHttpEvidence:
    method: str
    url: str
    status_code: int
    request_started_ts_ms: int
    request_completed_ts_ms: int
    response_body_sha256: str
    request_body_sha256: str | None
    body: bytes
    payload: object


@dataclass(frozen=True, slots=True)
class BtcFiveMinuteMarket:
    condition_id: str
    slug: str
    open_epoch_seconds: int
    up_token_id: str
    down_token_id: str


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _validate_public_endpoint(method: str, url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise PublicEndpointViolation("only credential-free HTTPS endpoints are allowed")
    normalized_method = method.upper()
    if parsed.netloc == "gamma-api.polymarket.com":
        allowed = normalized_method == "GET" and parsed.path.startswith("/markets/slug/")
    elif parsed.netloc == "clob.polymarket.com":
        allowed = normalized_method == "POST" and parsed.path == "/books"
    else:
        allowed = False
    if not allowed:
        raise PublicEndpointViolation(f"endpoint is outside the frozen public allowlist: {method} {url}")


class PublicHttpClient:
    def __init__(
        self,
        *,
        requester: Callable[..., Any] = requests.request,
        clock_ms: Callable[[], int] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.requester = requester
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def request_json(
        self,
        method: str,
        url: str,
        *,
        json_body: object | None = None,
    ) -> PublicHttpEvidence:
        normalized_method = method.upper()
        _validate_public_endpoint(normalized_method, url)
        headers = {
            "Accept": "application/json",
            "User-Agent": "btc-only-v3-prospective-shadow/1",
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        started = int(self.clock_ms())
        response = self.requester(
            normalized_method,
            url,
            headers=headers,
            timeout=self.timeout_seconds,
            json=json_body,
        )
        completed = int(self.clock_ms())
        status = int(response.status_code)
        body = bytes(response.content)
        if status != 200:
            raise PublicResponseError(f"public endpoint returned HTTP {status}: {url}")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise PublicResponseError(f"public endpoint returned invalid JSON: {url}") from exc
        request_hash = None if json_body is None else hashlib.sha256(_canonical_json(json_body)).hexdigest()
        return PublicHttpEvidence(
            method=normalized_method,
            url=url,
            status_code=status,
            request_started_ts_ms=started,
            request_completed_ts_ms=completed,
            response_body_sha256=hashlib.sha256(body).hexdigest(),
            request_body_sha256=request_hash,
            body=body,
            payload=payload,
        )


class RawEvidenceStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.manifest_path = self.root / "manifest.jsonl"
        self.records: list[dict[str, Any]] = []
        self.head_hash = "0" * 64
        if self.manifest_path.exists():
            self._load_and_verify()

    def _load_and_verify(self) -> None:
        previous = "0" * 64
        for line_number, line in enumerate(
            self.manifest_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid evidence manifest JSON at line {line_number}") from exc
            stored = str(row.get("record_hash", ""))
            without = dict(row)
            without.pop("record_hash", None)
            if without.get("previous_hash") != previous:
                raise RuntimeError(f"evidence hash chain mismatch at line {line_number}")
            expected = hashlib.sha256(_canonical_json(without)).hexdigest()
            if stored != expected:
                raise RuntimeError(f"evidence record hash mismatch at line {line_number}")
            body_path = self.root / str(row["body_path"])
            if not body_path.is_file():
                raise RuntimeError(f"missing evidence body at line {line_number}")
            if hashlib.sha256(body_path.read_bytes()).hexdigest() != row["response_body_sha256"]:
                raise RuntimeError(f"evidence body hash mismatch at line {line_number}")
            self.records.append(row)
            self.head_hash = stored
            previous = stored

    def append(self, evidence: PublicHttpEvidence, *, purpose: str) -> dict[str, Any]:
        if not purpose:
            raise ValueError("purpose must be non-empty")
        body_rel = Path("bodies") / f"{evidence.response_body_sha256}.json"
        body_path = self.root / body_rel
        body_path.parent.mkdir(parents=True, exist_ok=True)
        if body_path.exists() and hashlib.sha256(body_path.read_bytes()).hexdigest() != evidence.response_body_sha256:
            raise RuntimeError("existing evidence body conflicts with response hash")
        if not body_path.exists():
            body_path.write_bytes(evidence.body)
        without = {
            "body_path": body_rel.as_posix(),
            "method": evidence.method,
            "previous_hash": self.head_hash,
            "purpose": str(purpose),
            "request_body_sha256": evidence.request_body_sha256,
            "request_completed_ts_ms": evidence.request_completed_ts_ms,
            "request_started_ts_ms": evidence.request_started_ts_ms,
            "response_body_sha256": evidence.response_body_sha256,
            "status_code": evidence.status_code,
            "url": evidence.url,
        }
        row = {**without, "record_hash": hashlib.sha256(_canonical_json(without)).hexdigest()}
        self.root.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
        self.records.append(row)
        self.head_hash = row["record_hash"]
        return dict(row)


def _json_list(value: object, name: str) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name} is not valid JSON") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a string list")
    return list(value)


def parse_btc_five_minute_market(
    payload: Mapping[str, Any], expected_open_epoch_seconds: int
) -> BtcFiveMinuteMarket:
    opening = int(expected_open_epoch_seconds)
    expected_slug = f"btc-updown-5m-{opening}"
    if str(payload.get("slug")) != expected_slug:
        raise ValueError("Gamma market slug does not match requested BTC window")
    if payload.get("active") is not True or payload.get("closed") is not False:
        raise ValueError("Gamma market is not active and open")
    if payload.get("enableOrderBook") is not True:
        raise ValueError("Gamma market is not CLOB-enabled")
    condition_id = str(payload.get("conditionId") or "")
    if not condition_id:
        raise ValueError("Gamma market is missing conditionId")
    outcomes = _json_list(payload.get("outcomes"), "outcomes")
    token_ids = _json_list(payload.get("clobTokenIds"), "clobTokenIds")
    if len(outcomes) != 2 or len(token_ids) != 2 or set(outcomes) != {"Up", "Down"}:
        raise ValueError("Gamma market must contain exactly Up and Down outcomes")
    mapping = dict(zip(outcomes, token_ids, strict=True))
    if not mapping["Up"] or not mapping["Down"] or mapping["Up"] == mapping["Down"]:
        raise ValueError("Gamma market contains invalid token IDs")
    return BtcFiveMinuteMarket(
        condition_id=condition_id,
        slug=expected_slug,
        open_epoch_seconds=opening,
        up_token_id=mapping["Up"],
        down_token_id=mapping["Down"],
    )


def _parse_books(payload: object, requested_token_ids: Sequence[str]) -> dict[str, Mapping[str, Any]]:
    if not isinstance(payload, list):
        raise PublicResponseError("CLOB /books response must be a list")
    requested = [str(token) for token in requested_token_ids]
    found: dict[str, Mapping[str, Any]] = {}
    for row in payload:
        if not isinstance(row, Mapping):
            raise PublicResponseError("CLOB /books row must be an object")
        token = str(row.get("asset_id") or "")
        if token in found:
            raise PublicResponseError(f"duplicate CLOB book for token {token}")
        found[token] = row
    if set(found) != set(requested):
        raise PublicResponseError("CLOB /books response token set mismatch")
    return found


def next_collectable_open(now_ts_ms: int, cutoff_epoch_seconds: int) -> int:
    now_ms = int(now_ts_ms)
    opening = (now_ms // 1000 // 300) * 300
    if now_ms > opening * 1000 + 210_000:
        opening += 300
    while opening <= int(cutoff_epoch_seconds):
        opening += 300
    return opening


class SingleMarketCollector:
    def __init__(
        self,
        *,
        client: PublicHttpClient,
        evidence_store: RawEvidenceStore,
        ledger: CaptureBoundLifecycleLedger,
        trading_policy: FrozenPolicy,
        capture_policy: CapturePolicy,
        sleep_until_ms: Callable[[int], None],
    ) -> None:
        self.client = client
        self.evidence_store = evidence_store
        self.ledger = ledger
        self.trading_policy = trading_policy
        self.capture_policy = capture_policy
        self.sleep_until_ms = sleep_until_ms

    def capture(self, market_open_epoch_seconds: int) -> dict[str, Any]:
        opening = int(market_open_epoch_seconds)
        slug = f"btc-updown-5m-{opening}"
        discovery = self.client.request_json("GET", f"{GAMMA_BASE}/markets/slug/{slug}")
        discovery_manifest = self.evidence_store.append(discovery, purpose="market_discovery")
        if not isinstance(discovery.payload, Mapping):
            raise PublicResponseError("Gamma market response must be an object")
        market = parse_btc_five_minute_market(discovery.payload, opening)
        self.ledger.append(
            condition_id=market.condition_id,
            market_open_epoch_seconds=opening,
            event_type="discovered",
            observed_ts_ms=discovery.request_completed_ts_ms,
            payload={
                "slug": market.slug,
                "up_token_id": market.up_token_id,
                "down_token_id": market.down_token_id,
                "gamma_response_body_sha256": discovery.response_body_sha256,
                "evidence_record_hash": discovery_manifest["record_hash"],
            },
        )
        signal_target = opening * 1000 + self.capture_policy.signal_target_offset_ms
        self.sleep_until_ms(signal_target)
        signal_body = [{"token_id": market.up_token_id}, {"token_id": market.down_token_id}]
        signal_http = self.client.request_json(
            "POST", f"{CLOB_BASE}/books", json_body=signal_body
        )
        self.evidence_store.append(signal_http, purpose="signal_books")
        signal_books = _parse_books(signal_http.payload, [market.up_token_id, market.down_token_id])
        signal = evaluate_signal_capture(
            self.trading_policy,
            self.capture_policy,
            condition_id=market.condition_id,
            market_open_epoch_seconds=opening,
            up_token_id=market.up_token_id,
            down_token_id=market.down_token_id,
            up_book=signal_books[market.up_token_id],
            down_book=signal_books[market.down_token_id],
            request_started_ts_ms=signal_http.request_started_ts_ms,
            request_completed_ts_ms=signal_http.request_completed_ts_ms,
            response_payload_sha256=signal_http.response_body_sha256,
        )
        self.ledger.append(
            condition_id=market.condition_id,
            market_open_epoch_seconds=opening,
            event_type="signal",
            observed_ts_ms=signal["observed_ts_ms"],
            payload=signal,
        )
        if signal["decision"] != "signal":
            return signal
        arrival_target = opening * 1000 + self.capture_policy.arrival_target_offset_ms
        self.sleep_until_ms(arrival_target)
        selected_token = str(signal["selected_token_id"])
        arrival_body = [{"token_id": selected_token}]
        arrival_http = self.client.request_json(
            "POST", f"{CLOB_BASE}/books", json_body=arrival_body
        )
        self.evidence_store.append(arrival_http, purpose="arrival_book")
        arrival_books = _parse_books(arrival_http.payload, [selected_token])
        arrival = evaluate_arrival_capture(
            self.trading_policy,
            self.capture_policy,
            signal,
            arrival_books[selected_token],
            request_started_ts_ms=arrival_http.request_started_ts_ms,
            request_completed_ts_ms=arrival_http.request_completed_ts_ms,
            response_payload_sha256=arrival_http.response_body_sha256,
        )
        self.ledger.append(
            condition_id=market.condition_id,
            market_open_epoch_seconds=opening,
            event_type="arrival",
            observed_ts_ms=arrival["observed_ts_ms"],
            payload=arrival,
        )
        return arrival
