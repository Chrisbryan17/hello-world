#!/usr/bin/env python3
"""Exact direct-wiring search for cubic three-terminal gadgets.

For every connected cubic source graph Q, delete any vertex lying on every
power-of-two cycle. The remaining graph H is a cubic three-terminal gadget
with no internal power-of-two cycle. Instead of requiring a uniform modular
path condition, this program directly assembles copies of H over every supplied
cubic base graph and exhausts every physical terminal assignment. No terminal
symmetry quotient is taken unless separately proved.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from typing import Iterator

PERMUTATIONS = tuple(itertools.permutations(range(3)))


def parse_graph6(raw: bytes) -> tuple[int, tuple[int, ...]]:
    data = raw.strip()
    if data.startswith(b">>graph6<<"):
        data = data[len(b">>graph6<<"):]
    values = [character - 63 for character in data]
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
    if len(bits_out) < order * (order - 1) // 2:
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


def validate_connected_cubic(adjacency: tuple[int, ...]) -> None:
    if not adjacency or any(neighbours.bit_count() != 3 for neighbours in adjacency):
        raise ValueError("graph is not cubic")
    seen = 1
    frontier = 1
    while frontier:
        bit = frontier & -frontier
        frontier ^= bit
        vertex = bit.bit_length() - 1
        unseen = adjacency[vertex] & ~seen
        seen |= unseen
        frontier |= unseen
    if seen.bit_count() != len(adjacency):
        raise ValueError("graph is disconnected")


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


def contains_four_cycle(adjacency: tuple[int, ...]) -> bool:
    order = len(adjacency)
    for first in range(order):
        for second in range(first + 1, order):
            if (adjacency[first] & adjacency[second]).bit_count() >= 2:
                return True
    return False


def first_forbidden_power(adjacency: tuple[int, ...]) -> int | None:
    if contains_four_cycle(adjacency):
        return 4
    power = 8
    while power <= len(adjacency):
        if next(canonical_cycles(adjacency, power), None) is not None:
            return power
        power *= 2
    return None


def assemble(
    gadget: tuple[int, ...],
    terminals: tuple[int, int, int],
    base: tuple[int, ...],
    assignments: tuple[tuple[int, int, int], ...],
) -> tuple[int, ...]:
    gadget_order = len(gadget)
    base_order = len(base)
    assembled = [0] * (gadget_order * base_order)
    for copy in range(base_order):
        offset = copy * gadget_order
        for vertex, neighbours in enumerate(gadget):
            for neighbour in iter_bits(neighbours):
                assembled[offset + vertex] |= 1 << (offset + neighbour)

    base_neighbours = [tuple(sorted(iter_bits(neighbours))) for neighbours in base]
    neighbour_slots = [
        {neighbour: slot for slot, neighbour in enumerate(neighbours)}
        for neighbours in base_neighbours
    ]
    for first in range(base_order):
        for second in base_neighbours[first]:
            if first >= second:
                continue
            first_terminal = terminals[
                assignments[first][neighbour_slots[first][second]]
            ]
            second_terminal = terminals[
                assignments[second][neighbour_slots[second][first]]
            ]
            first_vertex = first * gadget_order + first_terminal
            second_vertex = second * gadget_order + second_terminal
            assembled[first_vertex] |= 1 << second_vertex
            assembled[second_vertex] |= 1 << first_vertex
    return tuple(assembled)


def exhaust_assignments(
    gadget: tuple[int, ...],
    terminals: tuple[int, int, int],
    base: tuple[int, ...],
) -> tuple[tuple[tuple[int, int, int], ...] | None, int, int]:
    tested = 0
    deepest_survival = 0
    # Enumerate every physical terminal assignment. A global terminal-label
    # normalization is not valid unless the gadget has a proved S3 action on
    # its three terminals; no such symmetry is assumed here.
    for assignments in itertools.product(PERMUTATIONS, repeat=len(base)):
        tested += 1
        graph = assemble(gadget, terminals, base, assignments)
        forbidden = first_forbidden_power(graph)
        if forbidden is None:
            return assignments, tested, len(graph)
        deepest_survival = max(deepest_survival, forbidden)
    return None, tested, deepest_survival


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-file", required=True)
    parser.add_argument("--order", required=True, type=int)
    parser.add_argument("--expected", type=int)
    parser.add_argument("--witness-out")
    args = parser.parse_args()

    bases: list[tuple[str, tuple[int, ...]]] = []
    with open(args.base_file, "rb") as base_handle:
        for raw in base_handle:
            if not raw.strip() or raw.startswith(b">>"):
                continue
            _order, adjacency = parse_graph6(raw)
            validate_connected_cubic(adjacency)
            bases.append((raw.strip().decode("ascii"), adjacency))

    stats = {
        "source_order": args.order,
        "source_graphs": 0,
        "candidate_vertices": 0,
        "base_graphs": len(bases),
        "wirings_tested": 0,
        "deepest_forbidden_power_seen": 0,
    }
    witness = None
    for raw in sys.stdin.buffer:
        if not raw.strip() or raw.startswith(b">>"):
            continue
        order, source = parse_graph6(raw)
        if order != args.order:
            raise ValueError(f"expected order {args.order}, received {order}")
        validate_connected_cubic(source)
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
            for base_graph6, base in bases:
                assignments, tested, outcome = exhaust_assignments(gadget, terminals, base)
                stats["wirings_tested"] += tested
                if assignments is None:
                    stats["deepest_forbidden_power_seen"] = max(
                        stats["deepest_forbidden_power_seen"], outcome
                    )
                    continue
                witness = {
                    "kind": "direct_three_pole_wiring",
                    "source_graph6": raw.strip().decode("ascii"),
                    "source_order": order,
                    "deleted_vertex": deleted_vertex,
                    "terminals": list(terminals),
                    "base_graph6": base_graph6,
                    "assignments": [list(assignment) for assignment in assignments],
                    "assembled_order": outcome,
                }
                break
            if witness is not None:
                break
        if witness is not None:
            break

    result = {"stats": stats, "witness": witness}
    if args.expected is not None and witness is None and stats["source_graphs"] != args.expected:
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
