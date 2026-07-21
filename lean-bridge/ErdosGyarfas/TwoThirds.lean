import Mathlib

namespace ErdosGyarfas

theorem two_thirds_from_cross_edge_bounds
    (a b e : ℕ)
    (hLower : 4 * b ≤ e)
    (hUpper : e ≤ 2 * a) :
    2 * b ≤ a := by
  omega

theorem two_thirds_fraction_form
    (a b n : ℕ)
    (hPartition : n = a + b)
    (hRatio : 2 * b ≤ a) :
    2 * n ≤ 3 * a := by
  omega

theorem two_thirds_from_partition_and_cross_edges
    (a b e n : ℕ)
    (hPartition : n = a + b)
    (hLower : 4 * b ≤ e)
    (hUpper : e ≤ 2 * a) :
    2 * n ≤ 3 * a := by
  have hRatio : 2 * b ≤ a :=
    two_thirds_from_cross_edge_bounds a b e hLower hUpper
  exact two_thirds_fraction_form a b n hPartition hRatio

end ErdosGyarfas
