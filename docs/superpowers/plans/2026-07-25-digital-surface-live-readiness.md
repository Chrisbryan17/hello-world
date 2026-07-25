# Digital Surface Live-Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Diagnose and remove legitimate execution bottlenecks, create new uncontaminated acceptance folds, and build a fail-closed Polymarket CLOB V2 shadow bot that cannot submit real orders by default.

**Architecture:** Keep the existing causal surface, candidate, execution, portfolio, and validation modules as the research core. Add focused diagnostics and liquidity-policy modules, then add a separate live package whose only dependency on research is an immutable `TradeIntent` interface. Historical known weeks remain diagnostic; new prospective weeks alone determine admission.

**Tech Stack:** Python 3.11, pandas 2.2.3, NumPy 2.2.6, SciPy 1.15.3, scikit-learn 1.6.1, PyArrow 19.0.1, pytest 8.3.5, Polymarket CLOB V2 REST/WebSocket APIs, GitHub Actions.

## Global Constraints

- Preserve the 99% official-resolution agreement gate and 100% coverage requirement.
- Never tune against the four already observed Kinzik test weeks.
- Keep all execution evidence post-arrival and strictly causal.
- Do not claim two independent market orders are atomic.
- Default `TRADING_MODE` is `shadow`; CI may not set it to `live`.
- No secret, private key, API key, passphrase, or wallet material may be committed.
- Commit every meaningful diagnostic, test, fix, workflow, and result checkpoint.

---

### Task 1: Deterministic execution failure attribution

**Files:**
- Create: `research/digital_surface/diagnostics.py`
- Create: `tests/digital_surface/test_diagnostics.py`
- Modify: `research/digital_surface/run_research.py`
- Create: `.github/workflows/digital-surface-execution-diagnostics.yml`

**Interfaces:**
- Consumes: `candidate_ledger.parquet`, `execution_ledger.parquet`, and existing candidate/execution columns.
- Produces: `attribute_execution_failures(candidates: pd.DataFrame, executions: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]` and artifacts `execution_failure_attribution.csv` plus `EXECUTION_DIAGNOSTICS.json`.

- [ ] **Step 1: Write failing tests**

```python
def test_attributes_each_leg_to_one_terminal_reason():
    candidates = pd.DataFrame([
        {"candidate_id": "a", "tau_s": 30.0, "expected_cost": 1.05, "theoretical_edge": 0.03},
        {"candidate_id": "b", "tau_s": 12.0, "expected_cost": 1.02, "theoretical_edge": 0.04},
    ])
    executions = pd.DataFrame([
        {
            "candidate_id": "a",
            "atomic": False,
            "low_book_ts_ms": np.nan,
            "low_book_crossable": False,
            "low_book_full": False,
            "low_tape_full": False,
            "high_book_ts_ms": 2,
            "high_book_crossable": True,
            "high_book_full": True,
            "high_tape_full": False,
        },
        {
            "candidate_id": "b",
            "atomic": True,
            "low_book_ts_ms": 2,
            "low_book_crossable": True,
            "low_book_full": True,
            "low_tape_full": True,
            "high_book_ts_ms": 2,
            "high_book_crossable": True,
            "high_book_full": True,
            "high_tape_full": True,
        },
    ])
    ledger, summary = attribute_execution_failures(candidates, executions)
    assert ledger.set_index(["candidate_id", "leg"]).loc[("a", "low"), "reason"] == "missing_post_arrival_book"
    assert ledger.set_index(["candidate_id", "leg"]).loc[("a", "high"), "reason"] == "insufficient_post_arrival_tape"
    assert ledger[ledger["candidate_id"] == "b"]["reason"].tolist() == ["filled", "filled"]
    assert summary["legs_attributed"] == 4
```

- [ ] **Step 2: Run the test and verify RED**

Run: `PYTHONPATH=. pytest tests/digital_surface/test_diagnostics.py -v`
Expected: FAIL because `research.digital_surface.diagnostics` does not exist.

- [ ] **Step 3: Implement one-reason precedence**

Reason precedence per leg:

1. `missing_post_arrival_book`
2. `ask_above_limit`
3. `insufficient_displayed_depth`
4. `insufficient_post_arrival_tape`
5. `filled`

Join candidates one-to-one to executions, emit exactly two rows per candidate, assert complete attribution, and summarize by week, leg, reason, tau bucket, expected-cost bucket, edge bucket, and requested shares.

