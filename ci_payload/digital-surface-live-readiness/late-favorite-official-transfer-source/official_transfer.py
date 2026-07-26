from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd
import requests

GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"
GAMMA_MARKET_BY_SLUG_URL = "https://gamma-api.polymarket.com/markets/slug/{slug}"
CLOB_SIMPLIFIED_MARKETS_URL = "https://clob.polymarket.com/simplified-markets"
EXPECTED_FILLED_CONDITION_SET_SHA256 = "bf276fbce187d9651d56ecae976520d4251140c1d5b0d440696c5d077838a67a"
TERMINAL_EPSILON = Decimal("1e-12")
USER_AGENT = "late-favorite-official-transfer/1.0 research-only"


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _normalize_condition_id(value: Any) -> str:
    return str(value or "").strip().lower()


def _condition_set_sha256(values: Iterable[Any]) -> str:
    ids = sorted({_normalize_condition_id(value) for value in values if _normalize_condition_id(value)})
    canonical = (("\n".join(ids) + "\n") if ids else "").encode("utf-8")
    return _sha256_bytes(canonical)


def _decode_array(value: Any) -> list[Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, (list, tuple)):
        raise ValueError("value is not an array")
    return list(value)


def _base_parse_result(source: str, classification: str) -> dict[str, Any]:
    return {
        "source": source,
        "classification": classification,
        "official_outcome": None,
        "condition_id": None,
        "closed": None,
        "uma_resolution_status": None,
        "payload_sha256": None,
    }


def parse_gamma_terminal(payload: Any, *, expected_condition_id: str) -> dict[str, Any]:
    result = _base_parse_result("gamma", "malformed_gamma_payload")
    result["payload_sha256"] = _sha256_bytes(_canonical_json_bytes(payload))
    if not isinstance(payload, Mapping):
        return result

    actual = _normalize_condition_id(payload.get("conditionId"))
    expected = _normalize_condition_id(expected_condition_id)
    result.update(
        {
            "condition_id": actual or None,
            "closed": payload.get("closed"),
            "uma_resolution_status": payload.get("umaResolutionStatus"),
        }
    )
    if actual != expected:
        result["classification"] = "mismatched_condition_id"
        return result
    if payload.get("closed") is not True:
        result["classification"] = "not_closed"
        return result

    try:
        outcomes = [str(value).strip().title() for value in _decode_array(payload.get("outcomes"))]
        raw_prices = _decode_array(payload.get("outcomePrices"))
        prices = [Decimal(str(value)) for value in raw_prices]
    except (ValueError, TypeError, json.JSONDecodeError, InvalidOperation):
        return result

    if len(outcomes) != len(prices) or len(outcomes) != 2:
        return result
    if len(set(outcomes)) != len(outcomes) or set(outcomes) != {"Up", "Down"}:
        return result
    if any((not price.is_finite()) or price < 0 or price > 1 for price in prices):
        return result

    winner_indexes = [index for index, price in enumerate(prices) if abs(price - Decimal(1)) <= TERMINAL_EPSILON]
    zero_indexes = [index for index, price in enumerate(prices) if abs(price) <= TERMINAL_EPSILON]
    if len(winner_indexes) != 1 or len(zero_indexes) != len(prices) - 1:
        result["classification"] = "ambiguous_terminal_prices"
        return result

    result["classification"] = "terminal"
    result["official_outcome"] = outcomes[winner_indexes[0]]
    return result


def parse_clob_terminal(payload: Any, *, expected_condition_id: str) -> dict[str, Any]:
    result = _base_parse_result("clob", "malformed_clob_payload")
    result["payload_sha256"] = _sha256_bytes(_canonical_json_bytes(payload))
    if not isinstance(payload, Mapping):
        return result

    actual = _normalize_condition_id(payload.get("condition_id"))
    expected = _normalize_condition_id(expected_condition_id)
    result.update({"condition_id": actual or None, "closed": payload.get("closed")})
    if actual != expected:
        result["classification"] = "mismatched_condition_id"
        return result
    if payload.get("closed") is not True:
        result["classification"] = "not_closed"
        return result

    tokens = payload.get("tokens")
    if not isinstance(tokens, list) or len(tokens) != 2 or not all(isinstance(token, Mapping) for token in tokens):
        return result
    outcomes = [str(token.get("outcome") or "").strip().title() for token in tokens]
    if len(set(outcomes)) != len(outcomes) or set(outcomes) != {"Up", "Down"}:
        return result
    winner_indexes = [index for index, token in enumerate(tokens) if token.get("winner") is True]
    if len(winner_indexes) != 1:
        result["classification"] = "ambiguous_winner_flags"
        return result

    result["classification"] = "terminal"
    result["official_outcome"] = outcomes[winner_indexes[0]]
    return result


