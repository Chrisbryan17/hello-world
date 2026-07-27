import json

import pytest

from research.digital_surface.live.report import ShadowCanaryMetrics
from research.digital_surface.live.report_chain import ShadowReportIntegrityError, ShadowReportLedger


def metrics(markets=650, qualified=120, atomic=116, orphaned=4, unresolved=0, weeks=4):
    return ShadowCanaryMetrics(
        markets_observed=markets,
        qualified_portfolios=qualified,
        simulated_atomic=atomic,
        orphaned=orphaned,
        unresolved_order_states=unresolved,
        feed_outages=0,
        weekly_passes=weeks,
    )


def test_appends_hash_chained_reports_bound_to_policy_source_and_prospective_head(tmp_path):
    path = tmp_path / "reports.jsonl"
    ledger = ShadowReportLedger(path)
    first = ledger.append(
        generated_ts_ms=100,
        metrics=metrics(),
        policy_sha256="1" * 64,
        source_sha256="2" * 64,
        prospective_head_sha256="3" * 64,
    )
    second = ledger.append(
        generated_ts_ms=200,
        metrics=metrics(markets=700),
        policy_sha256="1" * 64,
        source_sha256="2" * 64,
        prospective_head_sha256="4" * 64,
    )
    assert first["decision"]["classification"] == "Admissible"
    assert first["decision"]["live_mode"] == "disabled_pending_operator_release"
    assert second["previous_report_hash"] == first["report_hash"]
    reloaded = ShadowReportLedger(path)
    assert reloaded.head_hash == second["report_hash"]
    assert len(reloaded.rows) == 2


def test_recomputes_decision_and_detects_tampering(tmp_path):
    path = tmp_path / "reports.jsonl"
    ledger = ShadowReportLedger(path)
    ledger.append(
        generated_ts_ms=100,
        metrics=metrics(markets=499),
        policy_sha256="1" * 64,
        source_sha256="2" * 64,
        prospective_head_sha256="3" * 64,
    )
    row = json.loads(path.read_text())
    row["decision"]["classification"] = "Admissible"
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ShadowReportIntegrityError, match="report hash mismatch|decision mismatch"):
        ShadowReportLedger(path)


def test_rejects_unbound_or_invalid_digests(tmp_path):
    ledger = ShadowReportLedger(tmp_path / "reports.jsonl")
    with pytest.raises(ValueError, match="prospective_head_sha256"):
        ledger.append(
            generated_ts_ms=100,
            metrics=metrics(),
            policy_sha256="1" * 64,
            source_sha256="2" * 64,
            prospective_head_sha256="not-a-hash",
        )
