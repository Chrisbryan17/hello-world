#!/usr/bin/env python3
"""Exact path-spectrum CSP for cubic three-terminal gadget assemblies.

Every non-internal cycle in an assembled graph projects to a simple cycle of
the cubic base: a cycle crosses each three-terminal gadget cut an even number
of times, hence zero or two. Its length is the sum, over the projected base
cycle, of one internal terminal-to-terminal path length plus one external edge.
The program enumerates every simple path length in each gadget, every simple
cycle in each base, and every physical terminal assignment through an exact
backtracking CSP. Pruned branches are counted by their full completion volume.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from typing import Iterator

PERMUTATIONS = tuple(itertools.permutations(range(3)))
PAIR_INDEX = {(0, 1): 0, (0, 2): 1, (1, 2): 2}


def parse_graph6(raw: bytes) -> tuple[int, tuple[int, ...]]:
    data = raw.strip()
    if data.startswith(b">>graph6<<"):
        data = data[len(b">>graph6<<"):]
    values = [value - 63 for value in data]
    if not values or any(value < 0 or value > 63 for value in values):
        raise ValueError("invalid graph6 record")
    if values[0] <= 62:
        order, position = values[0], 1
    elif len(values) >= 4 and values[0] == 63 and values[1] != 63:
        order = (values[1] << 12) | (values[2] << 6) | values[3]
        position = 4
    else:
        raise ValueError("unsupported graph6 order encoding")
    bits_out: list[int] = []
    for value in values[position:]:
        bits_out.extend((value >> shift) & 1 for shift in range(5, -1, -1))
    required = order * (order - 1) // 2
    if len(bits_out) < required:
        raise ValueError("truncated graph6 record")
    adjacency = [0] * order
    index = 0
    for high in range(1, order):
        for low in range(high):
            if bits_out[index]:
                adjacency[low] |= 1 << high
                adjacency[high] |= 1 << low
            index += 1
    return order, tuple(adjacency)


def iter_bits(mask: int) -> Iterator[int]:
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def canonical_cycles(
    adjacency: tuple[int, ...], length: int
) -> Iterator[tuple[int, ...]]:
    order = len(adjacency)
    if length > order:
        return
    path = [0] * length
    for start in range(order):
        path[0] = start
        first_mask = adjacency[start] & ~((1 << (start + 1)) - 1)
        for first in iter_bits(first_mask):
            path[1] = first

            def search(depth: int, current: int, used: int) -> Iterator[tuple[int, ...]]:
                if depth == length:
                    if ((adjacency[current] >> start) & 1) and path[1] < path[-1]:
                        yield tuple(path)
                    return
                candidates = adjacency[current] & ~used & ~((1 << (start + 1)) - 1)
                if depth == length - 1:
                    candidates &= adjacency[start]
                for neighbour in iter_bits(candidates):
                    path[depth] = neighbour
                    yield from search(depth + 1, neighbour, used | (1 << neighbour))

            yield from search(2, first, (1 << start) | (1 << first))


def power_cycle_vertex_intersection(
    adjacency: tuple[int, ...],
) -> tuple[bool, int]:
    intersection = (1 << len(adjacency)) - 1
    saw_cycle = False
    power = 4
    while power <= len(adjacency):
        for cycle in canonical_cycles(adjacency, power):
            saw_cycle = True
            cycle_vertices = 0
            for vertex in cycle:
                cycle_vertices |= 1 << vertex
            intersection &= cycle_vertices
            if intersection == 0:
                return saw_cycle, 0
        power *= 2
    return saw_cycle, intersection


def delete_vertex(
    adjacency: tuple[int, ...], vertex: int
) -> tuple[tuple[int, ...], tuple[int, int, int]]:
    retained = [old for old in range(len(adjacency)) if old != vertex]
    new_index = {old: new for new, old in enumerate(retained)}
    gadget = [0] * len(retained)
    for old in retained:
        for neighbour in iter_bits(adjacency[old]):
            if neighbour != vertex:
                gadget[new_index[old]] |= 1 << new_index[neighbour]
    terminals = tuple(new_index[neighbour] for neighbour in iter_bits(adjacency[vertex]))
    if len(terminals) != 3:
        raise AssertionError("deleting a cubic vertex did not expose three terminals")
    return tuple(gadget), terminals


def terminal_path_spectra(
    gadget: tuple[int, ...], terminals: tuple[int, int, int]
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    spectra: list[tuple[int, ...]] = []
    for first, second in ((0, 1), (0, 2), (1, 2)):
        start, target = terminals[first], terminals[second]
        contributions: set[int] = set()

        def search(vertex: int, used: int, length: int) -> None:
            if vertex == target:
                contributions.add(length + 1)
                return
            for neighbour in iter_bits(gadget[vertex] & ~used):
                search(neighbour, used | (1 << neighbour), length + 1)

        search(start, 1 << start, 0)
        spectra.append(tuple(sorted(contributions)))
    return spectra[0], spectra[1], spectra[2]


def encoded_base_cycles(
    base: tuple[int, ...],
) -> tuple[tuple[tuple[int, int, int], ...], ...]:
    neighbours = [tuple(sorted(iter_bits(mask))) for mask in base]
    slots = [
        {neighbour: slot for slot, neighbour in enumerate(vertex_neighbours)}
        for vertex_neighbours in neighbours
    ]
    encoded = []
    for length in range(3, len(base) + 1):
        for cycle in canonical_cycles(base, length):
            terms = []
            for index, vertex in enumerate(cycle):
                previous = cycle[index - 1]
                following = cycle[(index + 1) % length]
                terms.append((vertex, slots[vertex][previous], slots[vertex][following]))
            encoded.append(tuple(terms))
    return tuple(encoded)


def forbidden_profiles(
    spectra: tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]],
    maximum_cycle_length: int,
    assembled_order: int,
) -> dict[tuple[int, int, int], bool]:
    powers = set()
    power = 4
    while power <= assembled_order:
        powers.add(power)
        power *= 2
    forbidden: dict[tuple[int, int, int], bool] = {}
    for count_01 in range(maximum_cycle_length + 1):
        for count_02 in range(maximum_cycle_length - count_01 + 1):
            for count_12 in range(maximum_cycle_length - count_01 - count_02 + 1):
                if count_01 + count_02 + count_12 < 3:
                    continue
                sums = {0}
                for pair_type, count in enumerate((count_01, count_02, count_12)):
                    for _ in range(count):
                        sums = {
                            partial + contribution
                            for partial in sums
                            for contribution in spectra[pair_type]
                        }
                profile = count_01, count_02, count_12
                forbidden[profile] = bool(sums & powers)
    return forbidden


def cycle_profile(
    encoded_cycle: tuple[tuple[int, int, int], ...],
    assignments: list[tuple[int, int, int] | None],
) -> tuple[int, int, int]:
    counts = [0, 0, 0]
    for vertex, first_slot, second_slot in encoded_cycle:
        assignment = assignments[vertex]
        if assignment is None:
            raise AssertionError("cycle constraint evaluated before all variables were assigned")
        first = assignment[first_slot]
        second = assignment[second_slot]
        if first > second:
            first, second = second, first
        counts[PAIR_INDEX[(first, second)]] += 1
    return counts[0], counts[1], counts[2]


def solve_exact(
    spectra: tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]],
    base: tuple[int, ...],
    gadget_order: int,
) -> tuple[tuple[tuple[int, int, int], ...] | None, int, int, int]:
    constraints = encoded_base_cycles(base)
    forbidden = forbidden_profiles(spectra, len(base), len(base) * gadget_order)
    occurrences = [0] * len(base)
    for constraint in constraints:
        for vertex, _, _ in constraint:
            occurrences[vertex] += 1
    variable_order = tuple(
        sorted(range(len(base)), key=lambda vertex: (-occurrences[vertex], vertex))
    )
    position = {vertex: index for index, vertex in enumerate(variable_order)}
    triggered: list[list[tuple[tuple[int, int, int], ...]]] = [
        [] for _ in variable_order
    ]
    for constraint in constraints:
        triggered[max(position[vertex] for vertex, _, _ in constraint)].append(constraint)

    assignments: list[tuple[int, int, int] | None] = [None] * len(base)
    covered_assignments = 0
    search_nodes = 0

    def search(depth: int) -> tuple[tuple[int, int, int], ...] | None:
        nonlocal covered_assignments, search_nodes
        search_nodes += 1
        if depth == len(variable_order):
            return tuple(assignment for assignment in assignments if assignment is not None)
        vertex = variable_order[depth]
        for permutation in PERMUTATIONS:
            assignments[vertex] = permutation
            failed = any(
                forbidden[cycle_profile(constraint, assignments)]
                for constraint in triggered[depth]
            )
            if failed:
                covered_assignments += 6 ** (len(variable_order) - depth - 1)
            else:
                answer = search(depth + 1)
                if answer is not None:
                    return answer
        assignments[vertex] = None
        return None

    answer = search(0)
    return answer, covered_assignments, search_nodes, len(constraints)


# A direct graph constructor and direct cycle test are retained solely for the
# exhaustive equivalence self-test and for adversarial witness verification.
def assemble(
    gadget: tuple[int, ...],
    terminals: tuple[int, int, int],
    base: tuple[int, ...],
    assignments: tuple[tuple[int, int, int], ...],
) -> tuple[int, ...]:
    gadget_order = len(gadget)
    assembled = [0] * (gadget_order * len(base))
    base_neighbours = [tuple(sorted(iter_bits(mask))) for mask in base]
    base_slots = [
        {neighbour: slot for slot, neighbour in enumerate(neighbours)}
        for neighbours in base_neighbours
    ]
    for copy in range(len(base)):
        offset = copy * gadget_order
        for vertex, neighbours in enumerate(gadget):
            for neighbour in iter_bits(neighbours):
                assembled[offset + vertex] |= 1 << (offset + neighbour)
    for first in range(len(base)):
        for second in base_neighbours[first]:
            if first >= second:
                continue
            first_vertex = (
                first * gadget_order
                + terminals[assignments[first][base_slots[first][second]]]
            )
            second_vertex = (
                second * gadget_order
                + terminals[assignments[second][base_slots[second][first]]]
            )
            assembled[first_vertex] |= 1 << second_vertex
            assembled[second_vertex] |= 1 << first_vertex
    return tuple(assembled)


def first_forbidden_power(adjacency: tuple[int, ...]) -> int | None:
    power = 4
    while power <= len(adjacency):
        if next(canonical_cycles(adjacency, power), None) is not None:
            return power
        power *= 2
    return None


def assignment_is_forbidden_by_spectra(
    spectra: tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]],
    base: tuple[int, ...],
    assignments: tuple[tuple[int, int, int], ...],
    gadget_order: int,
) -> bool:
    forbidden = forbidden_profiles(spectra, len(base), len(base) * gadget_order)
    mutable_assignments: list[tuple[int, int, int] | None] = list(assignments)
    return any(
        forbidden[cycle_profile(constraint, mutable_assignments)]
        for constraint in encoded_base_cycles(base)
    )


def self_test() -> None:
    _, source = parse_graph6(b"C~")
    gadget, terminals = delete_vertex(source, 0)
    spectra = terminal_path_spectra(gadget, terminals)
    for raw_base in (b"C~", b"EFz_", b"EUxo"):
        _, base = parse_graph6(raw_base)
        for assignments in itertools.product(PERMUTATIONS, repeat=len(base)):
            direct = first_forbidden_power(
                assemble(gadget, terminals, base, assignments)
            ) is not None
            spectral = assignment_is_forbidden_by_spectra(
                spectra, base, assignments, len(gadget)
            )
            if direct != spectral:
                raise AssertionError((raw_base, assignments, direct, spectral))
    print("SPECTRUM_DIRECT_CROSSCHECK=PASS", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-file")
    parser.add_argument("--order", type=int)
    parser.add_argument("--expected", type=int)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--witness-out")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.base_file or args.order is None:
        parser.error("--base-file and --order are required outside --self-test")

    bases: list[tuple[str, tuple[int, ...]]] = []
    with open(args.base_file, "rb") as handle:
        for raw in handle:
            if raw.strip():
                bases.append((raw.strip().decode("ascii"), parse_graph6(raw)[1]))

    stats = {
        "source_graphs": 0,
        "candidate_vertices": 0,
        "base_graphs": len(bases),
        "assignments_covered": 0,
        "search_nodes": 0,
        "constraints": 0,
    }
    witness = None
    for raw in sys.stdin.buffer:
        if not raw.strip():
            continue
        order, source = parse_graph6(raw)
        if order != args.order:
            raise ValueError(f"expected order {args.order}, received {order}")
        stats["source_graphs"] += 1
        saw_cycle, intersection = power_cycle_vertex_intersection(source)
        if not saw_cycle:
            witness = {
                "kind": "source_graph_counterexample",
                "graph6": raw.strip().decode("ascii"),
                "order": order,
            }
            break
        for deleted_vertex in iter_bits(intersection):
            stats["candidate_vertices"] += 1
            gadget, terminals = delete_vertex(source, deleted_vertex)
            if first_forbidden_power(gadget) is not None:
                raise AssertionError("candidate gadget retained a forbidden internal cycle")
            spectra = terminal_path_spectra(gadget, terminals)
            for base_graph6, base in bases:
                assignments, covered, nodes, constraint_count = solve_exact(
                    spectra, base, len(gadget)
                )
                stats["assignments_covered"] += covered
                stats["search_nodes"] += nodes
                stats["constraints"] += constraint_count
                if assignments is None and covered != 6 ** len(base):
                    raise AssertionError(
                        ("incomplete CSP accounting", base_graph6, covered, 6 ** len(base))
                    )
                if assignments is not None:
                    witness = {
                        "kind": "spectrum_wiring",
                        "source_graph6": raw.strip().decode("ascii"),
                        "source_order": order,
                        "deleted_vertex": deleted_vertex,
                        "terminals": list(terminals),
                        "path_spectra": [list(spectrum) for spectrum in spectra],
                        "base_graph6": base_graph6,
                        "assignments": [list(assignment) for assignment in assignments],
                        "assembled_order": len(gadget) * len(base),
                    }
                    break
            if witness is not None:
                break
        if witness is not None:
            break

    result = {"stats": stats, "witness": witness}
    if (
        args.expected is not None
        and witness is None
        and stats["source_graphs"] != args.expected
    ):
        result["count_error"] = {
            "expected": args.expected,
            "actual": stats["source_graphs"],
        }
        print(json.dumps(result, sort_keys=True))
        return 2
    if witness is not None and args.witness_out:
        with open(args.witness_out, "w", encoding="utf-8") as handle:
            json.dump(witness, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(json.dumps(result, sort_keys=True))
    return 10 if witness is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
