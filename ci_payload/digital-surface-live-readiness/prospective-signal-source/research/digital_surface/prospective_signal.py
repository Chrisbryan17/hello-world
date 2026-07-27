from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .binance_public import BTCMarketState
from .candidates import CandidateConfig, generate_cross_horizon_candidates, select_one_candidate_per_expiry
from .market_discovery import GammaMarketRecord
from .public_books import PublicOrderBook


_EPS = 1e-6


def _sha256(name: str, value: str) -> str:
    text = str(value).lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{name} must be a 64-character SHA-256 hex digest")
    return text


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(float(value) / math.sqrt(2.0)))


def _logit(probability: float) -> float:
    p = min(max(float(probability), _EPS), 1.0 - _EPS)
    return math.log(p / (1.0 - p))


def _expit(value: float) -> float:
    if value >= 0:
        inverse = math.exp(-value)
        return 1.0 / (1.0 + inverse)
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


@dataclass(frozen=True, slots=True)
class FrozenSurfacePolicy:
    coefficients: tuple[float, float, float, float]
    training_rows: int
    training_contracts: int
    config: CandidateConfig
    policy_sha256: str
    selection: str = "first_trigger_per_expiry"
    flow_assumption: str = "zero_without_public_causal_trade_flow"

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any], *, policy_sha256: str) -> "FrozenSurfacePolicy":
        if int(payload.get("version", -1)) != 1:
            raise ValueError("unsupported frozen surface policy version")
        model = payload.get("model")
        candidate = payload.get("candidate")
        if not isinstance(model, Mapping) or not isinstance(candidate, Mapping):
            raise ValueError("frozen policy requires model and candidate objects")
        coefficients = tuple(float(value) for value in model.get("coefficients", []))
        if len(coefficients) != 4 or not all(math.isfinite(value) for value in coefficients):
            raise ValueError("surface coefficients must contain four finite values")
        if coefficients[1] < 0.05:
            raise ValueError("structural slope must preserve positive spot monotonicity")
        training_rows = int(model.get("training_rows", 0))
        training_contracts = int(model.get("training_contracts", 0))
        if training_rows < 0 or training_contracts <= 0:
            raise ValueError("frozen policy requires positive training_contracts")
        config = CandidateConfig(
            min_edge=float(candidate["min_edge"]),
            max_total_cost=float(candidate["max_total_cost"]),
            min_tau_s=float(candidate.get("min_tau_s", 3.0)),
            max_tau_s=float(candidate["max_tau_s"]),
            decision_cadence_s=int(candidate.get("decision_cadence_s", 5)),
            pair_gap_ms=int(candidate.get("pair_gap_ms", 2_000)),
            slippage=float(candidate.get("slippage", 0.01)),
            uncertainty_penalty=float(candidate.get("uncertainty_penalty", 0.0)),
        )
        selection = str(payload.get("selection") or "")
        if selection != "first_trigger_per_expiry":
            raise ValueError("only the causal first-trigger selection policy is supported")
        flow_assumption = str(payload.get("flow_assumption") or "")
        if flow_assumption != "zero_without_public_causal_trade_flow":
            raise ValueError("prospective policy must freeze the zero-flow assumption")
        return cls(
            coefficients=(coefficients[0], coefficients[1], coefficients[2], coefficients[3]),
            training_rows=training_rows,
            training_contracts=training_contracts,
            config=config,
            policy_sha256=_sha256("policy_sha256", policy_sha256),
            selection=selection,
            flow_assumption=flow_assumption,
        )

    def fair_yes(self, *, spot: float, strike: float, tau_s: float, volatility_per_s: float, horizon_s: int) -> tuple[float, float, float]:
        if spot <= 0 or strike <= 0 or tau_s <= 0 or volatility_per_s <= 0:
            raise ValueError("surface inputs must be positive")
        z_moneyness = math.log(spot / strike) / (volatility_per_s * math.sqrt(tau_s))
        structural = min(max(_normal_cdf(z_moneyness), _EPS), 1.0 - _EPS)
        intercept, structural_slope, horizon_offset, flow_coefficient = self.coefficients
        eta = intercept + structural_slope * _logit(structural) + horizon_offset * (1.0 if horizon_s == 900 else 0.0)
        eta += flow_coefficient * 0.0
        fair = min(max(_expit(eta), _EPS), 1.0 - _EPS)
        uncertainty = math.sqrt(fair * (1.0 - fair) / self.training_contracts)
        return fair, uncertainty, z_moneyness


def load_frozen_surface_policy(path: str | Path) -> FrozenSurfacePolicy:
    policy_path = Path(path)
    raw = policy_path.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, Mapping):
        raise ValueError("frozen surface policy must be a JSON object")
    return FrozenSurfacePolicy.from_payload(payload, policy_sha256=hashlib.sha256(raw).hexdigest())


