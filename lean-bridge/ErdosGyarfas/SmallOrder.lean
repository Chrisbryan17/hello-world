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

/-- Vertices outside the closed neighborhood of `v`. -/
def outsideVertices
    (J : SimpleGraph V) [DecidableRel J.Adj] (v : V) : Finset V :=
  (Finset.univ.erase v) \ J.neighborFinset v

/-- Every neighbor of `v` belongs to `univ.erase v`. -/
theorem neighborFinset_subset_univ_erase
    (J : SimpleGraph V) [DecidableRel J.Adj] (v : V) :
    J.neighborFinset v ⊆ Finset.univ.erase v := by
  intro x hx
  have hvx : J.Adj v x := (J.mem_neighborFinset v x).mp hx
  exact Finset.mem_erase.mpr ⟨hvx.ne.symm, Finset.mem_univ x⟩

/-- In a four-regular graph, precisely `|V| - 5` vertices lie outside the
closed neighborhood of a fixed vertex. -/
theorem card_outsideVertices
    (J : SimpleGraph V) [DecidableRel J.Adj]
    (hReg : J.IsRegularOfDegree 4) (v : V) :
    #(outsideVertices J v) = Fintype.card V - 5 := by
  rw [outsideVertices,
    Finset.card_sdiff_of_subset (neighborFinset_subset_univ_erase J v),
    Finset.card_erase_of_mem (Finset.mem_univ v), Finset.card_univ,
    SimpleGraph.card_neighborFinset_eq_degree, hReg.degree_eq v]
  omega

/-- Endpoint of an exterior two-step walk, placed in the finite set outside the
closed neighborhood. -/
def outsideTwoStepEndpoint
    (J : SimpleGraph V) [DecidableRel J.Adj] (v : V) :
    OutsideTwoStepAt J v → outsideVertices J v
  | p =>
      ⟨p.1.2.1, Finset.mem_sdiff.mpr
        ⟨Finset.mem_erase.mpr
          ⟨(Finset.mem_erase.mp p.1.2.2).1, Finset.mem_univ _⟩,
          p.2⟩⟩

/-- `C₄`-freeness makes the exterior endpoint map injective. -/
theorem outsideTwoStepEndpoint_injective
    (J : SimpleGraph V) [DecidableRel J.Adj] (v : V)
    (hC4 : NoFourCycle J) :
    Function.Injective (outsideTwoStepEndpoint J v) := by
  intro p q hpq
  apply Subtype.ext
  apply twoStepEndpoint_injective J v hC4
  apply Subtype.ext
  exact congrArg Subtype.val hpq

/-- Exterior two-step walks fit injectively into the vertices outside the
closed neighborhood. -/
theorem card_outsideTwoStepAt_le
    (J : SimpleGraph V) [DecidableRel J.Adj]
    (hReg : J.IsRegularOfDegree 4) (hC4 : NoFourCycle J) (v : V) :
    Fintype.card (OutsideTwoStepAt J v) ≤ Fintype.card V - 5 := by
  have hCard := Fintype.card_le_of_injective (outsideTwoStepEndpoint J v)
    (outsideTwoStepEndpoint_injective J v hC4)
  rw [Fintype.card_coe, card_outsideVertices J hReg v] at hCard
  exact hCard

/-- At order at most fourteen, at least three of the twelve two-step walks from
each vertex end back inside its neighborhood. -/
theorem three_le_card_insideTwoStepAt
    (J : SimpleGraph V) [DecidableRel J.Adj]
    (hReg : J.IsRegularOfDegree 4) (hC4 : NoFourCycle J)
    (hOrder : Fintype.card V ≤ 14) (v : V) :
    3 ≤ Fintype.card (InsideTwoStepAt J v) := by
  have hOutside := card_outsideTwoStepAt_le J hReg hC4 v
  have hTotal := card_twoStepAt_eq_twelve J hReg v
  have hPartition := card_outsideTwoStepAt_eq_total_sub_inside J v
  have hInsideLe : Fintype.card (InsideTwoStepAt J v) ≤
      Fintype.card (TwoStepAt J v) :=
    Fintype.card_subtype_le
      (fun p : TwoStepAt J v => p.2.1 ∈ J.neighborFinset v)
  omega

/-- Consequently, every neighborhood contains exactly two edges whenever a
four-regular `C₄`-free graph has order at most fourteen. -/
theorem neighborGraph_card_edges_eq_two_of_card_le_fourteen
    (J : SimpleGraph V) [DecidableRel J.Adj]
    (hReg : J.IsRegularOfDegree 4) (hC4 : NoFourCycle J)
    (hOrder : Fintype.card V ≤ 14) (v : V) :
    #(neighborGraph J v).edgeFinset = 2 := by
  have hInside := three_le_card_insideTwoStepAt J hReg hC4 hOrder v
  have hDarts := card_insideTwoStepAt_eq_twice_local_edges J v
  have hUpper := neighborGraph_card_edges_le_two J hReg hC4 v
  omega

end ErdosGyarfas