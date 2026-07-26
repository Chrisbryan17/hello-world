# Digital Surface Live-Readiness Status

## Durable checkpoint

- Repository: `Chrisbryan17/hello-world`
- Branch: `digital-surface-live-readiness-20260725`
- Draft PR: #59
- Official late-favorite decision commit: `cedd659e0b573d8479932c428cd2eaf472c6bf8f`
- BTC-only v3 observer merge: `e88eada8589119baf755f0ab9f40d37160ff125a`
- BTC-only v3 runner merge: `9e794700600ba8a9173040711d09b7feb4817ff9`
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
- full official evidence artifact SHA-256: `210984541bcd64597ca48d480ad59102427f56b4ac204ab1308adf8a4f93ce5`
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

### Observer, collector, and resolver

The merged observer implements:

1. market-open-anchored signal at +210 seconds and arrival at +211 seconds;
2. frozen request-start, duration, book-age, and future-skew limits;
3. Decimal full-depth five-share FOK VWAP and per-level fee accounting;
4. adverse-move, price-limit, depth, stale, timeout, token, and lifecycle fail-closed decisions;
5. append-only candidate/capture/source-bound lifecycle records;
6. content-addressed raw public evidence and a separate manifest hash chain;
7. public Gamma market-by-slug discovery and terminal resolution;
8. public CLOB `POST /books` signal and arrival snapshots;
9. official fill P&L and terminal no-fill closure.

Observer verification:

- 22/22 behavior contracts passed;
- workflow run: `30217953678`;
- artifact ID: `8636344655`;
- artifact ZIP SHA-256: `667d7090ecfe3d174e5821af29a26fde2e18a87a50f7891cdcc49dff740f26af`;
- combined source SHA-256: `f2e086bb5e74f0343a4ea29f46ea2bf8e23062952b456303e204c6b5469b6126`.

### One-shot runner

The merged runner exposes only:

- `collect-next`;
- `resolve --condition-id`;
- `status`.

Runner verification:

- 5/5 runner contracts passed;
- workflow run: `30218421705`;
- artifact ID: `8636471934`;
- artifact ZIP SHA-256: `762294c4141c25d6dd0a1f6678e2f90795bfbecf909deaf130d3001358ca7b88`;
- combined runtime source SHA-256: `b398e7b9893170cb47ea17923448a87a10b017249a950ca670f9b09081b0d845`.

The known-fee field is now recorded for hypothetical fills even when diagnostic inferred outcomes are null. This audit correction does not change the official rejection result.

## Safety and admission boundary

- credentials used: **0**;
- authenticated requests: **0**;
- order submissions: **0**;
- live submission: **physically absent**;
- historical admission credit: **0**;
- prospective markets collected so far: **0**.

No historical result is admissible. Even a future admissible shadow report cannot enable live trading; any order submitter requires a separate reviewed release and explicit operator action.

## Next work

1. execute one credential-free `collect-next` run on a genuinely new post-cutoff BTC window;
2. preserve its append-only lifecycle, raw evidence, summaries, policy hashes, source hash, and artifact digest;
3. resolve the condition from authoritative terminal outcomes after closure;
4. repeat without policy changes for at least four untouched weekly blocks;
5. require measured fill evidence, acceptable concentration, zero unresolved states, and a positive lower confidence bound after fees and execution costs;
6. keep real-money execution physically disabled.
