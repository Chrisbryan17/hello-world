import Mathlib
import ErdosGyarfas.FourRegularBound

/-!
# Small-order two-step decomposition

Two-step walks from a fixed vertex split according to whether their endpoint
is again a neighbor of the start. The internal part is canonically equivalent
to the darts of the graph induced on the neighborhood.
-/

namespace ErdosGyarfas

open Finset Fintype
open SimpleGraph

variable {V : Type*} [Fintype V] [DecidableEq V]

/-- A non-backtracking two-step walk whose endpoint is again adjacent to the
starting vertex. -/
def InsideTwoStepAt
    (J : SimpleGraph V) [DecidableRel J.Adj] (v : V) :=
  {p : TwoStepAt J v // p.2.1 ∈ J.neighborFinset v}

/-- A non-backtracking two-step walk whose endpoint lies outside the open
neighborhood of the starting vertex. -/
def OutsideTwoStepAt
    (J : SimpleGraph V) [DecidableRel J.Adj] (v : V) :=
  {p : TwoStepAt J v // p.2.1 ∉ J.neighborFinset v}

instance instFintypeInsideTwoStepAt
    (J : SimpleGraph V) [DecidableRel J.Adj] (v : V) :
    Fintype (InsideTwoStepAt J v) := by
  unfold InsideTwoStepAt
  infer_instance

instance instFintypeOutsideTwoStepAt
    (J : SimpleGraph V) [DecidableRel J.Adj] (v : V) :
    Fintype (OutsideTwoStepAt J v) := by
  unfold OutsideTwoStepAt
  infer_instance

/-- Internal two-step walks are exactly oriented edges of the graph induced on
`N(v)`. -/
def insideTwoStepEquivDart
    (J : SimpleGraph V) [DecidableRel J.Adj] (v : V) :
    InsideTwoStepAt J v ≃ (neighborGraph J v).Dart where
  toFun p :=
    { toProd := (p.1.1, ⟨p.1.2.1, p.2⟩)
      adj := by
        apply (neighborGraph_adj J v).2
        exact (J.mem_neighborFinset p.1.1.1 p.1.2.1).mp
          (Finset.mem_erase.mp p.1.2.2).2 }
  invFun d :=
    ⟨⟨d.fst,
        ⟨d.snd.1, Finset.mem_erase.mpr
          ⟨((J.mem_neighborFinset v d.snd.1).mp d.snd.2).ne.symm,
            (J.mem_neighborFinset d.fst.1 d.snd.1).mpr
              ((neighborGraph_adj J v).mp d.adj)⟩⟩⟩,
      d.snd.2⟩
  left_inv := by
    rintro ⟨⟨x, y⟩, hy⟩
    rfl
  right_inv := by
    rintro ⟨⟨x, y⟩, hxy⟩
    rfl

/-- The number of internal two-step walks is twice the number of edges in the
induced neighborhood graph. -/
theorem card_insideTwoStepAt_eq_twice_local_edges
    (J : SimpleGraph V) [DecidableRel J.Adj] (v : V) :
    Fintype.card (InsideTwoStepAt J v) =
      2 * #(neighborGraph J v).edgeFinset := by
  rw [Fintype.card_congr (insideTwoStepEquivDart J v)]
  exact (neighborGraph J v).dart_card_eq_twice_card_edges

/-- The inside and outside classes partition all non-backtracking two-step
walks. -/
theorem card_outsideTwoStepAt_eq_total_sub_inside
    (J : SimpleGraph V) [DecidableRel J.Adj] (v : V) :
    Fintype.card (OutsideTwoStepAt J v) =
      Fintype.card (TwoStepAt J v) - Fintype.card (InsideTwoStepAt J v) := by
  simpa [InsideTwoStepAt, OutsideTwoStepAt] using
    (Fintype.card_subtype_compl
      (fun p : TwoStepAt J v => p.2.1 ∈ J.neighborFinset v))

end ErdosGyarfas