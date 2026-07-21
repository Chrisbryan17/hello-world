import Lake
open Lake DSL

package «counting-kernel-check» where
  version := v!"0.1.0"

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @ "v4.29.0"

@[default_target]
lean_lib CountingKernel where
  roots := #[`CountingKernel.Bounds, `CountingKernel.Equality]
