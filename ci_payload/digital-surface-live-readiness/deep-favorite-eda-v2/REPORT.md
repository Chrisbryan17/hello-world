# Polymarket 5-Minute Crypto — Deep Favorite EDA Checkpoint

## Decision-useful answer

The strongest high-frequency candidate in the 89,233-market / 26.77M-tick corpus is not BTC-to-alt lead-lag. It is a **late-window settlement-favorite strategy** at 210 seconds with a signal ask of at least 85 cents, one-second execution latency, five-share FOK sizing, and taker fees included.

The all-seven-asset version was positive on the final chronological test segment, but the edge was diluted by weak assets and concentrated in a few days. The statistically credible core is **BTC + ETH**. This is a research candidate for official-label transfer and prospective shadowing, not permission for live trading.

## Evidence spine

### Original strict walk-forward result

- Train: 38 active days, 18,493 trades, +$1,088.33 at five shares, daily t = 5.91.
- Validation: 14 active days, 6,819 trades, +$395.42, daily t = 5.35, every validation day positive.
- Final chronological test: 12 active days, 6,769 trades, +$249.11, 24.67 trades/hour, daily t = 1.67.
- The selected 210s / 85c configuration ranked #1 of 982 eligible configurations by validation daily t.
- Every tested latency from 0 to 3 seconds remained positive in train and validation.

### BTC + ETH alpha spine

- 2,054 final-test trades.
- +$139.72 at five shares.
- 95.67% win rate.
- 1.3604 cents mean P&L per share after the modeled fee.
- Daily t = 3.85.
- Exact one-sided day-level sign-flip p = 0.00244.
- 95% day-bootstrap mean interval: +$5.84 to +$17.13 per day at five shares.
- BTC and ETH individually survive Benjamini-Hochberg control at 5% across seven assets.

### Adverse-selection finding

A lower execution ask is not always price improvement. When the favorite ask fell by at least 2 cents during the one-second latency window, the final test produced:

- 288 trades;
- 84.38% win rate;
- -$48.44 at five shares;
- negative daily t.

A one-cent improvement was positive, while two cents or more was toxic. This supports a causal **cancel if arrival ask is more than 1 cent below the signal ask** rule for the next prospective candidate. Because this rule was diagnosed after inspecting the final test, it must be validated only on new observations.

### Cross-asset loss clustering

- 38.66% of losses occurred in windows with at least two simultaneous asset losses.
- BTC/ETH loss correlation was 0.559.
- When BTC won, ETH won 98.39% of simultaneous windows; when BTC lost, ETH won only 38.46%.
- The all-seven portfolio derived 66.62% of total P&L from its two best days.
- BTC + ETH reduced top-two-day concentration to 38.02%.

This is a common-factor crash problem, not independent diversification. Portfolio exposure must be capped by five-minute window, not only by asset.

### Execution-price calibration

BTC/ETH edge is concentrated in the 85c-93c range. Diagnostic one-cent buckets showed especially strong empirical edge at 86c, 88c, 91c and 92c. The 95c and 98c buckets were flat-to-negative, while 99c remained slightly positive. This irregularity argues against fitting a fine price lookup table from the inspected test; retain the broad 85c rule until prospective evidence accumulates.

### Capacity and cost sensitivity

- BTC/ETH break-even additional cost: 1.3604 cents/share.
- All-seven break-even additional cost: 0.7360 cents/share.
- At 100 shares, 56.13% of BTC/ETH test signals displayed enough top-of-book size and remained positive, but daily tail risk scaled sharply.
- At 250+ shares, statistical quality deteriorated; top-of-book size is selection-biased and is not a reliable live capacity guarantee.
- The all-seven strategy turned negative at 1 cent extra slippage; the BTC/ETH core has more cost headroom but still requires measured prospective fill slippage.

## Frozen prospective hypothesis

```json
{
  "name": "late_favorite_btc_eth_v2_diagnostic",
  "assets": ["btc", "eth"],
  "entry_second": 210,
  "signal_ask_min": 0.85,
  "latency_seconds": 1,
  "fok_limit": "signal ask",
  "shares": 5,
  "arrival_adverse_move_cancel": "cancel when execution ask < signal ask - 0.01",
  "maximum_positions_per_asset_per_window": 1,
  "maximum_total_positions_per_window": 2,
  "hold": "settlement",
  "fee_per_share": "0.07 * p * (1-p)",
  "live_submission": "disabled",
  "status": "diagnostic candidate; requires new official-label prospective validation"
}
```

## Non-negotiable uncertainty

1. Dataset outcomes are inferred from the final recorded book, not authoritative settlement.
2. Only 28 false winning labels would erase the BTC/ETH final-test profit; official-resolution validation is mandatory.
3. Ask-side capacity is top-of-book only; queue position and full depth were not recorded.
4. The BTC/ETH universe and adverse-move cancel were identified after inspecting the final test. They cannot inherit the original untouched-test status.
5. Real-money order submission remains absent. The next valid evidence is an append-only prospective shadow ledger.

## Next experiment

Run the frozen BTC/ETH candidate prospectively with official terminal outcomes and public-book evidence. Report every five-minute window, including no-trade decisions, arrival price movement, displayed size, hypothetical FOK fill, settlement, and per-window portfolio exposure. Admission requires at least four untouched weekly blocks and enough trades to establish a positive lower confidence bound after measured fees and slippage.
