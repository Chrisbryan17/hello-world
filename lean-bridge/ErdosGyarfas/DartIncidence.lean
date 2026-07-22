import Mathlib
import ErdosGyarfas.SmallOrder

/-!
# Dart/common-neighbor double counting

For a directed edge `d = x → y`, a common neighbor is a vertex adjacent to
both `x` and `y`. At order at most fourteen, every vertex contributes four
such dart incidences. `C₄`-freeness allows at most one common neighbor per
dart. Since a four-regular graph has exactly `4|V|` darts, equality forces
exactly one common neighbor for every dart.
-/

namespace ErdosGyarfas

open Finset Fintype
open SimpleGraph

variable {V : Type*} [Fintype V] [DecidableEq V]

/-- A vertex is a common neighbor of the two endpoints of a dart. -/
def CommonNeighborRel (J : SimpleGraph V) (v : V) (d : J.Dart) : Prop :=
  J.Adj v d.fst ∧ J.Adj v d.snd

instance instDecidableCommonNeighborRel
    (J : SimpleGraph V) [DecidableRel J.Adj] :
    ∀ v d, Decidable (CommonNeighborRel J v d) := by
  intro v d
  unfold CommonNeighborRel
  infer_instance

/-- Darts whose endpoints are both adjacent to `v`. -/
def commonDartsAt
    (J : SimpleGraph V) [DecidableRel J.Adj] (v : V) : Finset J.Dart :=
  Finset.univ.filter (CommonNeighborRel J v)

/-- Common neighbors of a fixed dart. -/
def commonNeighborsOfDart
    (J : SimpleGraph V) [DecidableRel J.Adj] (d : J.Dart) : Finset V :=
  Finset.univ.filter (fun v => CommonNeighborRel J v d)

