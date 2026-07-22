import Mathlib
import ErdosGyarfas.EqualityGraph

/-!
# Local counting in four-regular `C₄`-free graphs

The first stage of the order bound packages non-backtracking two-step walks
from a fixed vertex as a finite sigma type. `C₄`-freeness makes the endpoint
map injective, yielding the sharp preliminary lower bound `|V| ≥ 13`.
-/

namespace ErdosGyarfas

open Finset Fintype
open SimpleGraph

variable {V : Type*} [Fintype V] [DecidableEq V]

/-- Non-backtracking two-step walks starting at `v`, represented by their
first and second vertices. -/
def TwoStepAt (J : SimpleGraph V) [DecidableRel J.Adj] (v : V) :=
  Σ x : J.neighborFinset v, (J.neighborFinset x.1).erase v

instance instFintypeTwoStepAt
    (J : SimpleGraph V) [DecidableRel J.Adj] (v : V) :
    Fintype (TwoStepAt J v) := by
  unfold TwoStepAt
  infer_instance

/-- A regular degree-four graph has exactly twelve non-backtracking two-step
walks from each vertex. -/
theorem card_twoStepAt_eq_twelve
    (J : SimpleGraph V) [DecidableRel J.Adj]
    (hReg : J.IsRegularOfDegree 4) (v : V) :
    Fintype.card (TwoStepAt J v) = 12 := by
  classical
  change Fintype.card
    (Σ x : J.neighborFinset v, (J.neighborFinset x.1).erase v) = 12
  rw [Fintype.card_sigma]
  simp only [Fintype.card_coe]
  have hvMem (x : J.neighborFinset v) : v ∈ J.neighborFinset x.1 := by
    have hxAdj : J.Adj v x.1 := (J.mem_neighborFinset v x.1).mp x.2
    exact (J.mem_neighborFinset x.1 v).mpr hxAdj.symm
  simp_rw [Finset.card_erase_of_mem (hvMem _),
    SimpleGraph.card_neighborFinset_eq_degree, hReg.degree_eq]
  rw [hReg.degree_eq v]
  norm_num

/-- Endpoint of a non-backtracking two-step walk, regarded as a vertex other
than the starting point. -/
def twoStepEndpoint
    (J : SimpleGraph V) [DecidableRel J.Adj] (v : V) :
    TwoStepAt J v → {y : V // y ≠ v}
  | ⟨_x, y⟩ => ⟨y.1, (Finset.mem_erase.mp y.2).1⟩

/-- In a `C₄`-free graph, two non-backtracking two-step walks from the same
start cannot have the same endpoint unless they are the same walk. -/
theorem twoStepEndpoint_injective
    (J : SimpleGraph V) [DecidableRel J.Adj] (v : V)
    (hC4 : NoFourCycle J) :
    Function.Injective (twoStepEndpoint J v) := by
  classical
  rintro ⟨x, y⟩ ⟨x', y'⟩ hEnd
  have hy : (y : V) = (y' : V) := congrArg Subtype.val hEnd
  have hx : (x : V) = (x' : V) := by
    by_contra hxx
    have hvx : J.Adj v x := (J.mem_neighborFinset v x.1).mp x.2
    have hxy : J.Adj x y :=
      (J.mem_neighborFinset x.1 y.1).mp (Finset.mem_erase.mp y.2).2
    have hx'y' : J.Adj x' y' :=
      (J.mem_neighborFinset x'.1 y'.1).mp (Finset.mem_erase.mp y'.2).2
    have hyx' : J.Adj y x' := by
      simpa [hy] using hx'y'.symm
    have hx'v : J.Adj x' v :=
      ((J.mem_neighborFinset v x'.1).mp x'.2).symm
    have hvy : v ≠ (y : V) := (Finset.mem_erase.mp y.2).1.symm
    exact hC4 hvx hxy hyx' hx'v hvy hxx
  have hxx : x = x' := Subtype.ext hx
  subst x'
  have hyy : y = y' := Subtype.ext hy
  subst y'
  rfl

/-- Every nonempty finite four-regular `C₄`-free simple graph has at least
thirteen vertices. -/
theorem four_regular_noFourCycle_card_ge_thirteen
    [Nonempty V] (J : SimpleGraph V) [DecidableRel J.Adj]
    (hReg : J.IsRegularOfDegree 4) (hC4 : NoFourCycle J) :
    13 ≤ Fintype.card V := by
  classical
  let v : V := Classical.arbitrary V
  have hCard : Fintype.card (TwoStepAt J v) ≤ Fintype.card {y : V // y ≠ v} :=
    Fintype.card_le_of_injective (twoStepEndpoint J v)
      (twoStepEndpoint_injective J v hC4)
  have hDomain : Fintype.card (TwoStepAt J v) = 12 :=
    card_twoStepAt_eq_twelve J hReg v
  have hCodomain : Fintype.card {y : V // y ≠ v} = Fintype.card V - 1 := by
    simp
  omega

end ErdosGyarfas