- [ ] **Step 4: Run focused and full tests**

Run:

```bash
PYTHONPATH=. pytest tests/digital_surface/test_diagnostics.py -v
PYTHONPATH=. pytest tests/digital_surface -q
```

Expected: focused PASS and exactly 29 existing tests plus the new diagnostics tests all PASS.

- [ ] **Step 5: Wire diagnostics into `run_research.py`**

Write the CSV and JSON only after candidate and execution ledgers exist. Include their hashes in `SHA256SUMS.json` and `MANIFEST.json`.

- [ ] **Step 6: Add clean-room workflow and commit**

The workflow reconstructs the checksum-pinned v5 source, applies the diagnostics patch, runs tests, runs research, validates that every candidate produces two attributed legs, archives results, and uploads them.

Commit: `feat: attribute every candidate leg execution failure`

---

### Task 2: Validation-only liquidity sizing policy

**Files:**
- Create: `research/digital_surface/liquidity.py`
- Create: `tests/digital_surface/test_liquidity.py`
- Modify: `research/digital_surface/execution.py`
- Modify: `research/digital_surface/validation.py`

**Interfaces:**
- Produces: `LiquidityPolicy(size_tiers: tuple[float, ...], min_joint_fill_probability: float)` and `fit_liquidity_policy(validation_candidates, validation_executions) -> LiquidityPolicy`.
- `replay_atomic_fok` accepts either scalar `shares` or a candidate column `requested_shares`.

- [ ] **Step 1: Write failing tests**

Test that size is selected only from supplied validation rows, never from test rows, and that lower size can convert a displayed-depth or tape failure into an atomic fill without changing timestamps or prices.

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=. pytest tests/digital_surface/test_liquidity.py -v`
Expected: FAIL because the policy module and candidate-sized replay do not exist.

- [ ] **Step 3: Implement minimal deterministic policy**

Candidate size tiers are exactly `(1.0, 2.0, 3.0, 5.0)`. Estimate joint empirical fill probability by causal feature bins from validation data. Select the largest tier with Wilson 95% lower bound at least `0.80`; otherwise reject the candidate.

- [ ] **Step 4: Verify focused and full suites**

Run focused tests, then the complete suite. Do not inspect held-out fold outcomes during policy selection.

- [ ] **Step 5: Commit**

Commit: `feat: fit validation-only liquidity size tiers`

---

### Task 3: Candidate selection that optimizes completed portfolios, not raw edge

**Files:**
- Modify: `research/digital_surface/candidates.py`
- Modify: `research/digital_surface/validation.py`
- Test: `tests/digital_surface/test_candidates.py`
- Test: `tests/digital_surface/test_validation.py`

**Interfaces:**
- Add candidate columns `joint_fill_score`, `net_edge_after_orphan_risk`, and `requested_shares`.
- `select_one_candidate_per_expiry` ranks first causal trigger satisfying the frozen liquidity policy; it never chooses a later timestamp based on realized fill.

- [ ] **Step 1: Write a failing causal-selection regression**

Construct two timestamps for one expiry where the early candidate fails the frozen policy and the later candidate passes it. Assert the later candidate is selected. Construct a second case where both pass and assert the first timestamp remains selected.

- [ ] **Step 2: Verify RED**

Run the focused candidate test and confirm the missing-policy behavior causes the failure.

- [ ] **Step 3: Implement minimal policy-aware filtering**

Apply only frozen, pre-test liquidity estimates. Do not use realized test execution fields.

- [ ] **Step 4: Run all tests and commit**

Commit: `feat: select first liquidity-qualified surface portfolio`

---

### Task 4: Contamination guard and prospective fold ledger

**Files:**
- Create: `research/digital_surface/prospective.py`
- Create: `tests/digital_surface/test_prospective.py`
- Modify: `research/digital_surface/run_research.py`

**Interfaces:**
- Produces `ProspectiveLedger` with immutable market IDs, first-seen timestamps, policy hash, source hashes, and result state.
- Refuses to classify any week whose market IDs appeared in prior diagnostics or policy fitting.

- [ ] **Step 1: Write failing contamination tests**

Test that a market ID present in `diagnostic_market_ids` causes `ProspectiveContaminationError`, while a genuinely new market is accepted.

- [ ] **Step 2: Verify RED**

Run the focused test and confirm the missing guard is the failure.

- [ ] **Step 3: Implement append-only ledger**

Use canonical JSON, SHA-256 chaining, and explicit policy/source hashes. No row may be edited after observation.

- [ ] **Step 4: Run all tests and commit**

Commit: `feat: enforce uncontaminated prospective fold ledger`

---

### Task 5: CLOB V2 shadow adapter and fail-closed risk controls

**Files:**
- Create: `research/digital_surface/live/__init__.py`
- Create: `research/digital_surface/live/config.py`
- Create: `research/digital_surface/live/intents.py`
- Create: `research/digital_surface/live/market_stream.py`
- Create: `research/digital_surface/live/order_gateway.py`
- Create: `research/digital_surface/live/risk.py`
- Create: `research/digital_surface/live/runner.py`
- Create: `tests/digital_surface/live/test_config.py`
- Create: `tests/digital_surface/live/test_risk.py`
- Create: `tests/digital_surface/live/test_gateway.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class TradeIntent:
    condition_id_low: str
    token_id_low_yes: str
    condition_id_high: str
    token_id_high_no: str
    max_low_price: float
    max_high_price: float
    shares: float
    decision_ts_ms: int
    expires_ts_ms: int

