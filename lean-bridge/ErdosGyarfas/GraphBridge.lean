import Mathlib
import ErdosGyarfas.TwoThirds

/-!
# Finite `SimpleGraph` bridge for the two-thirds theorem

This file formalizes the graph-theoretic double count behind the sharpening of
Carr's cubic-vertex bound. It defines the cubic class `A`, its finite complement
`B`, and the bipartite crossing graph containing exactly the edges between `A`
and `B`.
-/

namespace ErdosGyarfas

open Finset
open SimpleGraph

variable {V : Type*} [Fintype V] [DecidableEq V]

/-- The vertices of degree exactly three. -/
def cubicVertices (G : SimpleGraph V) [DecidableRel G.Adj] : Finset V :=
  Finset.univ.filter fun v => G.degree v = 3

/-- The finite complement of the cubic vertices. -/
def higherVertices (G : SimpleGraph V) [DecidableRel G.Adj] : Finset V :=
  (cubicVertices G)ᶜ

/-- The subgraph consisting of edges crossing between cubic and noncubic vertices. -/
def crossingGraph (G : SimpleGraph V) [DecidableRel G.Adj] : SimpleGraph V :=
  G.between (↑(cubicVertices G) : Set V) (↑(higherVertices G) : Set V)

instance instDecidableRelCrossingGraph
    (G : SimpleGraph V) [DecidableRel G.Adj] :
    DecidableRel (crossingGraph G).Adj := by
  dsimp [crossingGraph]
  infer_instance

@[simp]
theorem mem_cubicVertices {G : SimpleGraph V} [DecidableRel G.Adj] {v : V} :
    v ∈ cubicVertices G ↔ G.degree v = 3 := by
  simp [cubicVertices]

@[simp]
theorem mem_higherVertices {G : SimpleGraph V} [DecidableRel G.Adj] {v : V} :
    v ∈ higherVertices G ↔ G.degree v ≠ 3 := by
  simp [higherVertices]

/-- Carr's structural conclusions, isolated from the minimal-counterexample proof
that produces them. -/
structure CarrStructure (G : SimpleGraph V) [DecidableRel G.Adj] : Prop where
  minDegreeThree : ∀ v, 3 ≤ G.degree v
  cubicNeighbor : ∀ v, ∃ w, G.Adj v w ∧ G.degree w = 3
  higherIndependent :
    ∀ ⦃v w : V⦄, v ∈ higherVertices G → w ∈ higherVertices G → ¬G.Adj v w

namespace CarrStructure

variable {G : SimpleGraph V} [DecidableRel G.Adj]

/-- A noncubic vertex has degree at least four under the minimum-degree hypothesis. -/
theorem four_le_degree_of_mem_higher
    (h : CarrStructure G) {v : V} (hv : v ∈ higherVertices G) :
    4 ≤ G.degree v := by
  have hne : G.degree v ≠ 3 := mem_higherVertices.mp hv
  have hmin := h.minDegreeThree v
  omega

/-- Every neighbor of a higher vertex is cubic, since the higher class is independent. -/
theorem neighbor_mem_cubic_of_mem_higher
    (h : CarrStructure G) {v w : V} (hv : v ∈ higherVertices G)
    (hvw : G.Adj v w) :
    w ∈ cubicVertices G := by
  by_contra hw
  have hwHigh : w ∈ higherVertices G := by
    simpa [higherVertices] using hw
  exact h.higherIndependent hv hwHigh hvw

/-- A higher vertex keeps every incident edge in the crossing graph. -/
theorem neighborFinset_crossing_eq_of_mem_higher
    (h : CarrStructure G) {v : V} (hv : v ∈ higherVertices G) :
    (crossingGraph G).neighborFinset v = G.neighborFinset v := by
  ext w
  simp only [SimpleGraph.mem_neighborFinset]
  constructor
  · rintro ⟨hvw, _⟩
    exact hvw
  · intro hvw
    have hw : w ∈ cubicVertices G := h.neighbor_mem_cubic_of_mem_higher hv hvw
    exact ⟨hvw, Or.inr ⟨by simpa using hv, by simpa using hw⟩⟩

/-- A higher vertex has the same degree in the crossing graph as in the original graph. -/
theorem crossing_degree_eq_of_mem_higher
    (h : CarrStructure G) {v : V} (hv : v ∈ higherVertices G) :
    (crossingGraph G).degree v = G.degree v := by
  change #((crossingGraph G).neighborFinset v) = #(G.neighborFinset v)
  exact congrArg Finset.card (h.neighborFinset_crossing_eq_of_mem_higher hv)

