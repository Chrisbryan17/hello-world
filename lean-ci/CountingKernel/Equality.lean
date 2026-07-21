import Mathlib
import CountingKernel.Bounds

namespace CountingKernel

theorem no_small_incidence
    (n T : ℕ)
    (hLower : 13 ≤ n)
    (hUpper : n ≤ 14)
    (hIncidence : 2 * n = 3 * T) :
    False := by
  omega

theorem auxiliary_order_ge_fifteen
    (j : ℕ)
    (hLocalCount : 13 ≤ j)
    (hSmallOrderIncidence : j ≤ 14 → ∃ T : ℕ, 2 * j = 3 * T) :
    15 ≤ j := by
  by_contra hNot
  have hAtMostFourteen : j ≤ 14 := by omega
  obtain ⟨T, hIncidence⟩ := hSmallOrderIncidence hAtMostFourteen
  exact no_small_incidence j T hLocalCount hAtMostFourteen hIncidence

theorem order_ge_forty_five
    (n j : ℕ)
    (hOrder : n = 3 * j)
    (hAuxiliary : 15 ≤ j) :
    45 ≤ n := by
  omega

theorem arithmetic_wrapper
    (a b e n j : ℕ)
    (hPartition : n = a + b)
    (hLowerCross : 4 * b ≤ e)
    (hUpperCross : e ≤ 2 * a)
    (hEquality : a = 2 * b)
    (hAuxiliaryIdentifiesB : b = j)
    (hAuxiliary : 15 ≤ j) :
    45 ≤ n := by
  have hTotal : n = 3 * b := total_order a b n hPartition hEquality
  omega

end CountingKernel
