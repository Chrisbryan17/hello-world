# Digital Surface Live-Readiness Status

## Durable checkpoint

- Repository: `Chrisbryan17/hello-world`
- Branch: `digital-surface-live-readiness-20260725`
- Draft PR: #59
- Official late-favorite decision commit: `cedd659e0b573d8479932c428cd2eaf472c6bf8f`
- First BTC-only prospective checkpoint merge: `f76097ef513a2e70881e7624cd8d9a60d12a642b`
- Bounded block-runner merge: `e0b4917c2c7895568d7acb0ca53d4a6ccfcfdf1c`
- Real-money execution: **physically disabled**

## Historical research verdicts

### Original 5m-vs-15m digital-surface sleeve

The official-resolution source gate and all four historical transfer folds completed, but the frozen sleeve remained **Rejected**. Those folds are diagnostic only and may never count toward prospective admission.

### Late-favorite BTC/ETH candidate

The immutable 9,268-fill set was transferred to authoritative Polymarket terminal outcomes with 100% coverage. The candidate is **Rejected / falsified**:

- official win rate: 94.3893%;
- official mean P&L/share: -$0.00127314;
- official P&L at five shares: -$59.00;
- BTC: +$64.00, but its daily confidence interval crosses zero;
- ETH: -$123.00.

The earlier +$428.93 inferred-label result was biased by 385 null-labeled fills. Official resolution showed that excluded cohort had only 67.53% wins and lost $472.92. Nine direct label disagreements changed comparable P&L by only -$15.00; the material defect was non-random label-availability censoring.

Authoritative decision evidence:

- `ci_payload/digital-surface-live-readiness/late-favorite-official-decision-v1/CHECKPOINT.md`
- filled condition-set SHA-256: `bf276fbce187d9651d56ecae976520d4251140c1d5b0d440696c5d077838a67a`
- full official evidence artifact SHA-256: `210984541bcd64597ca48d480ad59102427f56b4ac204ab1308ad8f8a4f93ce5`
- compact derivative artifact SHA-256: `fb5dfb4621caa8b62ebaefc0b5c15d04619f773c3686cc4f088767ca023416b9`

## BTC-only v3 prospective shadow track

BTC-only is a **marginal post-hoc lead**, not a historical pass. It has zero inherited validation or admission credit.

### Frozen candidate and capture boundaries

- candidate: `late_favorite_btc_only_v3_prospective_shadow`
- candidate policy SHA-256: `82b923b0d4034d801156b77a213db6084be719f27491478247e5354ea93e92ba`
- candidate freeze: `2026-07-26T19:11:11Z`
- capture policy SHA-256: `888810ae61a0ab3e067c68850faeba5f2709a57bb69ef0c2ad708e128b311edc`
- effective capture cutoff: `2026-07-26T19:35:21Z`
- only markets opening strictly after the effective capture cutoff may count.

### Observer and runner verification

The observer implements market-open-anchored +210s/+211s capture, frozen timing/freshness gates, Decimal full-depth five-share FOK evaluation, fail-closed decision states, append-only lifecycle and raw-evidence chains, public Gamma/CLOB collection, cache-busted terminal resolution, and official fill/no-fill closure.

Observer checkpoint:

- 25/25 behavior contracts passed;
- workflow run: `30220717065`;
- artifact ID: `8637116192`;
- artifact ZIP SHA-256: `172ef7213e7860a8bee00db5e0a79d66495d31199cde85d39dcfef201f14de86`;
- combined frozen source SHA-256: `ce477bf97589997899c91ad22af9025de521520f8ee7aa46a21b50a313958bd7`.

The bounded runner adds `collect-block`: 1–12 consecutive windows are captured before any resolution request, then the condition queue is resolved with bounded cache-busted retries. Unresolved state is preserved in a durable summary.

Runner checkpoint:

- 11/11 contracts passed;
- workflow run: `30221103255`;
- artifact ID: `8637227551`;
- artifact ZIP SHA-256: `fbc509ffa17046b885f25ef13b982f08c4f706bf4d65a73a179c66f0f1fb8f3b`;
- runner SHA-256: `48b45fb823b6fd9f6edf469d34a2c3a85c767c0bf4a456b919127dfeb39dcb8b`;
- combined runtime source SHA-256: `81a13d2aeb3df3c2088b8aa99272b10e217a392eabc839a01a8f2b71f570ecbb`.

### Prospective observation v1

- checkpoint: `ci_payload/digital-surface-live-readiness/late-favorite-btc-only-v3/prospective-run-v1/CHECKPOINT.md`
- market: `btc-updown-5m-1785099600`, 2026-07-26 21:00–21:05 UTC;
- Up signal at $0.98; arrival ask $0.99;
- decision: `no_fill_ask_above_limit`;
- official outcome: Up;
- fill/P&L: none;
- artifact ZIP SHA-256: `8d00c88d6046806a2abc07f43da8b2f0ab08449890ee8a7f9e1f7071b92c4e21`.

### Prospective block v1

Checkpoint:

- `ci_payload/digital-surface-live-readiness/late-favorite-btc-only-v3/prospective-block-v1/CHECKPOINT.md`
- workflow run: `30221188931`;
- artifact ID: `8637433570`;
- artifact ZIP SHA-256: `222d8261ea92dfdfcd3fbb9ccb12dbf6948d03f6bed1e7558f3d9e4bdc6a5580`.

Three consecutive markets were collected from 21:30–21:45 UTC:

1. Up at $0.66: below threshold; official Up.
2. Down at $0.76: below threshold; official Down.
3. Up at $0.95: arrival ask $0.98, so no fill above the frozen limit; official Down.

Block result:

- markets: 3;
- official outcomes: 3/3;
- hypothetical fills: 0;
- P&L: $0.00;
- unresolved conditions: 0;
- lifecycle records: 10, chain verified;
- raw evidence records: 44, chain and bodies verified.

The third decision avoided a loss: the observer refused to chase Up from 95 cents to 98 cents, and the market resolved Down.

## Safety and admission boundary

- credentials used: **0**;
- authenticated requests: **0**;
- order submissions: **0**;
- live submission: **physically absent**;
- historical admission credit: **0**;
- prospective markets observed: **4 / 500 minimum**;
- official outcome coverage: **4 / 4**;
- hypothetical FOK fills: **0 / 100 minimum**;
- prospective P&L: **$0.00**;
- complete untouched weekly blocks: **0 / 4 minimum**.

No historical result is admissible. These four markets are valid prospective evidence but cannot support admission. Even a future admissible shadow report cannot enable live trading; any order submitter requires a separate reviewed release and explicit operator action.

## Next work

1. continue bounded capture-first blocks without modifying candidate or capture thresholds;
2. preserve every no-signal, no-fill, fill, resolution, and transport-failure record;
3. accumulate at least 500 observed markets, 100 hypothetical fills, and four untouched weekly blocks;
4. require measured execution evidence, acceptable concentration, zero unresolved states, and a positive lower confidence bound after fees and costs;
5. keep real-money execution physically disabled.