/-- Internal two-step walks based at `v` are the same as global darts having
`v` as a common neighbor. -/
def insideTwoStepEquivCommonDart
    (J : SimpleGraph V) [DecidableRel J.Adj] (v : V) :
    InsideTwoStepAt J v ≃ {d : J.Dart // CommonNeighborRel J v d} where
  toFun p :=
    ⟨{ toProd := (p.1.1.1, p.1.2.1)
       adj := (J.mem_neighborFinset p.1.1.1 p.1.2.1).mp
         (Finset.mem_erase.mp p.1.2.2).2 },
      ⟨(J.mem_neighborFinset v p.1.1.1).mp p.1.1.2,
        (J.mem_neighborFinset v p.1.2.1).mp p.2⟩⟩
  invFun d :=
    ⟨⟨⟨d.1.fst, (J.mem_neighborFinset v d.1.fst).mpr d.2.1⟩,
        ⟨d.1.snd, Finset.mem_erase.mpr
          ⟨d.2.2.ne.symm,
            (J.mem_neighborFinset d.1.fst d.1.snd).mpr d.1.adj⟩⟩⟩,
      (J.mem_neighborFinset v d.1.snd).mpr d.2.2⟩
  left_inv := by
    rintro ⟨⟨x, y⟩, hy⟩
    rfl
  right_inv := by
    rintro ⟨⟨⟨x, y⟩, hxy⟩, hv⟩
    rfl

/-- At order at most fourteen, every vertex is a common neighbor of exactly
four darts. -/
theorem card_commonDartsAt_eq_four
    (J : SimpleGraph V) [DecidableRel J.Adj]
    (hReg : J.IsRegularOfDegree 4) (hC4 : NoFourCycle J)
    (hOrder : Fintype.card V ≤ 14) (v : V) :
    #(commonDartsAt J v) = 4 := by
  have hSubtype : #(commonDartsAt J v) =
      Fintype.card {d : J.Dart // CommonNeighborRel J v d} := by
    simpa [commonDartsAt] using
      (Fintype.card_subtype (fun d : J.Dart => CommonNeighborRel J v d)).symm
  calc
    #(commonDartsAt J v) =
        Fintype.card {d : J.Dart // CommonNeighborRel J v d} := hSubtype
    _ = Fintype.card (InsideTwoStepAt J v) :=
      (Fintype.card_congr (insideTwoStepEquivCommonDart J v)).symm
    _ = 2 * #(neighborGraph J v).edgeFinset :=
      card_insideTwoStepAt_eq_twice_local_edges J v
    _ = 4 := by
      rw [neighborGraph_card_edges_eq_two_of_card_le_fourteen
        J hReg hC4 hOrder v]

/-- Two distinct common neighbors of one dart would form a four-cycle. -/
theorem card_commonNeighborsOfDart_le_one
    (J : SimpleGraph V) [DecidableRel J.Adj]
    (hC4 : NoFourCycle J) (d : J.Dart) :
    #(commonNeighborsOfDart J d) ≤ 1 := by
  rw [Finset.card_le_one]
  intro v hv w hw
  simp only [commonNeighborsOfDart, Finset.mem_filter, Finset.mem_univ,
    true_and, CommonNeighborRel] at hv hw
  by_contra hvw
  exact hC4 hv.1 hw.1.symm hw.2 hv.2.symm hvw d.fst_ne_snd

/-- A four-regular finite graph has four darts per vertex. -/
theorem dart_card_eq_four_mul_vertices
    (J : SimpleGraph V) [DecidableRel J.Adj]
    (hReg : J.IsRegularOfDegree 4) :
    Fintype.card J.Dart = Fintype.card V * 4 := by
  rw [J.dart_card_eq_sum_degrees]
  simp_rw [hReg.degree_eq]
  simp

/-- The total number of common-neighbor/dart incidences equals the number of
darts in the small-order case. -/
theorem sum_card_commonNeighborsOfDart_eq_card_darts
    (J : SimpleGraph V) [DecidableRel J.Adj]
    (hReg : J.IsRegularOfDegree 4) (hC4 : NoFourCycle J)
    (hOrder : Fintype.card V ≤ 14) :
    (∑ d : J.Dart, #(commonNeighborsOfDart J d)) = Fintype.card J.Dart := by
  have hDouble := Finset.sum_card_bipartiteAbove_eq_sum_card_bipartiteBelow
    (r := CommonNeighborRel J)
    (s := (Finset.univ : Finset V))
    (t := (Finset.univ : Finset J.Dart))
  calc
    (∑ d : J.Dart, #(commonNeighborsOfDart J d)) =
        ∑ v : V, #(commonDartsAt J v) := by
          simpa [commonNeighborsOfDart, commonDartsAt,
            Finset.bipartiteBelow, Finset.bipartiteAbove] using hDouble.symm
    _ = ∑ _v : V, 4 := by
          apply Finset.sum_congr rfl
          intro v hv
          exact card_commonDartsAt_eq_four J hReg hC4 hOrder v
    _ = Fintype.card V * 4 := by simp
    _ = Fintype.card J.Dart := (dart_card_eq_four_mul_vertices J hReg).symm

/-- In the small-order case, every dart has exactly one common neighbor. -/
theorem card_commonNeighborsOfDart_eq_one
    (J : SimpleGraph V) [DecidableRel J.Adj]
    (hReg : J.IsRegularOfDegree 4) (hC4 : NoFourCycle J)
    (hOrder : Fintype.card V ≤ 14) (d : J.Dart) :
    #(commonNeighborsOfDart J d) = 1 := by
  classical
  let f : J.Dart → ℕ := fun e => #(commonNeighborsOfDart J e)
  have hTotal : (∑ e : J.Dart, f e) = Fintype.card J.Dart := by
    simpa [f] using sum_card_commonNeighborsOfDart_eq_card_darts J hReg hC4 hOrder
  have hLe : ∀ e : J.Dart, f e ≤ 1 := by
    intro e
    exact card_commonNeighborsOfDart_le_one J hC4 e
  have hdMem : d ∈ (Finset.univ : Finset J.Dart) := Finset.mem_univ d
  have hRest : (∑ e ∈ (Finset.univ.erase d), f e) ≤
      #(Finset.univ.erase d) := by
    calc
      (∑ e ∈ (Finset.univ.erase d), f e) ≤
          ∑ _e ∈ (Finset.univ.erase d), 1 := by
            apply Finset.sum_le_sum
            intro e he
            exact hLe e
      _ = #(Finset.univ.erase d) := by simp
  have hEraseCard : #(Finset.univ.erase d) = Fintype.card J.Dart - 1 := by
    simp
  have hSplit : (∑ e ∈ (Finset.univ.erase d), f e) + f d =
      ∑ e : J.Dart, f e := by
    simpa using Finset.sum_erase_add (s := (Finset.univ : Finset J.Dart))
      (f := f) hdMem
  have hfdLe : f d ≤ 1 := hLe d
  have hDartPos : 0 < Fintype.card J.Dart :=
    Fintype.card_pos_iff.mpr ⟨d⟩
  have hfdEq : f d = 1 := by
    omega
  simpa [f] using hfdEq

end ErdosGyarfas