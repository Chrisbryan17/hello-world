# Digital Surface Live-Readiness Design

## Objective

Turn the verified BTC 5m-versus-15m surface-arbitrage research snapshot into a recoverable, production-shaped system without claiming profitability from contaminated holdouts or enabling real-money orders before prospective evidence exists.

## Non-negotiable research integrity

1. The four Kinzik weeks already examined are diagnostic data and cannot be reused as untouched acceptance folds.
2. Strategy, threshold, sizing, and execution-policy selection may use only chronologically prior data.
3. Final admission requires four newly reserved untouched weeks or four prospective weekly shadow folds.
4. No admission rule may be relaxed merely to make a fold pass.
5. Every source, test, workflow, diagnostic, and result checkpoint is committed to GitHub before the next experiment.

## Workstreams

### 1. Execution bottleneck diagnosis

Produce deterministic candidate-to-fill attribution for each leg:

- missing post-arrival book;
- ask above limit;
- displayed depth below requested shares;
- post-arrival taker tape below requested shares;
- atomic fill;
- orphaned low-YES leg;
- orphaned high-NO leg.

Break results down by week, time-to-expiry, decision cadence, expected cost, edge, size, and leg orientation.

### 2. Validation-only strategy redesign

Evaluate changes only on chronologically prior training/validation blocks. Candidate approaches are:

- liquidity-aware prequalification using causal book/tape features;
- smaller size tiers selected from validation liquidity;
- maker-first coordinated execution with bounded orphan inventory;
- multiple same-expiry strike pairs rather than only the first qualifying pair;
- stronger calibration and interval-probability uncertainty penalties.

The selected policy must be frozen before any new test week.

### 3. Production-shaped shadow bot

Implement a Polymarket CLOB V2 adapter with:

- public market WebSocket ingestion;
- authenticated user WebSocket reconciliation;
- signed FOK or explicitly bounded maker orders;
- heartbeat fail-safe;
- cancel-all kill switch;
- idempotent order state machine;
- balance, allowance, tick-size, fee-rate, and market-status checks;
- maximum daily loss and maximum orphan exposure limits;
- shadow mode as the default and only CI-enabled mode.

There is no claim of atomic multi-market execution. Batch submission reduces timing skew but does not make two independent CLOB orders atomic.

## Acceptance gates

### Historical diagnostic gate

- Existing 29 tests remain green.
- Execution attribution covers 100% of candidate legs.
- No future book or trade print is used.
- Any redesigned policy is selected without consulting its test week.

### Prospective admission gate

Across four newly untouched weekly folds:

- all four weekly gates pass;
- at least 40 atomic or economically equivalent completed portfolios overall;
- at least 10 completed portfolios in every week;
- aggregate frequency at least 0.50 portfolios/hour;
- weakest-week frequency at least 0.20 portfolios/hour;
- orphan rate at most 5%;
- no single settlement timestamp contributes more than 20% of positive P&L;
- positive net growth after fees and one- and two-cent adverse slippage;
- bankroll and drawdown limits remain satisfied.

### Live-arm gate

Real-money order submission remains disabled until:

- prospective admission passes;
- at least 500 shadow markets have been observed;
- at least 100 shadow-qualified portfolios have complete order-state evidence;
- credentials are supplied through secrets, never committed;
- the operator explicitly changes `TRADING_MODE=shadow` to `TRADING_MODE=live` after reviewing the final evidence artifact.

## Failure behavior

Any stale market feed, authentication error, heartbeat failure, unresolved order state, balance discrepancy, source-integrity failure, or risk-limit breach immediately disables new orders and cancels open orders. Existing positions are surfaced for manual resolution; the bot never hides or automatically doubles down on orphan exposure.
