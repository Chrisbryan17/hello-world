import Mathlib
import ErdosGyarfas.GraphBridge

/-!
# Equality-case auxiliary graph

This module isolates the finite incidence structure produced in the equality
case. The left vertices represent cubic vertices and the right vertices
represent the higher-degree vertices. Every left vertex has exactly two right
neighbors, every right vertex has exactly four left neighbors, and no two left
vertices determine the same pair of right endpoints.

The development is compiled against Lean 4.29.0 and mathlib v4.29.0.
-/

namespace ErdosGyarfas

open Finset Fintype
open SimpleGraph

/-- An explicit four-cycle predicate using only the two opposite-vertex
inequalities; adjacency supplies all consecutive inequalities in a simple graph. -/
def NoFourCycle {V : Type*} (G : SimpleGraph V) : Prop :=
  ∀ ⦃v₀ v₁ v₂ v₃ : V⦄,
    G.Adj v₀ v₁ → G.Adj v₁ v₂ → G.Adj v₂ v₃ → G.Adj v₃ v₀ →
    v₀ ≠ v₂ → v₁ ≠ v₃ → False

/-- Finite bipartite incidence data for the auxiliary graph. -/
structure EqualityIncidence (A B : Type*) [Fintype A] [Fintype B] where
  Inc : A → B → Prop
  decidableInc : DecidableRel Inc
  leftDegreeTwo : ∀ a, Fintype.card {b // Inc a b} = 2
  rightDegreeFour : ∀ b, Fintype.card {a // Inc a b} = 4
  pairUnique :
    ∀ ⦃a a' : A⦄ ⦃b c : B⦄,
      b ≠ c → Inc a b → Inc a c → Inc a' b → Inc a' c → a = a'
  noAlternatingSquare :
    ∀ ⦃b₀ b₁ b₂ b₃ : B⦄,
      b₀ ≠ b₂ → b₁ ≠ b₃ →
      (∃ a, Inc a b₀ ∧ Inc a b₁) →
      (∃ a, Inc a b₁ ∧ Inc a b₂) →
      (∃ a, Inc a b₂ ∧ Inc a b₃) →
      (∃ a, Inc a b₃ ∧ Inc a b₀) → False

namespace EqualityIncidence

variable {A B : Type*} [Fintype A] [Fintype B] [DecidableEq B]

instance (S : EqualityIncidence A B) : DecidableRel S.Inc := S.decidableInc

/-- The finite set of right endpoints incident with a left vertex. -/
def leftNeighbors (S : EqualityIncidence A B) (a : A) : Finset B :=
  Finset.univ.filter (S.Inc a)

/-- The finite set of left incidences at a right vertex. -/
def rightNeighbors (S : EqualityIncidence A B) (b : B) : Finset A :=
  Finset.univ.filter (fun a => S.Inc a b)

@[simp]
theorem mem_leftNeighbors (S : EqualityIncidence A B) {a : A} {b : B} :
    b ∈ S.leftNeighbors a ↔ S.Inc a b := by
  simp [leftNeighbors]

@[simp]
theorem mem_rightNeighbors (S : EqualityIncidence A B) {a : A} {b : B} :
    a ∈ S.rightNeighbors b ↔ S.Inc a b := by
  simp [rightNeighbors]

@[simp]
theorem card_leftNeighbors (S : EqualityIncidence A B) (a : A) :
    #(S.leftNeighbors a) = 2 := by
  unfold leftNeighbors
  rw [← Fintype.card_subtype]
  exact S.leftDegreeTwo a

@[simp]
theorem card_rightNeighbors (S : EqualityIncidence A B) (b : B) :
    #(S.rightNeighbors b) = 4 := by
  unfold rightNeighbors
  rw [← Fintype.card_subtype]
  exact S.rightDegreeFour b

/-- In a two-element incidence set, fixing one endpoint leaves a unique other endpoint. -/
theorem existsUnique_other (S : EqualityIncidence A B)
    {a : A} {b : B} (hab : S.Inc a b) :
    ∃! c : B, c ≠ b ∧ S.Inc a c := by
  classical
  let N := S.leftNeighbors a
  have hbN : b ∈ N := by simpa [N] using hab
  have hcard : #(N.erase b) = 1 := by
    rw [Finset.card_erase_of_mem hbN]
    simp [N]
  obtain ⟨c, hc⟩ := Finset.card_eq_one.mp hcard
  refine ⟨c, ?_, ?_⟩
  · have hcMem : c ∈ N.erase b := by simp [hc]
    exact ⟨(Finset.mem_erase.mp hcMem).1, by
      exact S.mem_leftNeighbors.mp (Finset.mem_erase.mp hcMem).2⟩
  · intro d hd
    have hdMem : d ∈ N.erase b :=
      Finset.mem_erase.mpr ⟨hd.1, S.mem_leftNeighbors.mpr hd.2⟩
    simpa [hc] using hdMem

/-- The other right endpoint of a left incidence. -/
noncomputable def other (S : EqualityIncidence A B)
    (a : A) (b : B) (hab : S.Inc a b) : B :=
  Classical.choose (S.existsUnique_other hab)

@[simp]
theorem other_ne (S : EqualityIncidence A B)
    (a : A) (b : B) (hab : S.Inc a b) :
    S.other a b hab ≠ b :=
  (Classical.choose_spec (S.existsUnique_other hab)).1.1

@[simp]
theorem inc_other (S : EqualityIncidence A B)
    (a : A) (b : B) (hab : S.Inc a b) :
    S.Inc a (S.other a b hab) :=
  (Classical.choose_spec (S.existsUnique_other hab)).1.2

/-- The simple auxiliary graph on the right vertex class. -/
def auxiliaryGraph (S : EqualityIncidence A B) : SimpleGraph B where
  Adj b c := b ≠ c ∧ ∃ a, S.Inc a b ∧ S.Inc a c
  symm b c h := ⟨h.1.symm, by
    obtain ⟨a, hab, hac⟩ := h.2
    exact ⟨a, hac, hab⟩⟩
  loopless := ⟨by
    intro b h
    exact h.1 rfl⟩

instance (S : EqualityIncidence A B) : DecidableRel S.auxiliaryGraph.Adj := by
  intro b c
  change Decidable (b ≠ c ∧ ∃ a, S.Inc a b ∧ S.Inc a c)
  infer_instance

@[simp]
theorem auxiliaryGraph_adj (S : EqualityIncidence A B) {b c : B} :
    S.auxiliaryGraph.Adj b c ↔ b ≠ c ∧ ∃ a, S.Inc a b ∧ S.Inc a c :=
  Iff.rfl

/-- Incidences at `b` are in bijection with neighbors of `b` in the auxiliary graph. -/
noncomputable def incidenceNeighborEquiv (S : EqualityIncidence A B) (b : B) :
    {a // S.Inc a b} ≃ S.auxiliaryGraph.neighborSet b := by
  let f : {a // S.Inc a b} → S.auxiliaryGraph.neighborSet b := fun a =>
    ⟨S.other a.1 b a.2, by
      change S.other a.1 b a.2 ≠ b ∧
        ∃ a', S.Inc a' b ∧ S.Inc a' (S.other a.1 b a.2)
      exact ⟨S.other_ne a.1 b a.2, ⟨a.1, a.2, S.inc_other a.1 b a.2⟩⟩⟩
  refine Equiv.ofBijective f ⟨?_, ?_⟩
  · intro a a' haa'
    apply Subtype.ext
    have hOther : S.other a.1 b a.2 = S.other a'.1 b a'.2 :=
      congrArg Subtype.val haa'
    apply S.pairUnique (S.other_ne a.1 b a.2).symm
      a.2 (S.inc_other a.1 b a.2) a'.2
    simpa [hOther] using S.inc_other a'.1 b a'.2
  · intro c
    have hcAdj := S.auxiliaryGraph_adj.mp c.2
    rcases hcAdj with ⟨hbc, a, hab, hac⟩
    let a' : {a // S.Inc a b} := ⟨a, hab⟩
    refine ⟨a', Subtype.ext ?_⟩
    dsimp [f, a']
    exact ((Classical.choose_spec (S.existsUnique_other hab)).2 c.1
      ⟨hbc.symm, hac⟩).symm

/-- The auxiliary graph is 4-regular. -/
theorem auxiliaryGraph_four_regular (S : EqualityIncidence A B) :
    S.auxiliaryGraph.IsRegularOfDegree 4 := by
  intro b
  rw [← SimpleGraph.card_neighborSet_eq_degree]
  rw [← Fintype.card_congr (S.incidenceNeighborEquiv b)]
  exact S.rightDegreeFour b

/-- The alternating-square exclusion makes the auxiliary graph `C₄`-free. -/
theorem auxiliaryGraph_noFourCycle (S : EqualityIncidence A B) :
    NoFourCycle S.auxiliaryGraph := by
  intro b₀ b₁ b₂ b₃ h01 h12 h23 h30 h02 h13
  apply S.noAlternatingSquare h02 h13
  · exact (S.auxiliaryGraph_adj.mp h01).2
  · exact (S.auxiliaryGraph_adj.mp h12).2
  · exact (S.auxiliaryGraph_adj.mp h23).2
  · exact (S.auxiliaryGraph_adj.mp h30).2

end EqualityIncidence

/-- A graph-side certificate for the local order argument. This is temporarily
separated from the incidence construction so that the generic 4-regular,
`C₄`-free lower bound can be verified independently. -/
structure FourRegularNoFourCycleCertificate {V : Type*} [Fintype V]
    (J : SimpleGraph V) [DecidableRel J.Adj] : Prop where
  regular : J.IsRegularOfDegree 4
  noFourCycle : NoFourCycle J
  localThirteen : 13 ≤ Fintype.card V
  smallOrderTriangleIncidence :
    Fintype.card V ≤ 14 → ∃ T : ℕ, 2 * Fintype.card V = 3 * T

/-- The graph-theoretic 15-vertex conclusion, with the local combinatorial
certificate made explicit. -/
theorem four_regular_noFourCycle_card_ge_fifteen
    {V : Type*} [Fintype V] (J : SimpleGraph V) [DecidableRel J.Adj]
    (h : FourRegularNoFourCycleCertificate J) :
    15 ≤ Fintype.card V := by
  by_contra hNot
  have hAtLeastThirteen : 13 ≤ Fintype.card V := h.localThirteen
  have hAtMostFourteen : Fintype.card V ≤ 14 := by omega
  obtain ⟨T, hIncidence⟩ := h.smallOrderTriangleIncidence hAtMostFourteen
  have hCases : Fintype.card V = 13 ∨ Fintype.card V = 14 := by omega
  rcases hCases with h13 | h14 <;> omega

/-- End-to-end 45-vertex arithmetic conclusion once the equality incidence
system and the local 15-vertex certificate for its auxiliary graph are supplied. -/
theorem equality_case_forty_five
    {A B : Type*} [Fintype A] [Fintype B] [DecidableEq B]
    (S : EqualityIncidence A B)
    (hCard : Fintype.card A = 2 * Fintype.card B)
    (hLocal : FourRegularNoFourCycleCertificate S.auxiliaryGraph) :
    45 ≤ Fintype.card A + Fintype.card B := by
  have hAux : 15 ≤ Fintype.card B :=
    four_regular_noFourCycle_card_ge_fifteen S.auxiliaryGraph hLocal
  omega

end ErdosGyarfas
