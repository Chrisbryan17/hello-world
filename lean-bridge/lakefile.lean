import Lake
open Lake DSL

package «erdos-gyarfas-bridge-check» where
  version := v!"0.8.0"

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @ "v4.29.0"

@[default_target]
lean_lib ErdosGyarfas where
  roots := #[`ErdosGyarfas.TwoThirds, `ErdosGyarfas.GraphBridge,
    `ErdosGyarfas.EqualityGraph, `ErdosGyarfas.FourRegularBound,
    `ErdosGyarfas.SmallOrder, `ErdosGyarfas.DartIncidence,
    `ErdosGyarfas.LocallyLinearClosure,
    `ErdosGyarfas.EqualityConclusion]
