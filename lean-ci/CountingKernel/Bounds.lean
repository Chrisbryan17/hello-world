import Mathlib

namespace CountingKernel

theorem cross_edge_bounds
    (a b e : ℕ)
    (hLower : 4 * b ≤ e)
    (hUpper : e ≤ 2 * a) :
    2 * b ≤ a := by
  omega

theorem fraction_form
    (a b n : ℕ)
    (hPartition : n = a + b)
    (hRatio : 2 * b ≤ a) :
    2 * n ≤ 3 * a := by
  omega

theorem partition_and_cross_edges
    (a b e n : ℕ)
    (hPartition : n = a + b)
    (hLower : 4 * b ≤ e)
    (hUpper : e ≤ 2 * a) :
    2 * n ≤ 3 * a := by
  have hRatio : 2 * b ≤ a := cross_edge_bounds a b e hLower hUpper
  exact fraction_form a b n hPartition hRatio

theorem exact_cross_edge_count
    (a b e : ℕ)
    (hLower : 4 * b ≤ e)
    (hUpper : e ≤ 2 * a)
    (hEquality : a = 2 * b) :
    e = 4 * b := by
  omega

theorem total_order
    (a b n : ℕ)
    (hPartition : n = a + b)
    (hEquality : a = 2 * b) :
    n = 3 * b := by
  omega

end CountingKernel
