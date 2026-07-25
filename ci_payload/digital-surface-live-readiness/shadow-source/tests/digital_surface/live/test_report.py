from research.digital_surface.live.report import ShadowCanaryMetrics, evaluate_shadow_admission


def test_rejects_insufficient_prospective_sample_and_weekly_evidence():
    decision = evaluate_shadow_admission(ShadowCanaryMetrics(
        markets_observed=499,
        qualified_portfolios=99,
        simulated_atomic=95,
        orphaned=5,
        unresolved_order_states=0,
        feed_outages=0,
        weekly_passes=3,
    ))
    assert decision["classification"] == "Rejected"
    assert "requires at least 500 observed markets" in decision["reasons"]
    assert "requires at least 100 qualified portfolios" in decision["reasons"]
    assert "requires four untouched weekly passes" in decision["reasons"]


def test_rejects_unresolved_orders_and_excess_orphaning():
    decision = evaluate_shadow_admission(ShadowCanaryMetrics(
        markets_observed=600,
        qualified_portfolios=120,
        simulated_atomic=100,
        orphaned=8,
        unresolved_order_states=1,
        feed_outages=0,
        weekly_passes=4,
    ))
    assert decision["classification"] == "Rejected"
    assert "unresolved order state exists" in decision["reasons"]
    assert "orphan rate exceeds 5%" in decision["reasons"]


def test_admits_only_when_every_prospective_gate_clears():
    decision = evaluate_shadow_admission(ShadowCanaryMetrics(
        markets_observed=650,
        qualified_portfolios=120,
        simulated_atomic=116,
        orphaned=4,
        unresolved_order_states=0,
        feed_outages=1,
        weekly_passes=4,
    ))
    assert decision["classification"] == "Admissible"
    assert decision["orphan_rate"] == 4 / 120
    assert decision["live_mode"] == "disabled_pending_operator_release"
