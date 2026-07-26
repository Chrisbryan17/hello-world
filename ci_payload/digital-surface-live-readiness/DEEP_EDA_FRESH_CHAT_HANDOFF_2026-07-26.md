# Polymarket 5-Minute Crypto HFT — Fresh-Chat Handoff

Created 2026-07-26 after the prior chat reached its length limit and the next message crashed.

## Paste into the fresh chat

Continue the Polymarket 5-minute crypto high-frequency research project from this handoff.

Start by restoring and verifying the newest remote state:

- Active research repo: `Chrisbryan17/hello-world`
- Active branch: `digital-surface-live-readiness-20260725`
- Draft PR: `#59`
- Last verified research head before this handoff: `f8750201dc421b1c0e543712d8f207ef76705eaf`
- Latest verified commit message: `research: freeze diagnostic BTC ETH favorite candidate`
- Do not assume the branch has not advanced. Inspect PR #59 and branch history first.
- Read immediately:
  - `ci_payload/digital-surface-live-readiness/deep-favorite-eda-v2/REPORT.md`
  - `ci_payload/digital-surface-live-readiness/deep-favorite-eda-v2/CANDIDATE_SPEC.json`
  - `ci_payload/digital-surface-live-readiness/STATUS.md`

The strategic instruction is explicit: stop centering work on harness construction. Perform deep, microstructure-first EDA like a top Jane Street quant. Focus on event-time alignment, lead-lag discovery, conditional edge decay, fillability, regime clustering, strict walk-forward falsification, executable prices, and multiple-testing controls. Back up every material result to GitHub. Do not manufacture a passing strategy by leaking holdouts.

The initial deep EDA is already complete. Do not redo it from scratch. It found a leading diagnostic candidate:

- name: `late_favorite_btc_eth_v2_diagnostic`
- assets: BTC and ETH
- entry: 210 seconds into the 5-minute window
- favorite signal ask: at least $0.85
- latency: 1 second
- FOK limit: signal ask
- size: 5 shares
- fee: `0.07*p*(1-p)` per share
- hold: settlement
- maximum one position per asset per window and two total positions per window
- diagnostic cancel: cancel when arrival ask is more than $0.01 below signal ask
- live submission: disabled
- status: profitable diagnostic candidate requiring new official-label prospective validation

Next valid work:

1. verify and preserve the latest branch/artifacts;
2. audit the deep EDA result for reproducibility and contamination;
3. transfer the frozen BTC/ETH candidate to official Polymarket terminal outcomes;
4. run an append-only prospective observer recording every eligible and ineligible BTC/ETH window, signal/no-signal, signal ask, 1-second arrival book, full depth, hypothetical FOK result, adverse-move cancel, official outcome, fees, slippage, and per-window exposure;
5. run at least four untouched weekly prospective blocks;
6. continue deeper EDA in parallel, but version every new hypothesis discovered using inspected data;
7. keep live order submission physically absent.

For every meaningful pass: tests -> source/config/results/audit files -> atomic commit -> push -> fetch/read-back -> SHA/blob verification -> next experiment.

## Distinguish the two strategy tracks

### A. Original 5m-vs-15m digital-surface sleeve

After official-resolution correction and four untouched historical folds, this sleeve was honestly **Rejected**. Those weeks are diagnostic and may never count as prospective evidence.

Execution diagnosis across 224 portfolios / 448 legs:

- insufficient post-arrival tape: 186
- ask above frozen limit: 114
- missing post-arrival book: 110
- filled: 34
- insufficient displayed depth: 4

Tape-confirmed replay produced 8 paired fills. Diagnostic book-arrival replay estimated 62 paired-crossable portfolios with fold counts `[11,17,29,5]`. This is not transactionally atomic and not live truth.

### B. Deep late-favorite candidate

The broader EDA corpus contained 89,233 markets and approximately 26.77M one-second observations across BTC, ETH, SOL, XRP, DOGE, BNB, and HYPE.

The strongest candidate was not BTC-to-alt lead-lag. It was late-window settlement favorite, with BTC+ETH the statistically credible core.

## Deep EDA evidence

All-seven strict walk-forward:

- train: 38 days, 18,493 trades, +$1,088.33 at five shares, daily t=5.91
- validation: 14 days, 6,819 trades, +$395.42, daily t=5.35, every day positive
- final chronological test: 12 days, 6,769 trades, +$249.11, 24.67 trades/hour, daily t=1.67
- 210s / 85c ranked #1 of 982 eligible configurations by validation daily t
- tested latency 0-3 seconds remained positive in train and validation

BTC+ETH core:

- 2,054 final-test trades
- +$139.72 at five shares
- 95.67% win rate
- 1.3604 cents mean P&L/share after fee
- daily t=3.85
- exact one-sided day-level sign-flip p=0.00244
- 95% day-bootstrap mean interval: +$5.84 to +$17.13/day at five shares
- BTC and ETH survive BH control at 5% across seven assets

Adverse selection:

- favorite ask falling by >=$0.02 during the 1-second latency produced 288 trades, 84.38% win rate, and -$48.44
- $0.01 improvement remained positive
- therefore the prospective rule is cancel when `execution_ask < signal_ask - 0.01`
- this rule was found after final-test inspection and has no untouched status

Cross-asset risk:

- 38.66% of losses occurred in windows with at least two simultaneous losses
- BTC/ETH loss correlation: 0.559
- when BTC won, ETH won 98.39% of simultaneous windows
- when BTC lost, ETH won only 38.46%
- all-seven top-two-day P&L concentration: 66.62%
- BTC+ETH concentration: 38.02%
- cap by five-minute window, not only by asset

