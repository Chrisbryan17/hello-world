import Mathlib
import ErdosGyarfas.EqualityGraph
import ErdosGyarfas.LocallyLinearClosure

/-!
# Direct equality-case conclusion

The auxiliary graph supplied by an equality incidence structure is four-regular
and `C₄`-free. For a nonempty right vertex class, the direct local theorem gives
at least fifteen right vertices. The equality `|A| = 2|B|` then yields a total
of at least forty-five vertices.
-/

namespace ErdosGyarfas

open Fintype

namespace EqualityIncidence

variable {A B : Type*} [Fintype A] [Fintype B] [DecidableEq B]

/-- The equality-incidence auxiliary graph has at least fifteen vertices,
without an external graph certificate. -/
theorem auxiliaryGraph_card_ge_fifteen
    [Nonempty B] (S : EqualityIncidence A B) :
    15 ≤ Fintype.card B := by
  exact four_regular_noFourCycle_card_ge_fifteen_direct
    S.auxiliaryGraph S.auxiliaryGraph_four_regular
    S.auxiliaryGraph_noFourCycle

/-- Direct end-to-end equality-case lower bound. -/
theorem equality_case_forty_five_direct
    [Nonempty B] (S : EqualityIncidence A B)
    (hCard : Fintype.card A = 2 * Fintype.card B) :
    45 ≤ Fintype.card A + Fintype.card B := by
  have hAux : 15 ≤ Fintype.card B := S.auxiliaryGraph_card_ge_fifteen
  omega

end EqualityIncidence

end ErdosGyarfas
