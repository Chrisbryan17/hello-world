# BTC-Only v3 Prospective Block v2

## Classification

**Valid prospective block evidence; not strategy admission.**

This checkpoint covers three consecutive post-freeze BTC five-minute markets collected under the unchanged `late_favorite_btc_only_v3_prospective_shadow` candidate and capture policies. All three markets were captured before the runner made any resolution request. Every condition later received an authoritative Gamma terminal outcome.

The block produced the first genuine prospective hypothetical FOK fill: **one winning five-share Down fill and +$0.233375 P&L**. This is a useful observation, but one fill is nowhere near sufficient for admission.

## Block identity

- Windows: **2026-07-27 00:10–00:25 UTC** / **2026-07-26 7:10–7:25 PM Jamaica**
- Consecutive openings: `1785111000`, `1785111300`, `1785111600`
- GitHub Actions run: `30226869672`
- Workflow head SHA: `afc14b93c69bed593f4d51ce92fcbdb900d4a145`
- Artifact ID: `8638983600`
- Artifact ZIP SHA-256: `69ee1bb111f8aec0b52f982f305136a5e835ca2b2e50f4b66a129d3370b5ac58`
- Deterministic TAR SHA-256: `4fc0e0b68e7261899e133e1ba9af05939a72303d26609f73391967b5251c73cc`
- Runtime source SHA-256: `81a13d2aeb3df3c2088b8aa99272b10e217a392eabc839a01a8f2b71f570ecbb`
- Candidate policy SHA-256: `82b923b0d4034d801156b77a213db6084be719f27491478247e5354ea93e92ba`
- Capture policy SHA-256: `888810ae61a0ab3e067c68850faeba5f2709a57bb69ef0c2ad708e128b311edc`

## Market results

| Jamaica window | Selected side | Signal ask | Arrival | Frozen decision | Official outcome | P&L |
|---|---:|---:|---:|---|---:|---:|
| 7:10–7:15 PM | Up | $0.64 | Not requested | `no_signal_below_threshold` | Up | $0.00 |
| 7:15–7:20 PM | Down | $0.95 | $0.95; five shares | `hypothetical_fok_fill` | Down | **+$0.233375** |
| 7:20–7:25 PM | Up | $0.66 | Not requested | `no_signal_below_threshold` | Up | $0.00 |

## First prospective fill

The middle market, `btc-updown-5m-1785111300`, qualified with Down as the favorite at a 95-cent executable ask.

One second later:

- arrival best ask: **$0.95**;
- displayed executable size at or below the frozen limit: at least **5 shares**;
- execution: **5 shares at $0.95**;
- execution VWAP: **$0.95**;
- taker fee/share: **$0.003325**;
- all-in cost/share: **$0.953325**.

The market officially resolved Down. Therefore:

- official win: **yes**;
- P&L/share: **$0.046675**;
- P&L at five shares: **+$0.233375**.

No threshold or execution rule was changed before or during this market.

## Capture timing

### Market 1 — `btc-updown-5m-1785111000`

- Signal request start: +210,001 ms
- Signal request duration: 161 ms
- Signal book timestamps: +210,102 ms
- Decision: below the frozen 85-cent threshold

### Market 2 — `btc-updown-5m-1785111300`

- Signal request start: exactly +210,000 ms
- Signal request duration: 122 ms
- Signal book timestamps: +210,070 ms and +210,067 ms
- Arrival request start: exactly +211,000 ms
- Arrival request duration: 143 ms
- Arrival book timestamp: +211,095 ms
- Decision: hypothetical FOK fill

### Market 3 — `btc-updown-5m-1785111600`

- Signal request start: exactly +210,000 ms
- Signal request duration: 129 ms
- Signal book timestamps: +210,080 ms
- Decision: below the frozen 85-cent threshold

Every request start, request duration, and book timestamp remained within the frozen capture-policy bounds.

## Authoritative outcomes

| Market opening | Resolution polls | Official outcome | Terminal prices | Gamma `updatedAt` | Terminal payload SHA-256 |
|---:|---:|---:|---|---|---|
| `1785111000` | 1 | Up | `[1, 0]` | `2026-07-27T00:21:14.688273Z` | `c504beb6519ee8965f84c8a3122c701659672e7fa0ce0882689681325d77130b` |
| `1785111300` | 7 | Down | `[0, 1]` | `2026-07-27T00:23:15.362879Z` | `2863a051c35dd91192df4fc4088313937b328949e2bd0ac909597f2fe722d482` |
| `1785111600` | 29 | Up | `[1, 0]` | `2026-07-27T00:28:59.884201Z` | `a2ad563e7d0f24894088ca5c14206739b8f894041591462ff085b54136ff4ece` |

Resolution began only after all three capture windows completed. Every cache-busted public Gamma payload was preserved in the raw-evidence chain.

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
- Lifecycle head: `a04aac52de49a03fca237b888cbb284788a6dd5a53560147fc6b561489c9c87b`
- Raw evidence records: **44**
- Raw evidence chain and body hashes: **passed**
- Raw evidence head: `b44fc443b8c80537ae9f40243034194d45633e34f3d46694f0b3a895b9928606`
- Unresolved conditions: **0**
- Credentials used: **0**
- Authenticated requests: **0**
- Order submissions: **0**
- Historical admission credit: **0**
- Live submission: **physically absent**

## Cumulative admission ledger

- Prospective markets observed: **7 / 500 minimum**
- Official outcomes available: **7 / 7**
- Hypothetical FOK fills: **1 / 100 minimum**
- Prospective P&L: **+$0.233375**
- Unresolved states: **0**
- Complete untouched weekly blocks: **0 / 4 minimum**

The positive result is a single observation. It cannot support a confidence bound, concentration assessment, weekly-block pass, or strategy admission.

## Next valid work

1. Continue bounded capture-first blocks without modifying candidate or capture thresholds.
2. Preserve every no-signal, no-fill, fill, resolution, and transport-failure record.
3. Accumulate at least 500 observed markets, 100 hypothetical fills, and four untouched weekly blocks.
4. Require zero unresolved states, measured execution evidence, acceptable concentration, and a positive lower confidence bound after fees and costs.
5. Keep real-money order submission physically absent.