def reconcile_terminal_sources(gamma: Mapping[str, Any], clob: Mapping[str, Any]) -> dict[str, Any]:
    gamma_class = str(gamma.get("classification") or "unavailable")
    clob_class = str(clob.get("classification") or "unavailable")
    gamma_outcome = gamma.get("official_outcome")
    clob_outcome = clob.get("official_outcome")
    result = {
        "classification": "unavailable",
        "official_outcome": None,
        "gamma_classification": gamma_class,
        "clob_classification": clob_class,
        "gamma_outcome": gamma_outcome,
        "clob_outcome": clob_outcome,
    }
    if gamma_class == "terminal":
        if clob_class == "terminal":
            if gamma_outcome == clob_outcome:
                result.update(
                    {"classification": "terminal_confirmed_both", "official_outcome": gamma_outcome}
                )
            else:
                result["classification"] = "source_disagreement"
        else:
            result.update({"classification": "terminal_gamma_only", "official_outcome": gamma_outcome})
        return result
    if clob_class == "terminal":
        result["classification"] = "clob_only_unconfirmed"
        return result
    result["classification"] = gamma_class if gamma_class != "unavailable" else clob_class
    return result


@dataclass
class ResponseArchive:
    root: Path
    records: list[dict[str, Any]] = field(default_factory=list)
    sequence: int = 0

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, *, source: str, kind: str, response: requests.Response) -> dict[str, Any]:
        self.sequence += 1
        relative = Path("raw") / source / f"{self.sequence:06d}_{kind}.body"
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = bytes(response.content)
        path.write_bytes(raw)
        record = {
            "sequence": self.sequence,
            "source": source,
            "kind": kind,
            "url": response.url,
            "status_code": int(response.status_code),
            "body_path": str(relative),
            "body_sha256": _sha256_bytes(raw),
            "content_type": response.headers.get("content-type"),
        }
        self.records.append(record)
        return record

    def save_exception(self, *, source: str, kind: str, url: str, error: Exception) -> dict[str, Any]:
        self.sequence += 1
        record = {
            "sequence": self.sequence,
            "source": source,
            "kind": kind,
            "url": url,
            "status_code": None,
            "body_path": None,
            "body_sha256": None,
            "content_type": None,
            "error_type": type(error).__name__,
            "error": str(error),
        }
        self.records.append(record)
        return record

    def write_manifest(self) -> Path:
        path = self.root / "raw_response_manifest.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8", mtime=0) as handle:
            for record in self.records:
                handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        return path


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return session


