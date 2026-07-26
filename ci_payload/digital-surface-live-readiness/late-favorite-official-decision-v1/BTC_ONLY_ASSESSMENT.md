# BTC-Only Post-Transfer Diagnostic Assessment

## Classification

**Marginal prospective lead only. Not admitted. Not a historical pass.**

BTC was part of the inspected BTC+ETH candidate. Retaining BTC after observing the official asset split is post-hoc. The statistics below may justify low-cost prospective shadowing under a newly frozen version, but they cannot inherit any validation status from the rejected BTC+ETH rule.

## Fixed-rule official result

The entry geometry was not changed: second 210, favorite ask at least $0.85, one-second latency, five-share FOK at the signal ask, cancel when arrival ask is more than $0.01 lower, fee `0.07*p*(1-p)`, settlement hold.

- Fills: **4,844**
- Official wins: **4,587**
- Official win rate: **94.6945%**
- Mean P&L/share: **+$0.00264236** (**0.2642 cents/share**)
- P&L at five shares: **+$64.00**
- Official days: **56**
- Positive days: **30** (53.57%)
- Daily 95% bootstrap interval for mean P&L: **-$1.73 to +$3.93/day**
- Positive calendar weeks: **6 of 9**
- Maximum cumulative P&L: **+$67.92**
- Maximum dollar drawdown: **-$56.15**
- Approximately **13 additional winner-to-loss flips** erase the observed profit.

## Cost fragility

| Additional cost/share | BTC P&L at five shares |
|---:|---:|
| 0.00 cents | +$64.00 |
| 0.10 cents | +$39.78 |
| 0.20 cents | +$15.56 |
| 0.25 cents | +$3.45 |
| 0.30 cents | -$8.66 |
| 0.50 cents | -$57.10 |

The observed edge is therefore too small to tolerate even modest unmodeled execution friction. Public top-of-book crossability is not proof of queue-position or realized FOK fill probability.

## Stability diagnostics

Chronological quartile P&L was `[-$11.31, +$11.47, +$24.16, +$39.67]`, so the result was not produced solely by the earliest segment. Every leave-one-week-out total remained positive. However, weekly outcomes still included three meaningful losing weeks, and the daily confidence interval crosses zero.

Both selected directions were positive under the unchanged rule:

- Down favorite: +$55.52 across 2,418 fills.
- Up favorite: +$8.47 across 2,426 fills.

This split must not be used to introduce a new side filter on the inspected corpus. Price-bucket results were also irregular; no bucket optimization is authorized.

## Decision

BTC-only is worth **shadow observation only** because the official point estimate is positive and broadly distributed, but the economic margin is nearly exhausted by 0.25 cents/share of additional cost and statistical uncertainty remains material.

Any continuation must:

1. use a new version identifier and policy hash;
2. start after the policy is frozen;
3. record every BTC 5-minute window, including no-signal and no-fill outcomes;
4. preserve signal and one-second-arrival full-depth books;
5. resolve every market from authoritative terminal outcomes;
6. measure actual crossability and displayed depth without assuming queue priority;
7. run at least four untouched weekly blocks;
8. require a positive lower confidence bound after fees and measured execution costs;
9. keep real-money submission physically absent.
