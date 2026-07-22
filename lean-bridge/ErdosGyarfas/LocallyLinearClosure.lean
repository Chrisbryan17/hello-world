import Mathlib
import ErdosGyarfas.DartIncidence

/-!
# Locally-linear closure of the order bound

At order at most fourteen, every dart has exactly one common neighbor. This
makes the graph locally linear: every edge belongs to exactly one triangle.
The locally-linear triangle count and the four-regular handshaking identity
then imply `2|V| = 3T`, which is incompatible with `|V| = 13` or `14`.
-/

namespace ErdosGyarfas

open Finset Fintype
open SimpleGraph

variable {V : Type*} [Fintype V] [DecidableEq V]

/-- In a three-clique containing two distinct prescribed vertices, there is a
unique third vertex. -/
theorem existsUnique_third_vertex_of_is3Clique
    {J : SimpleGraph V} [DecidableRel J.Adj]
    {s : Finset V} (hs : J.IsNClique 3 s)
    {x y : V} (hx : x ∈ s) (hy : y ∈ s) (hxy : x ≠ y) :
    ∃! z : V, z ∈ s ∧ z ≠ x ∧ z ≠ y := by
  classical
  have hPairSubset : ({x, y} : Finset V) ⊆ s := by
    simp [hx, hy]
  have hDiffCard : #(s \ {x, y}) = 1 := by
    rw [Finset.card_sdiff_of_subset hPairSubset, hs.card_eq,
      Finset.card_pair hxy]
  obtain ⟨z, hzEq⟩ := Finset.card_eq_one.mp hDiffCard
  refine ⟨z, ?_, ?_⟩
  · have hz : z ∈ s \ {x, y} := by
      rw [hzEq]
      simp
    simp only [Finset.mem_sdiff, Finset.mem_insert, Finset.mem_singleton,
      not_or] at hz
    exact ⟨hz.1, hz.2.1, hz.2.2⟩
  · intro w hw
    have hwDiff : w ∈ s \ {x, y} := by
      simp [hw.1, hw.2.1, hw.2.2]
    rw [hzEq] at hwDiff
    simpa using hwDiff

/-- A `C₄`-free graph has edge-disjoint triangles. -/
theorem edgeDisjointTriangles_of_noFourCycle
    (J : SimpleGraph V) [DecidableRel J.Adj]
    (hC4 : NoFourCycle J) :
    J.EdgeDisjointTriangles := by
  classical
  rw [SimpleGraph.EdgeDisjointTriangles]
  intro s hs t ht hst
  rintro x ⟨hxs, hxt⟩ y ⟨hys, hyt⟩
  by_contra hxy
  have hsClique : J.IsNClique 3 s := hs
  have htClique : J.IsNClique 3 t := ht
  obtain ⟨z, hz, _hzUnique⟩ :=
    existsUnique_third_vertex_of_is3Clique hsClique hxs hys hxy
  obtain ⟨w, hw, _hwUnique⟩ :=
    existsUnique_third_vertex_of_is3Clique htClique hxt hyt hxy
  have hxyAdj : J.Adj x y := hsClique.isClique hxs hys hxy
  let d : J.Dart := ⟨(x, y), hxyAdj⟩
  have hzCommon : z ∈ commonNeighborsOfDart J d := by
    simp only [commonNeighborsOfDart, Finset.mem_filter, Finset.mem_univ,
      true_and, CommonNeighborRel]
    exact ⟨hsClique.isClique hz.1 hxs hz.2.1,
      hsClique.isClique hz.1 hys hz.2.2⟩
  have hwCommon : w ∈ commonNeighborsOfDart J d := by
    simp only [commonNeighborsOfDart, Finset.mem_filter, Finset.mem_univ,
      true_and, CommonNeighborRel]
    exact ⟨htClique.isClique hw.1 hxt hw.2.1,
      htClique.isClique hw.1 hyt hw.2.2⟩
  have hzw : z = w := by
    have hle := card_commonNeighborsOfDart_le_one J hC4 d
    rw [Finset.card_le_one] at hle
    exact hle z hzCommon w hwCommon
  have hTripleCard : #({x, y, z} : Finset V) = 3 := by
    simp [hxy, hz.2.1, hz.2.2]
  have hsTriple : s = {x, y, z} := by
    symm
    apply Finset.eq_of_subset_of_card_le
    · simp [hxs, hys, hz.1]
    · rw [hTripleCard, hsClique.card_eq]
  have htTriple : t = {x, y, z} := by
    subst w
    symm
    apply Finset.eq_of_subset_of_card_le
    · simp [hxt, hyt, hw.1]
    · rw [hTripleCard, htClique.card_eq]
  exact hst (hsTriple.trans htTriple.symm)