def _request_with_retry(
    session: requests.Session,
    url: str,
    *,
    params: Any = None,
    timeout: float = 30.0,
    attempts: int = 5,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(url, params=params, timeout=timeout)
            if response.status_code not in {429, 500, 502, 503, 504}:
                return response
            last_error = RuntimeError(f"retryable HTTP status {response.status_code}")
        except requests.RequestException as error:
            last_error = error
        if attempt + 1 < attempts:
            time.sleep(min(8.0, 0.5 * (2**attempt)))
    assert last_error is not None
    raise last_error


def _chunks(values: Sequence[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def _extract_gamma_payloads(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def fetch_gamma_payloads(
    targets: pd.DataFrame,
    *,
    archive: ResponseArchive,
    session: requests.Session,
    batch_size: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    target_ids = sorted({_normalize_condition_id(value) for value in targets["condition_id"]})
    slugs = {
        _normalize_condition_id(row.condition_id): str(row.slug)
        for row in targets[["condition_id", "slug"]].drop_duplicates("condition_id").itertuples(index=False)
    }
    payloads: dict[str, dict[str, Any]] = {}
    failures: dict[str, dict[str, Any]] = {}

    def absorb(response: requests.Response, requested: set[str], kind: str) -> set[str]:
        evidence = archive.save(source="gamma", kind=kind, response=response)
        if response.status_code != 200:
            return set()
        try:
            decoded = response.json()
        except ValueError:
            return set()
        matched: set[str] = set()
        for payload in _extract_gamma_payloads(decoded):
            condition_id = _normalize_condition_id(payload.get("conditionId"))
            if condition_id not in requested:
                continue
            if condition_id in payloads:
                failures[condition_id] = {
                    "classification": "duplicate_gamma_records",
                    "official_outcome": None,
                }
                continue
            payload = dict(payload)
            payload["_response_body_sha256"] = evidence["body_sha256"]
            payload["_response_url"] = evidence["url"]
            payloads[condition_id] = payload
            matched.add(condition_id)
        return matched

    for batch_number, batch in enumerate(_chunks(target_ids, batch_size), start=1):
        requested = set(batch)
        repeated_params: list[tuple[str, str | int]] = [("limit", len(batch)), ("offset", 0)]
        repeated_params.extend(("condition_ids", condition_id) for condition_id in batch)
        try:
            response = _request_with_retry(session, GAMMA_MARKETS_URL, params=repeated_params)
            matched = absorb(response, requested, f"batch_{batch_number:04d}_repeated")
        except Exception as error:
            archive.save_exception(
                source="gamma", kind=f"batch_{batch_number:04d}_repeated", url=GAMMA_MARKETS_URL, error=error
            )
            matched = set()

        missing = requested - matched - set(payloads)
        if missing:
            comma_params = {
                "limit": len(missing),
                "offset": 0,
                "condition_ids": ",".join(sorted(missing)),
            }
            try:
                response = _request_with_retry(session, GAMMA_MARKETS_URL, params=comma_params)
                absorb(response, missing, f"batch_{batch_number:04d}_comma")
            except Exception as error:
                archive.save_exception(
                    source="gamma", kind=f"batch_{batch_number:04d}_comma", url=GAMMA_MARKETS_URL, error=error
                )

    remaining = [condition_id for condition_id in target_ids if condition_id not in payloads]
    for index, condition_id in enumerate(remaining, start=1):
        slug = slugs.get(condition_id, "").strip()
        if not slug or slug.lower() == "nan":
            failures[condition_id] = {"classification": "missing_slug", "official_outcome": None}
            continue
        url = GAMMA_MARKET_BY_SLUG_URL.format(slug=slug)
        try:
            response = _request_with_retry(session, url)
            evidence = archive.save(source="gamma", kind=f"slug_{index:05d}", response=response)
            if response.status_code != 200:
                failures[condition_id] = {
                    "classification": f"gamma_http_{response.status_code}",
                    "official_outcome": None,
                }
                continue
            decoded = response.json()
            candidates = _extract_gamma_payloads(decoded)
            if len(candidates) != 1:
                failures[condition_id] = {
                    "classification": "gamma_slug_cardinality_error",
                    "official_outcome": None,
                }
                continue
            payload = candidates[0]
            payload["_response_body_sha256"] = evidence["body_sha256"]
            payload["_response_url"] = evidence["url"]
            payloads[condition_id] = payload
        except Exception as error:
            archive.save_exception(source="gamma", kind=f"slug_{index:05d}", url=url, error=error)
            failures[condition_id] = {
                "classification": "gamma_request_exception",
                "official_outcome": None,
            }
    return payloads, failures


def fetch_clob_payloads(
    target_ids: set[str],
    *,
    archive: ResponseArchive,
    session: requests.Session,
    max_pages: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    cursor: str | None = None
    seen_cursors: set[str] = set()
    audit: dict[str, Any] = {"pages": 0, "terminated": None, "last_cursor": None}

    for page in range(1, max_pages + 1):
        params = None if cursor is None else {"next_cursor": cursor}
        try:
            response = _request_with_retry(session, CLOB_SIMPLIFIED_MARKETS_URL, params=params)
        except Exception as error:
            archive.save_exception(
                source="clob", kind=f"page_{page:05d}", url=CLOB_SIMPLIFIED_MARKETS_URL, error=error
            )
            audit.update({"pages": page - 1, "terminated": "request_exception", "last_cursor": cursor})
            break
        evidence = archive.save(source="clob", kind=f"page_{page:05d}", response=response)
        if response.status_code != 200:
            audit.update(
                {"pages": page, "terminated": f"http_{response.status_code}", "last_cursor": cursor}
            )
            break
        try:
            decoded = response.json()
        except ValueError:
            audit.update({"pages": page, "terminated": "malformed_json", "last_cursor": cursor})
            break
        if not isinstance(decoded, Mapping):
            audit.update({"pages": page, "terminated": "malformed_payload", "last_cursor": cursor})
            break
        data = decoded.get("data")
        if not isinstance(data, list):
            audit.update({"pages": page, "terminated": "malformed_data", "last_cursor": cursor})
            break
        for item in data:
            if not isinstance(item, Mapping):
                continue
            condition_id = _normalize_condition_id(item.get("condition_id"))
            if condition_id not in target_ids or condition_id in payloads:
                continue
            payload = dict(item)
            payload["_response_body_sha256"] = evidence["body_sha256"]
            payload["_response_url"] = evidence["url"]
            payloads[condition_id] = payload
        next_cursor = decoded.get("next_cursor")
        audit.update({"pages": page, "last_cursor": next_cursor})
        if not next_cursor or next_cursor == "LTE=":
            audit["terminated"] = "end_cursor"
            break
        next_cursor = str(next_cursor)
        if next_cursor in seen_cursors:
            audit["terminated"] = "repeated_cursor"
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    else:
        audit["terminated"] = "max_pages"
    audit["matched_targets"] = len(payloads)
    return payloads, audit


def _unavailable(source: str, classification: str = "unavailable") -> dict[str, Any]:
    result = _base_parse_result(source, classification)
    return result


def build_transfer_ledger(
    eligible: pd.DataFrame,
    gamma_payloads: Mapping[str, Mapping[str, Any]],
    gamma_failures: Mapping[str, Mapping[str, Any]],
    clob_payloads: Mapping[str, Mapping[str, Any]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for trade in eligible.itertuples(index=False):
        condition_id = _normalize_condition_id(trade.condition_id)
        gamma_payload = gamma_payloads.get(condition_id)
        if gamma_payload is not None:
            gamma = parse_gamma_terminal(gamma_payload, expected_condition_id=condition_id)
            gamma_url = gamma_payload.get("_response_url")
            gamma_body_sha256 = gamma_payload.get("_response_body_sha256")
        else:
            failure = gamma_failures.get(condition_id) or {}
            gamma = _unavailable("gamma", str(failure.get("classification") or "unavailable"))
            gamma_url = None
            gamma_body_sha256 = None

        clob_payload = clob_payloads.get(condition_id)
        if clob_payload is not None:
            clob = parse_clob_terminal(clob_payload, expected_condition_id=condition_id)
            clob_url = clob_payload.get("_response_url")
            clob_body_sha256 = clob_payload.get("_response_body_sha256")
        else:
            clob = _unavailable("clob")
            clob_url = None
            clob_body_sha256 = None

        reconciled = reconcile_terminal_sources(gamma, clob)
        official_outcome = reconciled["official_outcome"]
        official_usable = official_outcome in {"Up", "Down"}
        official_won = bool(str(trade.selected_side).title() == official_outcome) if official_usable else None
        arrival_ask = float(trade.arrival_ask)
        fee = float(trade.fee_per_share) if pd.notna(trade.fee_per_share) else 0.07 * arrival_ask * (1.0 - arrival_ask)
        official_pnl_per_share = (float(official_won) - arrival_ask - fee) if official_usable else None
        inferred = str(trade.inferred_outcome).title() if pd.notna(trade.inferred_outcome) else None
        inferred = inferred if inferred in {"Up", "Down"} else None

        rows.append(
            {
                **trade._asdict(),
                "condition_id": condition_id,
                "gamma_classification": gamma["classification"],
                "gamma_outcome": gamma.get("official_outcome"),
                "gamma_payload_sha256": gamma.get("payload_sha256"),
                "gamma_response_body_sha256": gamma_body_sha256,
                "gamma_url": gamma_url,
                "gamma_closed": gamma.get("closed"),
                "gamma_uma_resolution_status": gamma.get("uma_resolution_status"),
                "clob_classification": clob["classification"],
                "clob_outcome": clob.get("official_outcome"),
                "clob_payload_sha256": clob.get("payload_sha256"),
                "clob_response_body_sha256": clob_body_sha256,
                "clob_url": clob_url,
                "official_classification": reconciled["classification"],
                "official_outcome": official_outcome,
                "official_label_usable": official_usable,
                "official_won": official_won,
                "official_pnl_per_share": official_pnl_per_share,
                "official_pnl_at_five_shares": official_pnl_per_share * 5 if official_pnl_per_share is not None else None,
                "inferred_label_available": inferred is not None,
                "official_vs_inferred_agree": (official_outcome == inferred) if official_usable and inferred else None,
            }
        )
    return pd.DataFrame(rows)


def _counts(series: pd.Series) -> dict[str, int]:
    return {str(key): int(value) for key, value in series.value_counts(dropna=False).sort_index().items()}


def summarize_transfer(ledger: pd.DataFrame) -> dict[str, Any]:
    usable = ledger.loc[ledger["official_label_usable"]].copy()
    comparable = usable.loc[usable["inferred_label_available"]].copy()
    by_asset: dict[str, Any] = {}
    for asset, frame in ledger.groupby("asset", sort=True):
        asset_usable = frame.loc[frame["official_label_usable"]]
        asset_comparable = asset_usable.loc[asset_usable["inferred_label_available"]]
        by_asset[str(asset)] = {
            "fills": int(len(frame)),
            "official_usable": int(len(asset_usable)),
            "official_coverage": float(len(asset_usable) / len(frame)) if len(frame) else None,
            "official_wins": int(asset_usable["official_won"].sum()),
            "official_win_rate": float(asset_usable["official_won"].mean()) if len(asset_usable) else None,
            "official_pnl_at_five_shares": float(asset_usable["official_pnl_at_five_shares"].sum()),
            "comparable_to_inferred": int(len(asset_comparable)),
            "official_vs_inferred_agreement": (
                float(asset_comparable["official_vs_inferred_agree"].mean()) if len(asset_comparable) else None
            ),
        }
    return {
        "fills": int(len(ledger)),
        "official_usable": int(len(usable)),
        "official_coverage": float(len(usable) / len(ledger)) if len(ledger) else None,
        "official_wins": int(usable["official_won"].sum()),
        "official_win_rate": float(usable["official_won"].mean()) if len(usable) else None,
        "official_mean_pnl_per_share": float(usable["official_pnl_per_share"].mean()) if len(usable) else None,
        "official_pnl_at_five_shares": float(usable["official_pnl_at_five_shares"].sum()),
        "comparable_to_inferred": int(len(comparable)),
        "official_vs_inferred_agreement": (
            float(comparable["official_vs_inferred_agree"].mean()) if len(comparable) else None
        ),
        "official_vs_inferred_disagreements": int((comparable["official_vs_inferred_agree"] == False).sum()),
        "classification_counts": _counts(ledger["official_classification"]),
        "gamma_classification_counts": _counts(ledger["gamma_classification"]),
        "clob_classification_counts": _counts(ledger["clob_classification"]),
        "by_asset": by_asset,
    }


def run_transfer(
    *,
    eligible_path: Path,
    out_dir: Path,
    batch_size: int,
    clob_max_pages: int,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    eligible = pd.read_csv(eligible_path)
    required = {
        "condition_id",
        "slug",
        "asset",
        "selected_side",
        "arrival_ask",
        "fee_per_share",
        "inferred_outcome",
    }
    missing = sorted(required - set(eligible.columns))
    if missing:
        raise RuntimeError(f"eligible ledger missing columns: {missing}")
    condition_set_sha256 = _condition_set_sha256(eligible["condition_id"])
    if condition_set_sha256 != EXPECTED_FILLED_CONDITION_SET_SHA256:
        raise RuntimeError(
            f"filled condition-set SHA-256 mismatch: {condition_set_sha256} != "
            f"{EXPECTED_FILLED_CONDITION_SET_SHA256}"
        )
    if eligible["condition_id"].duplicated().any():
        raise RuntimeError("eligible ledger contains duplicate condition IDs")

    archive = ResponseArchive(out_dir)
    session = _session()
    targets = eligible[["condition_id", "slug"]].copy()
    gamma_payloads, gamma_failures = fetch_gamma_payloads(
        targets, archive=archive, session=session, batch_size=batch_size
    )
    clob_payloads, clob_scan = fetch_clob_payloads(
        {_normalize_condition_id(value) for value in eligible["condition_id"]},
        archive=archive,
        session=session,
        max_pages=clob_max_pages,
    )
    raw_manifest = archive.write_manifest()

    ledger = build_transfer_ledger(eligible, gamma_payloads, gamma_failures, clob_payloads)
    ledger = ledger.sort_values(["market_start", "asset", "condition_id"])
    ledger_path = out_dir / "official_transfer_ledger.csv.gz"
    ledger.to_csv(ledger_path, index=False, compression={"method": "gzip", "mtime": 0})

    summary = summarize_transfer(ledger)
    audit = {
        "candidate": "late_favorite_btc_eth_v2_diagnostic",
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "filled_condition_set_sha256": condition_set_sha256,
        "expected_filled_condition_set_sha256": EXPECTED_FILLED_CONDITION_SET_SHA256,
        "eligible_input_sha256": _sha256_bytes(eligible_path.read_bytes()),
        "source_module_sha256": _sha256_bytes(Path(__file__).read_bytes()),
        "gamma_endpoint": GAMMA_MARKETS_URL,
        "clob_endpoint": CLOB_SIMPLIFIED_MARKETS_URL,
        "gamma_payloads": len(gamma_payloads),
        "gamma_failures": len(gamma_failures),
        "clob_payloads": len(clob_payloads),
        "clob_scan": clob_scan,
        "raw_responses": len(archive.records),
        "raw_response_manifest_sha256": _sha256_bytes(raw_manifest.read_bytes()),
        "live_submission": "physically_absent",
        "credentials_used": 0,
        "thresholds_changed": 0,
        **summary,
    }
    audit_path = out_dir / "AUDIT.json"
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")

    coverage = audit["official_coverage"]
    win_rate = audit["official_win_rate"]
    mean_pnl = audit["official_mean_pnl_per_share"]
    report = (
        "# Late-Favorite BTC/ETH Official Outcome Transfer\n\n"
        "## Result\n\n"
        f"- Frozen filled condition set: `{condition_set_sha256}`\n"
        f"- Fills: {audit['fills']:,}\n"
        f"- Official usable labels: {audit['official_usable']:,} ({coverage:.4%})\n"
        f"- Official win rate: {win_rate:.4%}\n"
        f"- Official mean P&L/share: {mean_pnl:.6f}\n"
        f"- Official P&L at five shares: ${audit['official_pnl_at_five_shares']:.6f}\n"
        f"- Comparable inferred labels: {audit['comparable_to_inferred']:,}\n"
        f"- Official/inferred disagreements: {audit['official_vs_inferred_disagreements']:,}\n"
        f"- Gamma payloads: {audit['gamma_payloads']:,}\n"
        f"- CLOB corroborating payloads: {audit['clob_payloads']:,}\n\n"
        "## Evidence boundary\n\n"
        "Gamma is the primary official terminal source. CLOB winner flags corroborate Gamma where available. CLOB-only outcomes are not promoted. Every HTTP response body is retained with its URL, status code, and SHA-256. This job contains no credentials or order-submission implementation.\n"
    )
    report_path = out_dir / "REPORT.md"
    report_path.write_text(report)

    top_level_outputs = [audit_path, ledger_path, raw_manifest, report_path]
    sums_path = out_dir / "SHA256SUMS"
    sums_path.write_text(
        "".join(f"{_sha256_bytes(path.read_bytes())}  {path.name}\n" for path in sorted(top_level_outputs))
    )
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eligible-trades", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--clob-max-pages", type=int, default=5000)
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 100:
        raise SystemExit("batch size must be between 1 and 100")
    audit = run_transfer(
        eligible_path=args.eligible_trades,
        out_dir=args.out_dir,
        batch_size=args.batch_size,
        clob_max_pages=args.clob_max_pages,
    )
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
