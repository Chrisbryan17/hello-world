# Direct 15-vertex and 45-vertex equality-case closure

## Formal setting

Let `J` be a finite nonempty simple graph. The Lean development assumes:

- `J.IsRegularOfDegree 4`;
- `NoFourCycle J`, the explicit prohibition of a four-cycle with distinct opposite vertices.

The principal generic theorem is:

```lean
ErdosGyarfas.four_regular_noFourCycle_card_ge_fifteen_direct
```

with conclusion

```lean
15 ≤ Fintype.card V.
```

## 1. Twelve non-backtracking two-step walks

For a fixed vertex `v`, `TwoStepAt J v` records an adjacent first vertex and then an adjacent second vertex different from `v`.

Four-regularity gives four choices for the first step and three non-backtracking choices for the second, so

```text
|TwoStepAt(J,v)| = 4·3 = 12.
```

This is formalized by `card_twoStepAt_eq_twelve`.

## 2. The preliminary order bound |V| ≥ 13

The endpoint map sends a two-step walk to its final vertex. If two distinct walks from `v` had the same endpoint, their two intermediate vertices and the shared endpoints would form a four-cycle. Thus `NoFourCycle J` makes the endpoint map injective.

There are only `|V|-1` possible endpoints other than `v`, hence

```text
12 ≤ |V|-1,
```

and therefore `|V| ≥ 13`. This is `four_regular_noFourCycle_card_ge_thirteen`.

## 3. At most two edges inside each open neighborhood

Let `neighborGraph J v` be the graph induced on `N(v)`. A vertex of this induced graph cannot have two distinct neighbors: together with `v`, those three neighbors would create a four-cycle. Therefore every induced-neighborhood degree is at most one.

Since `|N(v)|=4`, the handshaking lemma gives at most two induced edges:

```text
|E(J[N(v)])| ≤ 2.
```

This is `neighborGraph_card_edges_le_two`.

## 4. Small order forces exactly two local edges

Split the twelve two-step walks from `v` into:

- inside walks, whose endpoint returns to `N(v)`;
- outside walks, whose endpoint lies outside the closed neighborhood `{v}∪N(v)`.

The outside endpoint map is injective by the same four-cycle argument. In a four-regular graph, the number of vertices outside the closed neighborhood is exactly `|V|-5`. Therefore

```text
outside walks ≤ |V|-5.
```

When `|V|≤14`, at most nine walks are outside, so at least three are inside.

Inside walks are canonically equivalent to darts of `J[N(v)]`; consequently their number equals twice the number of local edges. It is therefore even. Combining

```text
3 ≤ inside walks = 2·|E(J[N(v)])|
and
|E(J[N(v)])| ≤ 2
```

forces

```text
|E(J[N(v)])| = 2
```

for every vertex. This is `neighborGraph_card_edges_eq_two_of_card_le_fourteen`.

## 5. Dart/common-neighbor saturation

For a dart `d = x→y`, define its common neighbors as vertices adjacent to both `x` and `y`.

At order at most fourteen, each vertex `v` is a common neighbor of exactly four darts: the inside two-step walks at `v` are the four darts arising from the two edges in `J[N(v)]`.

On the other hand, a dart has at most one common neighbor. Two distinct common neighbors of the same edge would produce a four-cycle.

Double-count common-neighbor/dart incidences:

```text
sum over vertices = 4|V|.
```

A four-regular graph also has exactly `4|V|` darts. Since every dart contributes at most one incidence, equality of the totals forces every dart to have exactly one common neighbor. The formal endpoint is `card_commonNeighborsOfDart_eq_one`.

## 6. Local linearity

`NoFourCycle J` implies that distinct triangles cannot share an edge: two different third vertices on the same edge would form a four-cycle. Thus triangles are edge-disjoint.

The dart saturation result shows every edge has a common neighbor and hence lies in a triangle. Therefore `J` is locally linear: every edge belongs to exactly one triangle.

This is `locallyLinear_of_card_le_fourteen`.

## 7. Divisibility excludes orders 13 and 14

Mathlib's locally-linear triangle count gives

```text
|E(J)| = 3T,
```

where `T` is the number of triangles.

Four-regularity and handshaking give

```text
|E(J)| = 2|V|.
```

Hence

```text
2|V| = 3T.
```

So `3` divides `2|V|`, and therefore `3` divides `|V|`. Neither `13` nor `14` is divisible by `3`. The preliminary bound already gives `|V|≥13`; assuming `|V|≤14` is therefore impossible. Thus

```text
|V| ≥ 15.
```

## 8. Equality-incidence auxiliary graph

An `EqualityIncidence A B` supplies:

- two right incidences at each `a:A`;
- four left incidences at each `b:B`;
- uniqueness of the left vertex determining a pair of right endpoints;
- exclusion of alternating squares.

The auxiliary graph on `B` joins two right vertices when some `a:A` is incident with both. The incidence-neighbor equivalence proves this graph is four-regular, and alternating-square exclusion proves it is `C₄`-free.

For `[Nonempty B]`, the generic direct theorem therefore gives

```text
15 ≤ |B|.
```

This is `EqualityIncidence.auxiliaryGraph_card_ge_fifteen`.

The nonempty assumption excludes only the vacuous abstract incidence system with empty vertex classes; it is automatic in the intended minimal-counterexample application.

## 9. Forty-five vertices

Under the equality-case cardinal relation

```text
|A| = 2|B|,
```

we obtain

```text
|A|+|B| = 3|B| ≥ 45.
```

This is the direct theorem

```lean
ErdosGyarfas.EqualityIncidence.equality_case_forty_five_direct
```

## Verification envelope

The verified project is pinned to:

- Lean `v4.29.0`;
- mathlib `v4.29.0`.

CI performs a full `lake build`, compiles both contract files, prints theorem axiom dependencies, rejects `sorry` and `admit` source placeholders, and fails if any audited theorem depends on `sorryAx`.