/-- In the small-order case every edge belongs to a triangle. -/
theorem every_edge_in_triangle_of_card_le_fourteen
    (J : SimpleGraph V) [DecidableRel J.Adj]
    (hReg : J.IsRegularOfDegree 4) (hC4 : NoFourCycle J)
    (hOrder : Fintype.card V ≤ 14) :
    ∀ ⦃x y : V⦄, J.Adj x y →
      ∃ s, J.IsNClique 3 s ∧ x ∈ s ∧ y ∈ s := by
  intro x y hxy
  let d : J.Dart := ⟨(x, y), hxy⟩
  have hCard := card_commonNeighborsOfDart_eq_one J hReg hC4 hOrder d
  have hNonempty : (commonNeighborsOfDart J d).Nonempty := by
    rw [← Finset.card_pos, hCard]
    norm_num
  obtain ⟨z, hz⟩ := hNonempty
  have hzCommon : CommonNeighborRel J z d := by
    simpa [commonNeighborsOfDart] using hz
  refine ⟨{x, y, z}, ?_, by simp, by simp⟩
  rw [SimpleGraph.is3Clique_triple_iff]
  exact ⟨hxy, hzCommon.1.symm, hzCommon.2.symm⟩

/-- A four-regular `C₄`-free graph of order at most fourteen is locally
linear. -/
theorem locallyLinear_of_card_le_fourteen
    (J : SimpleGraph V) [DecidableRel J.Adj]
    (hReg : J.IsRegularOfDegree 4) (hC4 : NoFourCycle J)
    (hOrder : Fintype.card V ≤ 14) :
    J.LocallyLinear :=
  ⟨edgeDisjointTriangles_of_noFourCycle J hC4,
    every_edge_in_triangle_of_card_le_fourteen J hReg hC4 hOrder⟩

/-- Four-regularity gives exactly two edges per vertex. -/
theorem card_edgeFinset_eq_twice_vertices
    (J : SimpleGraph V) [DecidableRel J.Adj]
    (hReg : J.IsRegularOfDegree 4) :
    #J.edgeFinset = 2 * Fintype.card V := by
  have hHandshake := J.sum_degrees_eq_twice_card_edges
  have hDegreeSum : (∑ v : V, J.degree v) = Fintype.card V * 4 := by
    simp_rw [hReg.degree_eq]
    simp
  omega

/-- Under the small-order hypothesis, vertex count and triangle count satisfy
`2|V| = 3T`. -/
theorem twice_vertices_eq_three_times_triangles_of_card_le_fourteen
    (J : SimpleGraph V) [DecidableRel J.Adj]
    (hReg : J.IsRegularOfDegree 4) (hC4 : NoFourCycle J)
    (hOrder : Fintype.card V ≤ 14) :
    2 * Fintype.card V = 3 * #(J.cliqueFinset 3) := by
  have hEdges := card_edgeFinset_eq_twice_vertices J hReg
  have hTriangles :=
    (locallyLinear_of_card_le_fourteen J hReg hC4 hOrder).card_edgeFinset
  omega

/-- Every nonempty finite four-regular `C₄`-free simple graph has at least
fifteen vertices. -/
theorem four_regular_noFourCycle_card_ge_fifteen_direct
    [Nonempty V] (J : SimpleGraph V) [DecidableRel J.Adj]
    (hReg : J.IsRegularOfDegree 4) (hC4 : NoFourCycle J) :
    15 ≤ Fintype.card V := by
  have hThirteen := four_regular_noFourCycle_card_ge_thirteen J hReg hC4
  by_contra hFifteen
  have hOrder : Fintype.card V ≤ 14 := by omega
  have hDiv :=
    twice_vertices_eq_three_times_triangles_of_card_le_fourteen
      J hReg hC4 hOrder
  omega

end ErdosGyarfas