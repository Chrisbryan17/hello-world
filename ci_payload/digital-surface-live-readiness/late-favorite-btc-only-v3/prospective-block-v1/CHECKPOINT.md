# BTC-Only v3 Prospective Block v1

## Classification

**Valid prospective block evidence; not strategy admission.**

This checkpoint covers three consecutive post-freeze BTC five-minute markets collected under the unchanged `late_favorite_btc_only_v3_prospective_shadow` candidate and capture policies. Every market was captured before any resolution request was made. All three conditions later received authoritative Gamma terminal outcomes.

The block produced **zero hypothetical FOK fills** and **$0.00 prospective P&L**. It increases the cumulative prospective market count from 1 to 4, but does not satisfy the minimum market, fill, weekly-block, confidence-bound, concentration, or release gates.

## Block identity

- Windows: **2026-07-26 21:30–21:45 UTC** / **4:30–4:45 PM Jamaica**
- Consecutive market openings: `1785101400`, `1785101700`, `1785102000`
- GitHub Actions run: `30221188931`
- Workflow head SHA: `be327b99530d9a5b1142e0c9896ae01716d4b070`
- Artifact ID: `8637433570`
- Artifact ZIP SHA-256: `222d8261ea92dfdfcd3fbb9ccb12dbf6948d03f6bed1e7558f3d9e4bdc6a5580`
- Runtime source SHA-256: `81a13d2aeb3df3c2088b8aa99272b10e217a392eabc839a01a8f2b71f570ecbb`
- Candidate policy SHA-256: `82b923b0d4034d801156b77a213db6084be719f27491478247e5354ea93e92ba`
- Capture policy SHA-256: `888810ae61a0ab3e067c68850faeba5f2709a57bb69ef0c2ad708e128b311edc`

## Market results

| Jamaica window | Selected side | Signal ask | Arrival | Frozen decision | Official outcome | P&L |
|---|---:|---:|---:|---|---:|---:|
| 4:30–4:35 PM | Up | $0.66 | Not requested | `no_signal_below_threshold` | Up | $0.00 |
| 4:35–4:40 PM | Down | $0.76 | Not requested | `no_signal_below_threshold` | Down | $0.00 |
| 4:40–4:45 PM | Up | $0.95 | $0.98 best ask | `no_fill_ask_above_limit` | Down | $0.00 |

The third market is decision-useful. Up qualified at a 95-cent signal ask, but one second later its best ask was 98 cents—above the frozen 95-cent FOK limit. The observer refused to chase the move. The market later resolved Down, so the no-fill rule avoided a losing position.

## Capture timing

### Market 1 — `btc-updown-5m-1785101400`

- Condition: `0x5452c4c60c9d3ed96739f7a46a58533244f2221ec504c352a808c7e3e90b379b`
- Signal request start: exactly +210,000 ms
- Signal request duration: 323 ms
- Signal book timestamp: +210,256 ms
- Decision: below 85-cent threshold

### Market 2 — `btc-updown-5m-1785101700`

- Condition: `0x7bd9fe5bfea03a72553b721d0824512a3e9dee6a0fec44992135d5cf08b3e352`
- Signal request start: +210,001 ms
- Signal request duration: 152 ms
- Signal book timestamp: +210,083 ms
- Decision: below 85-cent threshold

### Market 3 — `btc-updown-5m-1785102000`

- Condition: `0x1dcecaa2f4ee994fd4ab1b9f309bb18a56f24a5f9c84b82c290a7489d9cfd27d`
- Signal request start: exactly +210,000 ms
- Signal request duration: 170 ms
- Signal book timestamp: +210,112 ms
- Arrival request start: exactly +211,000 ms
- Arrival request duration: 265 ms
- Arrival book timestamp: +211,206 ms
- Decision: arrival ask above frozen limit

All request starts, durations, and book timestamps remained within the frozen capture-policy bounds.

## Authoritative outcomes

| Market | Resolution polls | Official outcome | Terminal prices | Gamma `updatedAt` | Terminal payload SHA-256 |
|---|---:|---:|---:|---|---|
| `1785101400` | 1 | Up | `[1, 0]` | `2026-07-26T21:37:05.248916Z` | `52737e9eb6279c33689c1044cf9074dad2dd98511b6fcc8e48439f5dea81e8ae` |
| `1785101700` | 5 | Down | `[0, 1]` | `2026-07-26T21:43:14.819851Z` | `a6fe3e627f6ac977e727d5fceb9fa47fd1b6ac9d2e1fc98a61aea9eccfa5aa86` |
| `1785102000` | 31 | Down | `[0, 1]` | `2026-07-26T21:46:24.754458Z` | `8693fbc94d74fbd218e18c3a8d65961efd2e997223509135b3b97395af6e89ca` |

Resolution polling began only after all three captures completed. Every poll used the cache-busted public Gamma endpoint and was preserved in the raw-evidence chain.

## Integrity verification

- Internal `SHA256SUMS`: **passed**
- Deterministic TAR sidecar: **passed**
- ZIP/TAR directory round-trip: **byte-for-byte passed**
- Lifecycle records: **10**
  - discovered: 3
  - signal: 3
  - arrival: 1
  - resolution: 3
- Lifecycle chain: **passed**
- Lifecycle head: `1f6f21cf25c1acd11ea5b06e4bd3dec617d69d84c8b25fb5471be22fc9430c11`
- Raw evidence records: **44**
  - market discovery: 3
  - signal books: 3
  - arrival books: 1
  - official resolution payloads: 37
- Raw evidence chain and body hashes: **passed**
- Raw evidence head: `9b43483f4a310d1ad84a3b6f5a029dc772f2181cb06dce08db476aab00dc2cf0`

## Admission ledger after this block

- Prospective markets observed: **4 / 500 minimum**
- Official outcomes available: **4 / 4**
- Hypothetical FOK fills: **0 / 100 minimum**
- Prospective P&L: **$0.00**
- Complete untouched weekly blocks: **0 / 4 minimum**
- Credentials used: **0**
- Authenticated requests: **0**
- Order submissions: **0**
- Historical admission credit: **0**
- Live submission: **physically absent**

The first one-shot observation and this block used different orchestration-source hashes, while the frozen candidate and capture policies remained identical. No weekly block receives completion credit yet.

## Next valid work

1. Continue capture-first prospective blocks without modifying candidate or capture thresholds.
2. Preserve every no-signal, no-fill, fill, resolution, and transport failure.
3. Accumulate at least 500 observed markets, 100 hypothetical fills, and four untouched weekly blocks.
4. Require zero unresolved states, acceptable concentration, measured execution evidence, and a positive lower confidence bound after fees and costs.
5. Keep real-money order submission physically absent.
