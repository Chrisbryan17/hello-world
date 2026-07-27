# BTC-Only v3 Prospective Run v1

## Classification

**Valid prospective observation; not strategy admission.**

This is the first complete post-freeze market collected by `late_favorite_btc_only_v3_prospective_shadow` using the frozen candidate and capture policies. It counts as one observed prospective market and zero hypothetical FOK fills. It does not satisfy any weekly, fill-count, confidence-bound, concentration, or release gate.

## Market and decision

- Window: **2026-07-26 21:00–21:05 UTC** / **4:00–4:05 PM Jamaica**
- Slug: `btc-updown-5m-1785099600`
- Condition ID: `0x4c02c25039452fa49c84a0a8d10f59390ac9b26b8b11f52a58ecfcec7962f13c`
- Frozen signal time: market open +210 seconds
- Frozen arrival time: market open +211 seconds
- Selected side: **Up**
- Signal ask: **$0.98**
- Arrival best ask: **$0.99**
- Decision: **`no_fill_ask_above_limit`**
- Official outcome: **Up**
- Hypothetical fill: **No**
- P&L: **Not applicable; no fill**

The observer did not chase the one-cent adverse price move. Although Up ultimately won, the arrival ask exceeded the frozen 98-cent FOK limit, so no position and no P&L were recorded.

## Timing and market-data evidence

- Signal request: started exactly at target; completed in **155 ms**.
- Signal books: timestamped **80 ms** after target and **75 ms** before request completion.
- Arrival request: started exactly at target; completed in **152 ms**.
- Arrival book: timestamped **69 ms** after target and **83 ms** before request completion.
- Full Up/Down signal books and selected-token arrival book were preserved and hashed.

## Authoritative resolution

Gamma returned 20 non-terminal payloads followed by one terminal payload. Every poll used a unique deterministic cache-busting query. The terminal response reported:

- `closed: true`
- outcomes: `["Up", "Down"]`
- terminal prices: `["1", "0"]`
- `updatedAt`: `2026-07-26T21:06:32.32566Z`

A stale-CDN defect was discovered during the preceding discarded attempt: the unqualified Gamma slug URL could continue returning a pre-close body after terminalization. Resolution requests now append `?cache_bust=<raw-evidence-record-count>`. This changes only transport freshness; it does not alter the candidate, timing, entry, FOK, fee, or outcome rules.

## Integrity verification

- GitHub Actions run: `30220121542`
- Artifact ID: `8637040765`
- Artifact ZIP SHA-256: `8d00c88d6046806a2abc07f43da8b2f0ab08449890ee8a7f9e1f7071b92c4e21`
- Workflow head SHA: `257e3b5f1bfa4118a4375fbbfc4693152a296c55`
- Runtime source SHA-256: `ce477bf97589997899c91ad22af9025de521520f8ee7aa46a21b50a313958bd7`
- Lifecycle records: **4**, chain verified
- Lifecycle head: `a2c123f6ba2413d7dddee24ef20d75b096503e0d31a7b1051d8118cfd9911a1d`
- Raw evidence records: **24**, chain and bodies verified
- Raw evidence head: `baa3454eab1f1d8417a0b494a34a0a5ab87a7b7a1ab0e96e058400fafab8d6e0`
- Internal `SHA256SUMS`: passed
- Deterministic TAR sidecar: passed
- ZIP/TAR directory round-trip: byte-for-byte passed
- Credentials used: **0**
- Authenticated Polymarket requests: **0**
- Order submissions: **0**
- Historical admission credit: **0**
- Live submission: **physically absent**

## Admission ledger after this run

- Prospective markets observed: **1 / 500 minimum**
- Hypothetical FOK fills: **0 / 100 minimum**
- Official outcome coverage: **1 / 1**
- Complete untouched weekly blocks: **0 / 4 minimum**
- Realized prospective P&L: **$0.00**, because no fill occurred
- Candidate status: **prospective shadow only**

## Next valid work

1. Merge the cache-busting resolver correction after the 25-test clean-room checkpoint passes.
2. Continue collecting every eligible BTC five-minute market, including no-signal and no-fill decisions.
3. Preserve authoritative outcomes and complete raw/lifecycle chains for every market.
4. Do not inspect or tune thresholds during the prospective block.
5. Keep live order submission physically absent.