/-- A higher vertex has crossing degree at least four. -/
theorem four_le_crossing_degree_of_mem_higher
    (h : CarrStructure G) {v : V} (hv : v ∈ higherVertices G) :
    4 ≤ (crossingGraph G).degree v := by
  rw [h.crossing_degree_eq_of_mem_higher hv]
  exact h.four_le_degree_of_mem_higher hv

/-- A cubic vertex has at most two neighbors across the cubic/noncubic cut. -/
theorem crossing_degree_le_two_of_mem_cubic
    (h : CarrStructure G) {v : V} (hv : v ∈ cubicVertices G) :
    (crossingGraph G).degree v ≤ 2 := by
  obtain ⟨w, hvw, hwDegree⟩ := h.cubicNeighbor v
  have hwCubic : w ∈ cubicVertices G := mem_cubicVertices.mpr hwDegree
  have hwNeighbor : w ∈ G.neighborFinset v := by
    simpa using hvw
  have hsubset :
      (crossingGraph G).neighborFinset v ⊆ (G.neighborFinset v).erase w := by
    intro x hx
    have hxCross : (crossingGraph G).Adj v x := by
      simpa using hx
    have hxG : G.Adj v x := hxCross.1
    have hxHigh : x ∈ higherVertices G := by
      rcases hxCross.2 with hxVH | hxHV
      · simpa using hxVH.2
      · have hvHigh : v ∈ higherVertices G := by simpa using hxHV.1
        exact False.elim ((by simpa [higherVertices] using hv :
          v ∉ higherVertices G) hvHigh)
    have hxne : x ≠ w := by
      intro hxw
      subst x
      exact (by simpa [higherVertices] using hwCubic : w ∉ higherVertices G) hxHigh
    exact Finset.mem_erase.mpr ⟨hxne, by simpa using hxG⟩
  have hcard := Finset.card_le_card hsubset
  rw [Finset.card_erase_of_mem hwNeighbor] at hcard
  simp only [SimpleGraph.card_neighborFinset_eq_degree] at hcard
  have hvDegree : G.degree v = 3 := mem_cubicVertices.mp hv
  omega

end CarrStructure

/-- The crossing graph is bipartite with the cubic and higher classes as its two sides. -/
theorem crossingGraph_isBipartiteWith
    (G : SimpleGraph V) [DecidableRel G.Adj] :
    (crossingGraph G).IsBipartiteWith
      (↑(cubicVertices G) : Set V) (↑(higherVertices G) : Set V) := by
  apply SimpleGraph.between_isBipartiteWith
  refine Set.disjoint_left.mpr ?_
  intro v hvCubic hvHigher
  have hvCubic' : v ∈ cubicVertices G := hvCubic
  have hvHigher' : v ∈ higherVertices G := hvHigher
  exact (by simpa [higherVertices] using hvCubic' : v ∉ higherVertices G) hvHigher'

/-- End-to-end finite-simple-graph form of the two-thirds theorem. -/
theorem carr_two_thirds
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (h : CarrStructure G) :
    2 * Fintype.card V ≤ 3 * #(cubicVertices G) := by
  let A : Finset V := cubicVertices G
  let B : Finset V := higherVertices G
  let H : SimpleGraph V := crossingGraph G

  have hBip : H.IsBipartiteWith (↑A : Set V) (↑B : Set V) := by
    simpa [A, B, H] using crossingGraph_isBipartiteWith G

  have hDegreeSum :
      ∑ v ∈ A, H.degree v = ∑ v ∈ B, H.degree v :=
    SimpleGraph.isBipartiteWith_sum_degrees_eq hBip

  have hLower : 4 * #B ≤ ∑ v ∈ B, H.degree v := by
    have hPointwise : ∑ _v ∈ B, 4 ≤ ∑ v ∈ B, H.degree v := by
      apply Finset.sum_le_sum
      intro v hv
      simpa [B, H] using h.four_le_crossing_degree_of_mem_higher
        (G := G) (by simpa [B] using hv)
    simpa [Nat.mul_comm] using hPointwise

  have hUpperA : ∑ v ∈ A, H.degree v ≤ 2 * #A := by
    have hPointwise : ∑ v ∈ A, H.degree v ≤ ∑ _v ∈ A, 2 := by
      apply Finset.sum_le_sum
      intro v hv
      simpa [A, H] using h.crossing_degree_le_two_of_mem_cubic
        (G := G) (by simpa [A] using hv)
    simpa [Nat.mul_comm] using hPointwise

  have hUpperB : ∑ v ∈ B, H.degree v ≤ 2 * #A := by
    rw [← hDegreeSum]
    exact hUpperA

  have hPartition : Fintype.card V = #A + #B := by
    simp [A, B, higherVertices]

  exact two_thirds_from_partition_and_cross_edges
    #A #B (∑ v ∈ B, H.degree v) (Fintype.card V)
    hPartition hLower hUpperB

end ErdosGyarfas