@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str
```

- [ ] **Step 1: Write failing default-shadow and risk-limit tests**

Assert missing `TRADING_MODE` resolves to `shadow`; any live mode without an explicit arm token fails startup; stale books, heartbeat loss, daily-loss breach, unresolved prior orders, or orphan exposure block new intents.

- [ ] **Step 2: Verify RED**

Run the live tests and confirm imports or required behavior fail.

- [ ] **Step 3: Implement config and risk kernel**

No network call exists in the risk kernel. It is deterministic and independently tested.

- [ ] **Step 4: Implement shadow gateway**

The shadow gateway records the exact signed-order parameters it would submit but never accesses credentials or sends HTTP requests.

- [ ] **Step 5: Implement authenticated gateway behind explicit arm gate**

Use the current CLOB V2 SDK/API shape, batch up to two pre-signed FOK orders to reduce skew, reconcile every response and user-WebSocket event, and immediately cancel open orders on ambiguity. Document that batch posting is not atomic.

- [ ] **Step 6: Run tests and commit**

Commit: `feat: add fail-closed Polymarket shadow execution service`

---

### Task 6: Shadow canary and final admission workflow

**Files:**
- Create: `.github/workflows/digital-surface-shadow-canary.yml`
- Create: `research/digital_surface/live/report.py`
- Create: `tests/digital_surface/live/test_report.py`

**Interfaces:**
- Produces a signed/hash-chained shadow report with market count, qualified intents, simulated paired fills, orphan rate, feed outages, order-state ambiguities, and risk-gate rejections.

- [ ] **Step 1: Write failing report-gate tests**

Assert admission fails below 500 observed markets, below 100 qualified portfolios, with any unresolved order state, above 5% orphan rate, or with fewer than four untouched weekly passes.

- [ ] **Step 2: Verify RED**

Run focused tests and confirm report-gate behavior is absent.

- [ ] **Step 3: Implement report and workflow**

The workflow runs on a schedule in shadow mode only, persists append-only artifacts, and never has access to live credentials.

- [ ] **Step 4: Run full suite and commit**

Commit: `ci: add prospective shadow canary admission gate`

---

### Task 7: Verification and authoritative promotion

**Files:**
- Modify: PR description and handoff documentation.
- No production behavior changes.

- [ ] **Step 1: Run exact source reconstruction and full suite**

Expected: all tests pass and collected count matches the manifest.

- [ ] **Step 2: Verify prospective artifacts**

Verify outer artifact digest, deterministic TAR sidecars, every internal SHA-256 entry, source hashes, policy hash, chronological fold identity, and live-mode-disabled evidence.

- [ ] **Step 3: Promote atomically**

Create one authoritative Git tree and commit containing the exact verified source. Fast-forward the isolated authoritative branch once and read critical blobs back.

- [ ] **Step 4: Final classification**

Classify `Rejected`, `Exploratory`, or `Admissible` strictly from the unchanged gates. Real-money mode remains disabled unless `Admissible` and the operator explicitly arms it.

Commit: `chore: promote verified digital-surface live-readiness checkpoint`
