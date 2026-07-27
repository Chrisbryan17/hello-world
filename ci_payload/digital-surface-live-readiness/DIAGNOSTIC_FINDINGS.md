# Execution Diagnostic Findings

Source artifact: GitHub Actions artifact `digital-surface-execution-diagnostics-v1`, artifact ID `8617727219`, outer SHA-256 `80a442cded15e26703c401e197a53db28ae59b61efa6dcb808a0d65ead961293`.

The immutable replay completed successfully and attributed exactly two legs for each of 224 candidates (448 legs total).

## Terminal leg reasons

| Reason | Legs | Share |
|---|---:|---:|
| Insufficient post-arrival tape | 186 | 41.52% |
| Ask above frozen limit | 114 | 25.45% |
| Missing post-arrival book | 110 | 24.55% |
| Filled | 34 | 7.59% |
| Insufficient displayed depth | 4 | 0.89% |

Only eight candidates filled both legs under the existing tape-confirmed replay.

## Size counterfactual

Reducing requested size does not solve the bottleneck:

| Shares | Tape-confirmed paired fills |
|---:|---:|
| 5 | 8 |
| 3 | 8 |
| 2 | 9 |
| 1 | 9 |
| 0.5 | 9 |
| 0.1 | 9 |

At five shares, 62 candidates have both post-latency arrival books, both asks within their frozen limits, and at least five displayed shares on both legs. The tape-confirmation requirement reduces those 62 book-executable candidates to eight.

## Root-cause conclusion

The fixed five-share size is not the principal execution bottleneck. The dominant blocker is the historical replay's requirement that unrelated post-arrival taker-buy tape independently demonstrate sufficient volume after the arrival snapshot. A real FOK order would itself consume displayed executable depth; its fill does not require another trader to print the same side afterward.

This does not prove that all 62 historical book-executable candidates would have filled live. It establishes two bounds that must remain separate:

1. **Tape-confirmed lower bound:** eight paired fills.
2. **Post-latency book-executable estimate:** 62 paired fills at five shares, before prospective calibration.

The next experiment must therefore implement a book-arrival FOK estimator with explicit uncertainty/haircuts, retain the tape-confirmed result as a conservative lower bound, and calibrate the estimator against prospective shadow orders. The four already observed weeks remain diagnostic and cannot become admissible holdouts.

Real-money execution remains disabled.
