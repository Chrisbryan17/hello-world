# Digital Surface Live-Readiness Status

## Durable checkpoint

- Repository: `Chrisbryan17/hello-world`
- Branch: `digital-surface-live-readiness-20260725`
- Draft PR: #59
- Official late-favorite decision commit: `cedd659e0b573d8479932c428cd2eaf472c6bf8f`
- First BTC-only prospective checkpoint merge: `f76097ef513a2e70881e7624cd8d9a60d12a642b`
- Real-money execution: **physically disabled**

## Historical research verdicts

### Original 5m-vs-15m digital-surface sleeve

The official-resolution source gate and all four historical transfer folds completed, but the frozen sleeve remained **Rejected**. Those folds are diagnostic only and may never count toward prospective admission.

### Late-favorite BTC/ETH candidate

The immutable 9,268-fill set was transferred to authoritative Polymarket terminal outcomes with 100% coverage. The candidate is **Rejected / falsified**:

- official win rate: 94.3893%;
- official mean P&L/share: -$0.00127314;
- official P&L at five shares: -$59.00;
- BTC: +$64.00, but its daily confidence interval crosses zero;
- ETH: -$123.00.

The earlier +$428.93 inferred-label result was biased by 385 null-labeled fills. Official resolution showed that excluded cohort had only 67.53% wins and lost $472.92. Nine direct label disagreements changed comparable P&L by only -$15.00; the material defect was non-random label-availability censoring.

Authoritative decision evidence:

- `ci_payload/digital-surface-live-readiness/late-favorite-official-decision-v1/CHECKPOINT.md`
- filled condition-set SHA-256: `bf276fbce187d9651d56ecae976520d4251140c1d5b0d440696c5d077838a67a`
- full official evidence artifact SHA-256: `210984541bcd64597ca48d480ad59102427f56b4ac204ab1308ad8f8a4f93ce5`
- compact derivative artifact SHA-256: `fb5dfb4621caa8b62ebaefc0b5c15d04619f773c3686cc4f088767ca023416b9`

## BTC-only v3 prospective shadow track

BTC-only is a **marginal post-hoc lead**, not a historical pass. It has zero inherited validation or admission credit.

### Frozen candidate and capture boundaries

- candidate: `late_favorite_btc_only_v3_prospective_shadow`
- candidate policy SHA-256: `82b923b0d4034d801156b77a213db6084be719f27491478247e5354ea93e92ba`
- candidate freeze: `2026-07-26T19:11:11Z`
- capture policy SHA-256: `888810ae61a0ab3e067c68850faeba5f2709a57bb69ef0c2ad708e128b311edc`
- effective capture cutoff: `2026-07-26T19:35:21Z`
- only markets opening strictly after the effective capture cutoff may count.

### Observer, collector, resolver, and CLI

The merged observer implements:

1. market-open-anchored signal at +210 seconds and arrival at +211 seconds;
2. frozen request-start, duration, book-age, and future-skew limits;
3. Decimal full-depth five-share FOK VWAP and per-level fee accounting;
4. adverse-move, price-limit, depth, stale, timeout, token, and lifecycle fail-closed decisions;
5. append-only candidate/capture/source-bound lifecycle records;
6. content-addressed raw public evidence and a separate manifest hash chain;
7. public Gamma discovery and cache-busted terminal resolution;
8. public CLOB `POST /books` signal and arrival snapshots;
9. official fill P&L and terminal no-fill closure;
10. one-shot `capture` and `resolve` command boundaries.

Current observer verification:

- 25/25 behavior contracts passed;
- workflow run: `30220717065`;
- artifact ID: `8637116192`;
- artifact ZIP SHA-256: `172ef7213e7860a8bee00db5e0a79d66495d31199cde85d39dcfef201f14de86`;
- combined frozen source SHA-256: `ce477bf97589997899c91ad22af9025de521520f8ee7aa46a21b50a313958bd7`;
- resolver source SHA-256: `90c417be653f5f0fdf22dfc7d4e20168869594a021fc3229d87b7f203bc9dc77`.

### First complete prospective observation

Checkpoint:

- `ci_payload/digital-surface-live-readiness/late-favorite-btc-only-v3/prospective-run-v1/CHECKPOINT.md`
- workflow run: `30220121542`;
- evidence artifact ID: `8637040765`;
- evidence ZIP SHA-256: `8d00c88d6046806a2abc07f43da8b2f0ab08449890ee8a7f9e1f7071b92c4e21`.

Result:

- market: `btc-updown-5m-1785099600`, 2026-07-26 21:00–21:05 UTC;
- selected side: Up;
- signal ask: $0.98;
- arrival best ask: $0.99;
- frozen decision: `no_fill_ask_above_limit`;
- official outcome: Up;
- hypothetical fill: no;
- P&L: not applicable.

The complete lifecycle and raw-evidence chains were independently verified. Twenty non-terminal Gamma payloads were followed by one terminal `[1,0]` payload. The one-cent adverse price move was correctly rejected rather than chased.

## Safety and admission boundary

- credentials used: **0**;
- authenticated requests: **0**;
- order submissions: **0**;
- live submission: **physically absent**;
- historical admission credit: **0**;
- prospective markets observed: **1 / 500 minimum**;
- hypothetical FOK fills: **0 / 100 minimum**;
- complete untouched weekly blocks: **0 / 4 minimum**.

No historical result is admissible. This single no-fill observation is valid prospective evidence but cannot support admission. Even a future admissible shadow report cannot enable live trading; any order submitter requires a separate reviewed release and explicit operator action.

## Next work

1. continue credential-free collection of every eligible BTC five-minute market, including no-signal and no-fill cases;
2. preserve append-only lifecycle and raw evidence with authoritative terminal outcomes;
3. make no threshold or policy changes during the prospective block;
4. accumulate at least 500 observed markets, 100 hypothetical FOK fills, and four untouched weekly blocks;
5. require measured fill evidence, acceptable concentration, zero unresolved states, and a positive lower confidence bound after fees and execution costs;
6. keep real-money execution physically disabled.
