# Late-Favorite BTC/ETH Reproducibility Checkpoint v2

## Verdict

The frozen late-favorite rule now has a clean-room, hash-bound full-corpus reproducer and a complete per-market ledger. This is a successful **reproducibility checkpoint**, not strategy admission.

The exact previously reported final-test result of 2,054 BTC/ETH trades and +$139.72 is **not yet independently reproducible** because the branch does not contain the original deep-EDA source or its exact train/validation/final-test split manifest. No replacement split was tuned to force a match.

## Clean-room verification

- Workflow: `Late Favorite Repro Audit`
- Run: `30213239532`
- Source commit: `6230f9060f463b1c687be8a10201c416fd7eb178`
- Result: green
- Behavior tests: 11 passed
- Source compilation: passed
- Live-submission absence check: passed
- Full BTC/ETH ledger build: passed
- Evidence-boundary and checksum verification: passed
- GitHub artifact ZIP digest: `sha256:0cc4a640d411d3b85130c858def8a84034cf7c293d7c25af6b8a9098382c8afc`
- Deterministic tar digest: `703365cd593e8cf38f08a5af4ece1a947c2393ece68a30583b5ba357a3110cdb`

## Bound market universe

- Markets: 27,940
- Signals at second 210: 12,695
- Hypothetical five-share FOK fills after the frozen one-second latency, limit, depth, and adverse-move rules: 9,268
- Labeled fills: 8,883
- Unlabeled fills: 385
- Inferred-label win rate among labeled fills: 95.5871%
- Diagnostic inferred-label P&L at five shares: +$428.925746
- Mean diagnostic P&L: +0.9657 cents per labeled share

Asset detail:

| Asset | Markets | Signals | Fills | Labeled | Unlabeled | Inferred win rate | Diagnostic P&L at 5 shares |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | 15,682 | 6,847 | 4,844 | 4,665 | 179 | 95.9700% | +$335.294207 |
| ETH | 12,258 | 5,848 | 4,424 | 4,218 | 206 | 95.1636% | +$93.631539 |

## Cryptographic identities

- Candidate spec SHA-256: `e8f09194678ff203b9906b0462c411e327c1c1e1a57fc9e7ce1a1c77c28f7cd3`
- Source module SHA-256: `9fee982c6934614ecef52679b49f81826f34f41e0a04fc7e251856ee79b47237`
- All-condition-set SHA-256: `ed051d81e9d5d4aa57cd598205b34cdd0af804f5fa0ddec45aeca4bb85b919a1`
- Filled-condition-set SHA-256: `bf276fbce187d9651d56ecae976520d4251140c1d5b0d440696c5d077838a67a`
- BTC filled set: `64ba2f09192a5dca87b18dd466b7d7d6b8e48c6f7629272bddeb10a5090a8f88`
- ETH filled set: `8fce860d459b12357547283181e7bb5b570cc4e92cffb403d6b2d9ceca9df5b2`

Output file checksums:

- `AUDIT.json`: `eb05935840395e34601d95954a20a167f16b431cde83beeb463ceba10ebb0c7c`
- `REPORT.md`: `290bf383f91ed01debfe3fe0a910dadcbaef433ff68e17d3753be971344ea9e5`
- `eligible_trades.csv.gz`: `3438e739c24bc4523e36b439c2fad0804d7018f11082787ce490b3abc8b5915a`
- `market_ledger.csv.gz`: `2e46aa667ddae8a0c5ea24d3329b4b0bba084fcb90dab760dca349e4ca154c62`

## Data-quality finding

The first green artifact exposed 385 filled rows with no inferred terminal label. The v2 audit now reports labeled and unlabeled denominators separately and tests that they reconcile exactly to total fills. Diagnostic P&L and win rate use only labeled fills.

Those 385 rows are not assumed winners, losers, or unresolved Polymarket settlements. They must be transferred to authoritative terminal outcomes or explicitly classified as unavailable.

## Reproducibility limitations

1. Official outcomes used: **0**.
2. The dataset outcomes remain inferred and cannot count toward admission.
3. Exact deep-EDA split boundaries and the original implementation source were not preserved.
4. This v2 reproducer selects the favorite as the side with the higher signal ask. That is consistent with the frozen `signal_ask` description but is not proven byte-for-byte identical to the missing original deep-EDA implementation.
5. The post-inspection adverse-move cancel remains a diagnostic/prospective rule; it does not inherit untouched holdout status.
6. Top-of-book depth still does not establish live queue position or realized FOK execution.
7. Live submission remains physically absent.

## Next bounded job

Transfer the hash-bound filled condition set to official Polymarket terminal outcomes, preserve every lookup response and failure classification, and recompute the same fixed-rule ledger without modifying thresholds, assets, timing, fees, latency, depth, or cancel logic.
