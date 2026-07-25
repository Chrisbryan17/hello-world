# Digital Surface Source-Gate Root-Cause Checkpoint — 2026-07-24

## Frozen inputs

- Authoritative implementation commit: `Chrisbryan17/trading-tools@aa63003bc6c8cb5532b5452536e2ab36761fac4c`
- Immutable Obadiaha corpus: `obadiaha/polymarket-crypto-5m-15m@11793901f0ac89c5a6c51123a6ccd29a3aaf8f4c`
- Contracts after normalization: 5,228
- Required pre-fold agreement: 99%
- No contracts filtered; no signals, thresholds, execution assumptions, or validation chronology changed.

## Root cause

The original adapter used causal Binance minute bars for two distinct roles:

1. the causal trading/reference strike used by the research features; and
2. a proxy reconstruction of the Polymarket settlement direction.

Polymarket settles these crypto Up/Down contracts from its official terminal market outcome, whose underlying resolution source is Chainlink. Binance and Chainlink are not identical price streams, so Binance-direction agreement is a cross-venue diagnostic, not a valid authenticity test for the recorded Polymarket outcome labels.

## Evidence

### Independent Chainlink Price-to-Beat audit

- Contracts: 5,228
- Unique boundary pages: 5,230
- Independent Chainlink boundary coverage: 96.3657%
- Direction agreement where both boundaries exist: 100%
- Missing boundary pages: 189 initially; one recovered; 188 remain
- Missing boundaries are concentrated in one March 9, 2026 metadata gap
- No disagreement was found among covered contracts

This audit cannot by itself clear a 100%-coverage gate because the historical numeric boundary field is unavailable for the March 9 gap.

### Official terminal-outcome audit

- Official Polymarket Gamma terminal outcomes: 5,228 / 5,228
- Agreement with immutable Obadiaha labels: 100%
- Each retained row contains condition ID, canonical slug, terminal outcome, Gamma URL, HTTP status, event ID, response byte count, and response SHA-256.

This is sufficient to validate label integrity, but it must not be described as independent numeric Chainlink boundary coverage.

## Correct source-gate semantics

- Preserve causal Binance minute opening prices for strategy strikes/features.
- Validate immutable resolution labels against checksum-pinned official Polymarket terminal outcomes.
- Keep the 99% threshold and enforce 100% coverage before any fold.
- Retain Binance-versus-recorded direction agreement only as a diagnostic field.
- Do not claim that Gamma terminal outcomes reproduce the unavailable March 9 numeric Chainlink boundary values.

## Local implementation status

A local authoritative-tree reconstruction now:

- loads a deterministic gzip snapshot containing all 5,228 official Gamma terminal outcomes;
- verifies the snapshot SHA-256;
- requires unique condition IDs, Up/Down terminal values, Gamma URLs, valid payload SHA-256 values, and HTTP 200 status;
- enforces 100% official-outcome coverage and at least 99% agreement before folds;
- leaves Binance strike construction unchanged;
- reports Binance direction agreement separately as a diagnostic;
- compiles successfully;
- passes exactly 29 / 29 tests.

Next step: publish the minimal test-first implementation to an isolated authoritative branch, verify its exact remote hashes, and run the complete four-fold clean-room campaign.