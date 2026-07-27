# Late-Favorite BTC/ETH Official-Outcome Decision Checkpoint v1

## Verdict

The frozen `late_favorite_btc_eth_v2_diagnostic` candidate is **Rejected / falsified** after transfer to authoritative Polymarket terminal outcomes.

- Frozen fills: **9,268**
- Official coverage: **100.00%**
- Official win rate: **94.3893%**
- Official mean P&L/share: **-$0.00127314**
- Official P&L at five shares: **-$59.00**
- Additional-cost headroom: **negative**; even zero additional slippage is unprofitable.

No threshold, asset, timing, latency, fee, depth, FOK, or adverse-move rule was changed during transfer. Real-money submission remains physically absent.

## Why the diagnostic result reversed

The earlier inferred-label diagnostic reported +$428.93 on 8,883 labeled fills. Official resolution shows that the nine direct label disagreements account for only **-$15.00** of the correction. The decisive defect was the excluded cohort:

- Previously unlabeled fills: **385** (4.15% of fills)
- Official win rate in that cohort: **67.53%**
- Official P&L in that cohort: **-$472.92**
- Losses in that cohort: **125**, or **24.04%** of all official losses
- Date span: **2026-03-25T04:20:00+00:00** through **2026-05-18T09:30:00+00:00**

The public dataset explicitly labels outcomes by inference from the final recorded book and permits null outcomes near edge cases. Those nulls were not missing at random: excluding them removed difficult, reversal-prone markets and materially inflated the apparent edge.

## Asset decomposition

| Asset | Fills | Win rate | P&L at 5 shares | Daily 95% bootstrap interval |
|---|---:|---:|---:|---:|
| BTC | 4,844 | 94.6945% | +$64.00 | -$1.72 to +$3.93 |
| ETH | 4,424 | 94.0552% | -$123.00 | -$5.90 to +$0.18 |
| Combined | 9,268 | 94.3893% | -$59.00 | -$5.18 to +$3.00 |

BTC-only is **not promoted**. BTC was selected for inspection together with ETH, and retaining BTC after seeing official outcomes would be post-hoc. Its daily confidence interval also crosses zero. Any BTC-only continuation must be frozen as a new prospective version with no inherited holdout status.

## Risk findings

- 56 official calendar days; 27 positive days (48.21%).
- Daily t-statistic: -0.50; sign-flip p-value: 0.691.
- Nine calendar weeks; five positive.
- BTC/ETH loss correlation in simultaneous windows: 0.522.
- ETH win probability was 97.80% when BTC won, but only 44.57% when BTC lost.
- Additional cost of only 0.25 cents/share worsens total P&L to approximately -$174.85.

## Evidence identity

- Filled condition-set SHA-256: `bf276fbce187d9651d56ecae976520d4251140c1d5b0d440696c5d077838a67a`
- Official transfer source run: `30213818908`
- Full official evidence artifact SHA-256: `210984541bcd64597ca48d480ad59102427f56b4ac204ab1308ad8f8a4f93ce5`
- Compact derivative artifact SHA-256: `fb5dfb4621caa8b62ebaefc0b5c15d04619f773c3686cc4f088767ca023416b9`
- Raw-response manifest SHA-256: `80283073bf2fbed3b5f9ff565852c4303c1ed18f1c6df0845a63abf478059655`
- Gamma terminal payloads: 9,268; failures: 0.
- CLOB corroborated 5,615 outcomes; 3,653 were Gamma-only and retained as such.

## Classification

- **Candidate:** Rejected / falsified.
- **Cause:** non-random inferred-label censoring plus weak/negative official economics.
- **BTC-only:** post-hoc diagnostic lead only; prospective-only.
- **ETH:** rejected.
- **Live mode:** disabled; no order submitter or credentials.

## Next valid research

1. Preserve this rejection as immutable diagnostic evidence.
2. Correct the reproducer so execution fees are recorded even when inferred labels are null; this is an audit-field correction only and does not change fills or the official verdict.
3. Freeze any BTC-only or replacement hypothesis under a new version before observing new data.
4. Run a credential-free, append-only prospective observer with authoritative terminal outcomes and complete no-trade/fill records.
5. Do not use the inspected historical corpus as admission evidence again.
