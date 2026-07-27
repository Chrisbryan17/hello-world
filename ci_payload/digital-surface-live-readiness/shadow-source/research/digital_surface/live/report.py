from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ShadowCanaryMetrics:
    markets_observed: int
    qualified_portfolios: int
    simulated_atomic: int
    orphaned: int
    unresolved_order_states: int
    feed_outages: int
    weekly_passes: int


def evaluate_shadow_admission(metrics: ShadowCanaryMetrics) -> dict[str, Any]:
    values = asdict(metrics)
    if any(int(value) < 0 for value in values.values()):
        raise ValueError("shadow canary metrics must be non-negative")
    attempts = int(metrics.simulated_atomic) + int(metrics.orphaned)
    orphan_rate = float(metrics.orphaned / attempts) if attempts else 0.0
    reasons: list[str] = []
    if metrics.markets_observed < 500:
        reasons.append("requires at least 500 observed markets")
    if metrics.qualified_portfolios < 100:
        reasons.append("requires at least 100 qualified portfolios")
    if metrics.weekly_passes < 4:
        reasons.append("requires four untouched weekly passes")
    if metrics.unresolved_order_states:
        reasons.append("unresolved order state exists")
    if orphan_rate > 0.05:
        reasons.append("orphan rate exceeds 5%")
    classification = "Admissible" if not reasons else "Rejected"
    return {
        "classification": classification,
        "reasons": reasons,
        "markets_observed": int(metrics.markets_observed),
        "qualified_portfolios": int(metrics.qualified_portfolios),
        "simulated_atomic": int(metrics.simulated_atomic),
        "orphaned": int(metrics.orphaned),
        "orphan_rate": orphan_rate,
        "unresolved_order_states": int(metrics.unresolved_order_states),
        "feed_outages": int(metrics.feed_outages),
        "weekly_passes": int(metrics.weekly_passes),
        # Even an admissible research report cannot arm the current build.
        "live_mode": "disabled_pending_operator_release",
    }
