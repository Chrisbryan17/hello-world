# BTC-Only v3 Prospective Observer Checkpoint

## Status

The frozen `late_favorite_btc_only_v3_prospective_shadow` observer and credential-free public collector are implemented and clean-room verified. This checkpoint is **infrastructure readiness only**. It contains no prospective market observations and grants no admission credit.

## Frozen boundaries

- Candidate policy SHA-256: `82b923b0d4034d801156b77a213db6084be719f27491478247e5354ea93e92ba`
- Candidate cutoff: `2026-07-26T19:11:11Z`
- Capture policy SHA-256: `888810ae61a0ab3e067c68850faeba5f2709a57bb69ef0c2ad708e128b311edc`
- Effective capture cutoff: `2026-07-26T19:35:21Z`
- Historical admission credit: **0**
- Live submission: **physically absent**

Only BTC five-minute markets opening strictly after the effective capture cutoff may enter a prospective ledger.

## Implemented behavior

1. Signal target remains market open +210 seconds.
2. Arrival target remains market open +211 seconds and is independent of HTTP completion time.
3. Public request starts may be at most 250 ms late; requests longer than 1,000 ms fail closed.
4. Books older than 2,000 ms at request completion fail closed.
5. Signal uses the higher executable Up/Down ask and requires at least $0.85.
6. Arrival applies the frozen adverse-move cancel and FOK price limit.
7. Five-share execution uses cumulative full-depth levels and per-level fee accounting.
8. Every discovery, signal/no-signal, arrival/no-fill, and resolution is append-only and hash chained.
9. Official settlement uses closed binary Gamma terminal prices and raw response SHA-256 evidence.
10. Raw public response bodies are content-addressed and bound to a separate evidence manifest chain.

## Public capability boundary

The only allowed network operations are:

- `GET https://gamma-api.polymarket.com/markets/slug/{slug}`
- `POST https://clob.polymarket.com/books`

The clean-room capability scan found:

- credentials used: **0**
- authenticated requests: **0**
- order submissions: **0**
- signing/private-key libraries: **0**

## Verification evidence

- Workflow run: `30217953678`
- Artifact ID: `8636344655`
- Artifact ZIP SHA-256: `667d7090ecfe3d174e5821af29a26fde2e18a87a50f7891cdcc49dff740f26af`
- Tests: **22 passed**
- Combined source SHA-256: `f2e086bb5e74f0343a4ea29f46ea2bf8e23062952b456303e204c6b5469b6126`
- Deterministic TAR sidecar: verified
- Internal `SHA256SUMS`: all files verified
- Archive extraction round-trip: byte-for-byte verified

Source file SHA-256 values are recorded in `OBSERVER_VERIFICATION.json`.

## Admission boundary

This checkpoint does not show that BTC-only is profitable. The inspected official historical point estimate was marginal and post-hoc. Admission still requires genuinely new observations, at least four untouched weekly blocks, authoritative outcome coverage, measured public-book fill evidence, acceptable concentration, zero unresolved states, and a positive lower confidence bound after fees and execution costs.

## Next valid work

1. Add a one-shot runnable CLI that selects the next eligible BTC window and persists its ledger/evidence directories.
2. Execute the collector only on post-cutoff markets.
3. Add a separate resolver command for closed markets.
4. Package append-only ledger/evidence artifacts after each run.
5. Keep live order submission absent.
