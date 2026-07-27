# BTC-Only v3 Prospective Block v3

## Classification

**Valid prospective block evidence; not strategy admission.**

This checkpoint covers three consecutive post-freeze BTC five-minute markets collected under the unchanged candidate and capture policies. The runner captured all three windows before sending any resolution request, then resolved every condition from authoritative cache-busted Gamma terminal responses.

The block produced one winning hypothetical FOK fill: **five Down shares at $0.87, +$0.610415**. Cumulatively, the prospective track now has two winning fills, but two observations remain far below every admission threshold.

## Block identity

- Windows: **2026-07-27 00:40–00:55 UTC** / **2026-07-26 7:40–7:55 PM Jamaica**
- Consecutive openings: `1785112800`, `1785113100`, `1785113400`
- GitHub Actions run: `30228071397`
- Workflow head SHA: `e5463d3ecb2b150de857ac73bf31e08d3317cd2f`
- Artifact ID: `8639355447`
- Artifact ZIP SHA-256: `b30e9e10de839070ad1ae88f98c952ff2d8d4378ab828bed1533cff0e588cc0e`
- Deterministic TAR SHA-256: `5af345750399cde55f782140c8ba0427b74d39c113ce864e7a045c3f246cc6ee`
- Runtime source SHA-256: `81a13d2aeb3df3c2088b8aa99272b10e217a392eabc839a01a8f2b71f570ecbb`
- Candidate policy SHA-256: `82b923b0d4034d801156b77a213db6084be719f27491478247e5354ea93e92ba`
- Capture policy SHA-256: `888810ae61a0ab3e067c68850faeba5f2709a57bb69ef0c2ad708e128b311edc`

## Market results

| Jamaica window | Selected side | Signal ask | Arrival | Frozen decision | Official outcome | P&L |
|---|---:|---:|---:|---|---:|---:|
| 7:40–7:45 PM | Up | $0.64 | Not requested | `no_signal_below_threshold` | Up | $0.00 |
| 7:45–7:50 PM | Down | $0.60 | Not requested | `no_signal_below_threshold` | Up | $0.00 |
| 7:50–7:55 PM | Down | $0.88 | $0.87; five shares | `hypothetical_fok_fill` | Down | **+$0.610415** |

## Filled-market economics

The final market, `btc-updown-5m-1785113400`, selected Down at an 88-cent signal ask. One second later, the best ask improved to 87 cents—exactly one cent below the signal ask, which remains eligible under the frozen adverse-move rule.

- signal ask: **$0.88**
- arrival best ask: **$0.87**
- execution: **5 shares at $0.87**
- execution VWAP: **$0.87**
- fee/share: **$0.007917**
- all-in cost/share: **$0.877917**
- official outcome: **Down**
- P&L/share: **$0.122083**
- five-share P&L: **+$0.610415**

No policy, threshold, size, fee, or execution rule changed.

## Capture timing

### Market 1 — `btc-updown-5m-1785112800`

- Signal request start: exactly +210,000 ms
- Signal request duration: 183 ms
- Signal book timestamps: +210,110 ms
- Decision: below the frozen 85-cent threshold

### Market 2 — `btc-updown-5m-1785113100`

- Signal request start: exactly +210,000 ms
- Signal request duration: 187 ms
- Signal book timestamps: +210,110 ms and +210,109 ms
- Decision: below the frozen 85-cent threshold

### Market 3 — `btc-updown-5m-1785113400`

- Signal request start: +210,001 ms
- Signal request duration: 198 ms
- Signal book timestamps: +210,122 ms
- Arrival request start: exactly +211,000 ms
- Arrival request duration: 163 ms
- Arrival book timestamp: +211,088 ms
- Decision: hypothetical FOK fill

Every request and book timestamp remained inside the frozen capture-policy limits.

## Authoritative outcomes

| Market opening | Resolution polls | Official outcome | Terminal prices | Gamma `updatedAt` | Terminal payload SHA-256 |
|---:|---:|---:|---|---|---|
| `1785112800` | 1 | Up | `[1, 0]` | `2026-07-27T00:51:14.942925Z` | `51fd814498aae2f743d5b6354eba77461066c333042c8a6614b263df0a85c8aa` |
| `1785113100` | 1 | Up | `[1, 0]` | `2026-07-27T00:51:35.707758Z` | `dbdcd84b4eb322624a45ae22543ed369be91021958779f9a52ca16c45e2d3423` |
| `1785113400` | 35 | Down | `[0, 1]` | `2026-07-27T00:56:26.240184Z` | `c37484c919bf833195bad9c90ecf508eafeda0cfc7af7560f6aff21fb465992a` |

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
- Lifecycle head: `fa080692b88dbfea6233fb6d2dc0f510008c7ff3c10342aec0b476afdb2f7579`
- Raw evidence records: **44**
- Raw evidence chain and body hashes: **passed**
- Raw evidence head: `5b24cf59091c974219c7d38abe776743b25fe445b41ecd00aa8812d47977ff26`
- Unresolved conditions: **0**
- Credentials/authenticated requests/order submissions: **0 / 0 / 0**
- Historical admission credit: **0**
- Live submission: **physically absent**

## Cumulative admission ledger

- Prospective markets observed: **10 / 500 minimum**
- Official outcomes available: **10 / 10**
- Hypothetical FOK fills: **2 / 100 minimum**
- Prospective P&L: **+$0.843790**
- Unresolved states: **0**
- Complete untouched weekly blocks: **0 / 4 minimum**

Both fills won, but a two-trade record has no meaningful statistical power and cannot satisfy confidence, concentration, weekly-block, or admission gates.

## Next valid work

1. Continue bounded capture-first blocks without modifying candidate or capture thresholds.
2. Preserve every no-signal, no-fill, fill, resolution, and transport-failure record.
3. Accumulate at least 500 markets, 100 hypothetical fills, and four untouched weekly blocks.
4. Require zero unresolved states, measured execution evidence, acceptable concentration, and a positive lower confidence bound after fees and costs.
5. Keep real-money order submission physically absent.
