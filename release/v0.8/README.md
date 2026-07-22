# Erdős–Gyárfás equality-case formalization v0.8

This release packages the exact Lean source tree used to verify the direct equality-case lower bound.

## Main verified conclusions

For every finite nonempty four-regular `C₄`-free simple graph `J`,

```lean
ErdosGyarfas.four_regular_noFourCycle_card_ge_fifteen_direct
```

proves

```text
15 ≤ Fintype.card V.
```

For a nonempty equality-incidence right class `B`,

```lean
ErdosGyarfas.EqualityIncidence.auxiliaryGraph_card_ge_fifteen
ErdosGyarfas.EqualityIncidence.equality_case_forty_five_direct
```

prove

```text
15 ≤ |B|
45 ≤ |A| + |B|      when |A| = 2|B|.
```

## Archive contents

The generated archive contains:

- the complete tracked `lean-bridge/` source and pinned project configuration;
- the equality-case and bridge CI workflows;
- this release documentation and the detailed proof note;
- `SOURCE_METADATA.json` identifying the exact commit and branch;
- `CI/CI_EVIDENCE.json` identifying the successful verification run and gate result;
- `CI/PR_SNAPSHOT.json` when GitHub CLI access is available during packaging;
- `MANIFEST.sha256`, covering every archive member except the manifest itself;
- `release/v0.8/verify_archive.py`, the independent content verifier.

## Verify an extracted archive

From the archive's top-level directory:

```bash
python3 release/v0.8/verify_archive.py .
```

The verifier rejects missing files, unexpected files, malformed manifest entries, and any SHA-256 mismatch.

## Rebuild the release

From an exact checkout of the release commit:

```bash
bash release/v0.8/build_release.sh ./dist/v0.8
```

The builder stages only tracked files through `git archive`, creates the manifest, emits a deterministic ZIP, extracts it into a clean directory, and runs the independent verifier before writing the outer ZIP checksum.

## Re-run Lean verification

```bash
cd lean-bridge
lake update
lake exe cache get
lake build
lake env lean BridgeTest.lean
lake env lean EqualityTest.lean
lake env lean Verify.lean
```

The CI additionally rejects source occurrences of `sorry` or `admit` and rejects any `sorryAx` dependency printed by `Verify.lean`.