def generate_prospective_candidates(
    markets: Sequence[GammaMarketRecord],
    books: Mapping[str, PublicOrderBook],
    state: BTCMarketState,
    *,
    book_observed_ts_ms: int,
    policy: FrozenSurfacePolicy,
    prospective_head_sha256: str,
    book_ledger_head_sha256: str,
    spot_state_head_sha256: str,
    max_evidence_age_ms: int = 2_000,
) -> tuple[pd.DataFrame, dict[str, object]]:
    evidence_hashes = {
        "policy_sha256": _sha256("policy_sha256", policy.policy_sha256),
        "prospective_head_sha256": _sha256("prospective_head_sha256", prospective_head_sha256),
        "book_ledger_head_sha256": _sha256("book_ledger_head_sha256", book_ledger_head_sha256),
        "spot_state_head_sha256": _sha256("spot_state_head_sha256", spot_state_head_sha256),
    }
    book_ts = int(book_observed_ts_ms)
    decision_ts_ms = max(book_ts, int(state.observed_ts_ms))
    if max_evidence_age_ms < 0:
        raise ValueError("max_evidence_age_ms must be non-negative")
    book_age = decision_ts_ms - book_ts
    state_age = decision_ts_ms - int(state.observed_ts_ms)
    if book_age > max_evidence_age_ms or state_age > max_evidence_age_ms:
        raise ValueError(
            f"stale evidence: book_age_ms={book_age}, state_age_ms={state_age}, max={max_evidence_age_ms}"
        )

    volatility = float(state.vol_30s)
    if not math.isfinite(volatility) or volatility <= 0:
        volatility = float(state.vol_120s)
    if not math.isfinite(volatility) or volatility <= 0:
        raise ValueError("BTC state does not contain positive causal volatility")

    rows: list[dict[str, object]] = []
    skipped_missing_books = 0
    skipped_empty_books = 0
    for market in markets:
        duration = {300: "5m", 900: "15m"}.get(int(market.duration_seconds))
        if duration is None:
            continue
        boundary_ms = int(market.open_epoch_seconds) * 1_000
        if boundary_ms not in state.strikes:
            raise ValueError(f"missing exact strike for {market.condition_id} at boundary {boundary_ms}")
        yes_book = books.get(market.yes_token_id)
        no_book = books.get(market.no_token_id)
        if yes_book is None or no_book is None:
            skipped_missing_books += 1
            continue
        if yes_book.condition_id != market.condition_id or no_book.condition_id != market.condition_id:
            raise ValueError(f"book condition mismatch for {market.condition_id}")
        if yes_book.best_ask is None or no_book.best_ask is None:
            skipped_empty_books += 1
            continue
        close_ts = int(market.open_epoch_seconds) + int(market.duration_seconds)
        tau_s = (close_ts * 1_000 - decision_ts_ms) / 1_000.0
        if tau_s <= 0:
            continue
        strike = float(state.strikes[boundary_ms])
        fair, uncertainty, z_moneyness = policy.fair_yes(
            spot=float(state.spot),
            strike=strike,
            tau_s=tau_s,
            volatility_per_s=volatility,
            horizon_s=int(market.duration_seconds),
        )
        rows.append(
            {
                "condition_id": market.condition_id,
                "duration": duration,
                "close_ts": close_ts,
                "ts_ms": decision_ts_ms,
                "strike": strike,
                "yes_token_id": market.yes_token_id,
                "no_token_id": market.no_token_id,
                "yes_ask": float(yes_book.best_ask.price),
                "no_ask": float(no_book.best_ask.price),
                "yes_ask_size": float(yes_book.best_ask.size),
                "no_ask_size": float(no_book.best_ask.size),
                "fair_yes": fair,
                "surface_uncertainty": uncertainty,
                "resolved_yes": False,
                "tau_s": tau_s,
                "z_moneyness": z_moneyness,
                "horizon_s": int(market.duration_seconds),
                "signed_trade_flow_5s": 0.0,
            }
        )

    surface = pd.DataFrame(rows)
    if surface.empty:
        candidates = pd.DataFrame()
    else:
        candidates = select_one_candidate_per_expiry(
            generate_cross_horizon_candidates(surface, config=policy.config)
        )
    if not candidates.empty:
        for name, value in evidence_hashes.items():
            candidates[name] = value
        candidates["book_observed_ts_ms"] = book_ts
        candidates["spot_observed_ts_ms"] = int(state.observed_ts_ms)
        candidates["decision_ts_ms"] = decision_ts_ms
        candidates["fill_model"] = "public_book_arrival_shadow"
        candidates["transactionally_atomic"] = False
        candidates["future_outcomes_used"] = 0

    summary = {
        "markets_seen": len(markets),
        "surface_rows": len(surface),
        "candidates_selected": len(candidates),
        "skipped_missing_books": skipped_missing_books,
        "skipped_empty_books": skipped_empty_books,
        "decision_ts_ms": decision_ts_ms,
        "book_age_ms": book_age,
        "spot_state_age_ms": state_age,
        "policy_config_id": policy.config.config_id,
        "future_outcomes_used": 0,
        "transactionally_atomic": False,
        **evidence_hashes,
    }
    return candidates.reset_index(drop=True), summary
