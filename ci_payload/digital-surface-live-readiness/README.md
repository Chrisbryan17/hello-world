# Digital Surface Live Readiness

This checkpoint extends the checksum-pinned v5 research source with diagnostics only.

- The four observed Kinzik transfer weeks are diagnostic data and may not be reused as admissible holdouts.
- `execution-diagnostics.patch` adds deterministic one-reason attribution for both legs of every candidate.
- The workflow asserts that candidate, execution, fold, and admission outputs remain byte-identical to v5.
- Real-money execution remains disabled. Future live components must default to shadow mode and pass prospective gates.