Capacity/cost:

- BTC+ETH break-even additional cost: 1.3604 cents/share
- all-seven break-even additional cost: 0.7360 cents/share
- at 100 shares, 56.13% of BTC/ETH test signals showed enough top-of-book size and stayed positive, but tail risk scaled sharply
- 250+ shares deteriorated
- top-of-book size is not a live capacity guarantee

## Non-negotiable uncertainty

1. Dataset outcomes were inferred from the final recorded book, not authoritative settlement.
2. Only 28 falsely labeled winners erase BTC+ETH final-test profit.
3. Official terminal-outcome validation is mandatory.
4. BTC/ETH selection and the adverse-move cancel were learned after final-test inspection.
5. Top-of-book depth does not model queue position.
6. Two separately submitted FOK orders are not transactionally atomic.
7. Previously inspected markets cannot count prospectively.
8. Policy, source, ledger, and reports must be hash-bound.
9. Real-money execution remains absent.

## Existing infrastructure to reuse

PR #59 already contains checksum-pinned recovery material for:

- official outcome/source correction;
- slug/timestamp/universe/asset merge fixes;
- deterministic archives;
- leg-level execution attribution;
- tape-confirmed and book-arrival replay;
- Decimal tick quantization;
- shadow-only pair preparation;
- stale data, loss, orphan, unresolved-order, token, depth, limit, expiry, and ambiguous-state kill switches;
- append-only prospective market, book, BTC-state, and report chains;
- historical contamination rejection;
- public Gamma market discovery;
- public CLOB book collection;
- public Binance spot/strike/volatility collection;
- causal prospective signal adapter;
- live startup physically disabled.

## Raw inputs from prior chat

- `polymarket-5m-btc(1).zip`
- `polymarket-5m-eth.zip`
- `polymarket-5m-sol(1).zip`
- `polymarket-5m-xrp.zip`
- `polymarket-5m-doge.zip`
- `polymarket-5m-bnb.zip`
- `polymarket-5m-hype.zip`
- `Branch · BTC Lead-Lag Strategy.txt`
- `Transcript.txt`

The new filesystem is temporary. Re-upload raw ZIPs only when needed; durable state belongs on GitHub.

## Required deep EDA continuation

Continue all of these, using executable bid/ask economics:

1. common-factor-residual cross-asset lead-lag at 1,2,3,5,10,15,30 seconds;
2. same-market complement arbitrage with both-leg fees/depth/latency;
3. microstructure markouts from spread, imbalance, depth curvature, update intensity, replenishment, and time-to-expiry;
4. regime clustering by volatility, cross-asset correlation, liquidity, time-of-day, favorite price, expiry, and crash state;
5. purged walk-forward, embargo, block bootstrap, sign-flip, BH/FWER, White Reality Check/SPA, PBO, deflated Sharpe, leave-day/regime-out, and concentration diagnostics.

Any candidate discovered using an inspected final test becomes a new prospective version and cannot inherit old holdout status.

## Admission standard

The BTC/ETH candidate needs:

- authoritative outcomes;
- four untouched weekly blocks;
- positive P&L after measured fees/slippage;
- positive lower confidence bound;
- no extreme day concentration;
- stable BTC/ETH performance;
- acceptable common-factor crash exposure;
- measured fill/capacity;
- zero unresolved states;
- frozen policy throughout;
- complete append-only verification.

Even then, live requires a separate reviewed and explicitly armed release.

## Recovery commands

```bash
git clone https://github.com/Chrisbryan17/hello-world.git
cd hello-world
git fetch --all --prune
git checkout digital-surface-live-readiness-20260725
git pull --ff-only
git rev-parse HEAD
git status --short --branch
git log --oneline --decorate -30

sed -n '1,240p' ci_payload/digital-surface-live-readiness/deep-favorite-eda-v2/REPORT.md
cat ci_payload/digital-surface-live-readiness/deep-favorite-eda-v2/CANDIDATE_SPEC.json
sed -n '1,220p' ci_payload/digital-surface-live-readiness/STATUS.md
find ci_payload/digital-surface-live-readiness -maxdepth 4 -type f | sort
```

Original authoritative provenance when needed:

```bash
git clone https://github.com/Chrisbryan17/trading-tools.git ../trading-tools
cd ../trading-tools
git fetch --all --prune
git checkout digital-surface-arbitrage-implementation-20260723
git log --oneline --decorate -30
```

## What not to do

- do not rebuild generic harnesses;
- do not tune known historical folds until they pass;
- do not use midpoint fills;
- do not ignore fees;
- do not fit a fine lookup table to inspected price buckets;
- do not call correlated BTC/ETH independent diversification;
- do not increase size from top-of-book alone;
- do not count diagnostic markets prospectively;
- do not add credentials or an order submitter;
- do not claim profitability before official-label transfer and prospective evidence;
- do not start the next experiment before committing, pushing, reading back, and verifying the current one.

## Definition of success for the next chat

- restore the actual latest PR #59 head;
- confirm it is newer than or equal to `f875020…`;
- avoid repeating initial harness work;
- reproduce/audit the deep-favorite result;
- begin official-label transfer or genuine prospective collection;
- produce a decision-useful new EDA result or falsification;
- push source, tests, configs, results, and audit metadata;
- keep live execution disabled.

The goal is not to force a pass. The goal is to find a genuine executable edge or falsify this candidate quickly without fooling ourselves.
