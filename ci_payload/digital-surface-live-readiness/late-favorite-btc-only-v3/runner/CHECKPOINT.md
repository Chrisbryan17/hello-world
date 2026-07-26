# BTC-Only v3 One-Shot Runner Checkpoint

## Status

The credential-free one-shot runner for `late_favorite_btc_only_v3_prospective_shadow` is implemented, clean-room verified, independently artifact-checked, and merged into the durable live-readiness branch.

This checkpoint adds orchestration only. It does not change the frozen candidate, capture policy, execution model, or admission gates.

## Commands

- `collect-next`: choose the next eligible post-cutoff BTC five-minute window, persist discovery/signal/arrival evidence, and write a non-overwriting summary.
- `resolve --condition-id`: fetch authoritative terminal resolution and append official fill P&L or no-fill closure.
- `status`: report lifecycle/evidence heads, event counts, and unresolved condition IDs.

There is no live, trading, signing, or order-submission command.

## Persistence

The runner loads the two frozen policies, binds all five runtime modules into the lifecycle source hash, and persists:

- `lifecycle.jsonl` — append-only candidate/capture/source-bound lifecycle chain;
- `raw_evidence/manifest.jsonl` and content-addressed response bodies;
- exclusive `summaries/collect-<open>.json` files;
- exclusive `summaries/resolve-<condition>.json` files.

Duplicate summaries fail closed rather than overwriting evidence.

## Verification

- Runner PR: #67
- Merge commit: `9e794700600ba8a9173040711d09b7feb4817ff9`
- Workflow run: `30218421705`
- Artifact ID: `8636471934`
- Artifact ZIP SHA-256: `762294c4141c25d6dd0a1f6678e2f90795bfbecf909deaf130d3001358ca7b88`
- Tests: **5 passed**
- Combined runtime source SHA-256: `b398e7b9893170cb47ea17923448a87a10b017249a950ca670f9b09081b0d845`
- Internal `SHA256SUMS`: all files verified
- Deterministic TAR sidecar: verified
- Archive extraction round-trip: byte-for-byte verified

The unchanged observer core also passed its independent 22-contract checkpoint on the runner PR.

## Safety boundary

- credentials used: **0**
- authenticated requests: **0**
- order submissions: **0**
- live submission: **physically absent**
- historical admission credit: **0**

## Next valid work

Run `collect-next` in a one-shot GitHub workflow, upload the resulting append-only state artifact, then resolve that condition after official closure. Only post-capture-freeze markets may count.
