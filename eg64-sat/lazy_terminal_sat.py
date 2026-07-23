#!/usr/bin/env python3
"""Lazy-clause SAT search for a one-terminal Erdős--Gyárfás cap.

The target is a connected bridgeless simple graph on odd order n with vertex 0
of degree 2 and every other vertex of degree 3, containing no cycle of length
4, 8, 16, ... up to n. Two copies joined at their degree-2 vertices then form
a cubic counterexample because the joining edge is a bridge and every cycle is
contained in one copy.

The base CNF fixes the degree sequence and all C4 exclusions. Each SAT model is
checked exactly. Connectivity cuts, bridge cuts, and clauses blocking every
power-of-two cycle in that model are learned until SAT witness, UNSAT, or the
wall-clock budget is reached.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import signal
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator

from pysat.card import CardEnc, EncType
from pysat.formula import IDPool
from pysat.solvers import Solver


def powers_of_two_le(n: int) -> tuple[int, ...]:
    values: list[int] = []
    power = 4
    while power <= n:
        values.append(power)
        power *= 2
    return tuple(values)


def iter_bits(mask: int) -> Iterator[int]:
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


class EdgeVariables:
    def __init__(self, order: int, pool: IDPool) -> None:
        self.order = order
        self.pool = pool
        self.by_edge: dict[tuple[int, int], int] = {}
        self.by_var: dict[int, tuple[int, int]] = {}
        for high in range(1, order):
            for low in range(high):
                var = pool.id((low, high))
                self.by_edge[(low, high)] = var
                self.by_var[var] = (low, high)

    def var(self, first: int, second: int) -> int:
        if first == second:
            raise ValueError("loops have no SAT variable")
        edge = (first, second) if first < second else (second, first)
        return self.by_edge[edge]

    def incident(self, vertex: int) -> list[int]:
        return [self.var(vertex, other) for other in range(self.order) if other != vertex]

    def crossing(self, subset: set[int]) -> list[int]:
        outside = set(range(self.order)) - subset
        return [self.var(left, right) for left in subset for right in outside]


def graph_from_model(
    order: int, edges: EdgeVariables, model: Iterable[int]
) -> tuple[int, ...]:
    positive = {literal for literal in model if literal > 0}
    adjacency = [0] * order
    for var, (first, second) in edges.by_var.items():
        if var in positive:
            adjacency[first] |= 1 << second
            adjacency[second] |= 1 << first
    return tuple(adjacency)


def edge_list(adjacency: tuple[int, ...]) -> list[list[int]]:
    return [
        [first, second]
        for first, neighbors in enumerate(adjacency)
        for second in range(first + 1, len(adjacency))
        if (neighbors >> second) & 1
    ]


def connected_components(adjacency: tuple[int, ...]) -> list[set[int]]:
    unseen = set(range(len(adjacency)))
    components: list[set[int]] = []
    while unseen:
        root = min(unseen)
        component = {root}
        stack = [root]
        unseen.remove(root)
        while stack:
            vertex = stack.pop()
            for neighbor in iter_bits(adjacency[vertex]):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    component.add(neighbor)
                    stack.append(neighbor)
        components.append(component)
    return components


def bridge_sides(adjacency: tuple[int, ...]) -> list[set[int]]:
    """Return one canonical shore for every bridge using Tarjan DFS."""
    order = len(adjacency)
    discovery = [-1] * order
    low = [0] * order
    parent = [-1] * order
    clock = 0
    bridges: list[tuple[int, int]] = []

    def dfs(vertex: int) -> None:
        nonlocal clock
        discovery[vertex] = low[vertex] = clock
        clock += 1
        for neighbor in iter_bits(adjacency[vertex]):
            if discovery[neighbor] == -1:
                parent[neighbor] = vertex
                dfs(neighbor)
                low[vertex] = min(low[vertex], low[neighbor])
                if low[neighbor] > discovery[vertex]:
                    bridges.append((vertex, neighbor))
            elif neighbor != parent[vertex]:
                low[vertex] = min(low[vertex], discovery[neighbor])

    dfs(0)
    if any(value == -1 for value in discovery):
        return []

    shores: list[set[int]] = []
    seen_keys: set[tuple[int, ...]] = set()
    for first, second in bridges:
        blocked = {first, second}
        shore = {second}
        stack = [second]
        while stack:
            vertex = stack.pop()
            for neighbor in iter_bits(adjacency[vertex]):
                if {vertex, neighbor} == blocked:
                    continue
                if neighbor not in shore:
                    shore.add(neighbor)
                    stack.append(neighbor)
        complement = set(range(order)) - shore
        canonical = shore if (len(shore), sorted(shore)) <= (len(complement), sorted(complement)) else complement
        key = tuple(sorted(canonical))
        if key not in seen_keys:
            seen_keys.add(key)
            shores.append(canonical)
    return shores


def canonical_cycles(adjacency: tuple[int, ...], length: int) -> Iterator[tuple[int, ...]]:
    """Enumerate each undirected simple cycle exactly once."""
    order = len(adjacency)
    if length < 3 or length > order:
        return
    path = [0] * length
    for start in range(order):
        path[0] = start
        first_candidates = adjacency[start] & ~((1 << (start + 1)) - 1)
        for first in iter_bits(first_candidates):
            path[1] = first

            def dfs(depth: int, current: int, used: int) -> Iterator[tuple[int, ...]]:
                if depth == length:
                    if ((adjacency[current] >> start) & 1) and path[1] < path[-1]:
                        yield tuple(path)
                    return
                candidates = adjacency[current] & ~used & ~((1 << (start + 1)) - 1)
                if depth == length - 1:
                    candidates &= adjacency[start]
                for nxt in iter_bits(candidates):
                    path[depth] = nxt
                    yield from dfs(depth + 1, nxt, used | (1 << nxt))

            yield from dfs(2, first, (1 << start) | (1 << first))


def cycle_clause(cycle: tuple[int, ...], edges: EdgeVariables) -> tuple[int, ...]:
    literals = []
    for index, first in enumerate(cycle):
        second = cycle[(index + 1) % len(cycle)]
        literals.append(-edges.var(first, second))
    return tuple(sorted(literals))


def all_c4_clauses(order: int, edges: EdgeVariables) -> Iterator[tuple[int, ...]]:
    for a, b, c, d in itertools.combinations(range(order), 4):
        yield tuple(sorted((-edges.var(a, b), -edges.var(b, c), -edges.var(c, d), -edges.var(d, a))))
        yield tuple(sorted((-edges.var(a, b), -edges.var(b, d), -edges.var(d, c), -edges.var(c, a))))
        yield tuple(sorted((-edges.var(a, c), -edges.var(c, b), -edges.var(b, d), -edges.var(d, a))))


def graph6(adjacency: tuple[int, ...]) -> str:
    order = len(adjacency)
    if order > 62:
        raise ValueError("compact graph6 writer supports order at most 62")
    bits: list[int] = []
    for high in range(1, order):
        for low in range(high):
            bits.append((adjacency[low] >> high) & 1)
    while len(bits) % 6:
        bits.append(0)
    chars = [chr(order + 63)]
    for offset in range(0, len(bits), 6):
        value = sum(bits[offset + bit] << (5 - bit) for bit in range(6))
        chars.append(chr(value + 63))
    return "".join(chars)


@dataclass
class Statistics:
    order: int
    solver: str
    status: str = "running"
    iterations: int = 0
    models: int = 0
    connectivity_cuts: int = 0
    bridge_cuts: int = 0
    cycle_clauses: int = 0
    c4_clauses: int = 0
    elapsed_seconds: float = 0.0


def emit_checkpoint(path: Path | None, stats: Statistics, extra: dict | None = None) -> None:
    if path is None:
        return
    payload = {"stats": asdict(stats)}
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order", type=int, required=True)
    parser.add_argument("--solver", default="cadical195")
    parser.add_argument("--max-seconds", type=float, default=3000.0)
    parser.add_argument("--checkpoint")
    parser.add_argument("--witness-out")
    parser.add_argument("--log-every", type=int, default=100)
    args = parser.parse_args()

    order = args.order
    if order < 5 or order % 2 == 0:
        raise ValueError("one-terminal degree sequence requires odd order at least 5")

    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    witness_path = Path(args.witness_out) if args.witness_out else None
    pool = IDPool()
    edges = EdgeVariables(order, pool)
    stats = Statistics(order=order, solver=args.solver)
    start_time = time.monotonic()
    learned_cycles: set[tuple[int, ...]] = set()
    learned_cuts: set[tuple[str, tuple[int, ...]]] = set()

    with Solver(name=args.solver) as solver:
        # Fix the unique terminal and two neighbors. This loses no solutions by relabeling.
        solver.add_clause([edges.var(0, 1)])
        solver.add_clause([edges.var(0, 2)])
        for vertex in range(3, order):
            solver.add_clause([-edges.var(0, vertex)])

        # Vertex 1 has two further neighbors; one can be relabeled as vertex 3.
        solver.add_clause([edges.var(1, 3)])

        # Exact degree sequence.
        for vertex in range(order):
            target = 2 if vertex == 0 else 3
            encoding = CardEnc.equals(
                lits=edges.incident(vertex),
                bound=target,
                vpool=pool,
                encoding=EncType.seqcounter,
            )
            solver.append_formula(encoding.clauses)

        # C4 clauses are cheap enough to add exhaustively and remove the dominant failure mode.
        for clause in all_c4_clauses(order, edges):
            solver.add_clause(list(clause))
            learned_cycles.add(clause)
            stats.c4_clauses += 1

        while True:
            stats.elapsed_seconds = time.monotonic() - start_time
            if stats.elapsed_seconds >= args.max_seconds:
                stats.status = "timeout"
                emit_checkpoint(checkpoint, stats)
                print(json.dumps({"stats": asdict(stats)}, sort_keys=True))
                return 124

            stats.iterations += 1
            satisfiable = solver.solve()
            stats.elapsed_seconds = time.monotonic() - start_time
            if not satisfiable:
                stats.status = "unsat"
                emit_checkpoint(checkpoint, stats)
                print(json.dumps({"stats": asdict(stats)}, sort_keys=True))
                return 0

            stats.models += 1
            adjacency = graph_from_model(order, edges, solver.get_model())
            new_constraints = 0

            components = connected_components(adjacency)
            if len(components) > 1:
                for component in components:
                    if len(component) == order:
                        continue
                    complement = set(range(order)) - component
                    canonical = component if (len(component), sorted(component)) <= (len(complement), sorted(complement)) else complement
                    key = ("connected", tuple(sorted(canonical)))
                    if key in learned_cuts:
                        continue
                    learned_cuts.add(key)
                    solver.add_clause(edges.crossing(canonical))
                    stats.connectivity_cuts += 1
                    new_constraints += 1
            else:
                # A smallest cap can be assumed bridgeless: a bridge exposes a smaller
                # one-terminal component with the same internal cycle restriction.
                for shore in bridge_sides(adjacency):
                    key = ("bridge", tuple(sorted(shore)))
                    if key in learned_cuts:
                        continue
                    learned_cuts.add(key)
                    encoding = CardEnc.atleast(
                        lits=edges.crossing(shore),
                        bound=2,
                        vpool=pool,
                        encoding=EncType.seqcounter,
                    )
                    solver.append_formula(encoding.clauses)
                    stats.bridge_cuts += 1
                    new_constraints += 1

                for length in powers_of_two_le(order):
                    if length == 4:
                        continue
                    for cycle in canonical_cycles(adjacency, length):
                        clause = cycle_clause(cycle, edges)
                        if clause in learned_cycles:
                            continue
                        learned_cycles.add(clause)
                        solver.add_clause(list(clause))
                        stats.cycle_clauses += 1
                        new_constraints += 1

            if new_constraints == 0:
                degrees = [neighbors.bit_count() for neighbors in adjacency]
                witness = {
                    "kind": "sat_terminal_cap",
                    "order": order,
                    "terminal": 0,
                    "graph6": graph6(adjacency),
                    "edges": edge_list(adjacency),
                    "degree_sequence": degrees,
                    "doubled_counterexample_order": 2 * order,
                    "power_cycle_lengths_checked": list(powers_of_two_le(order)),
                    "stats": asdict(stats),
                }
                stats.status = "witness"
                witness["stats"] = asdict(stats)
                if witness_path is not None:
                    witness_path.write_text(
                        json.dumps(witness, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                emit_checkpoint(checkpoint, stats, {"witness": witness})
                print(json.dumps({"stats": asdict(stats), "witness": witness}, sort_keys=True))
                return 10

            if args.log_every and stats.iterations % args.log_every == 0:
                emit_checkpoint(checkpoint, stats)
                print(
                    json.dumps(
                        {
                            "progress": asdict(stats),
                            "new_constraints": new_constraints,
                            "components": len(components),
                        },
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                    flush=True,
                )


if __name__ == "__main__":
    raise SystemExit(main())
