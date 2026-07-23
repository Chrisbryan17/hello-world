#!/usr/bin/env python3
"""Independent verifier for a Z5 voltage-lift counterexample candidate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterator

from pysat.card import CardEnc, EncType
from pysat.formula import IDPool
from pysat.solvers import Solver


def iter_bits(mask: int) -> Iterator[int]:
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def build_graph(order: int, listed: list[list[int]]) -> tuple[int, ...]:
    graph = [0] * order
    seen: set[tuple[int, int]] = set()
    for raw_first, raw_second in listed:
        first, second = sorted((int(raw_first), int(raw_second)))
        assert 0 <= first < second < order
        assert (first, second) not in seen
        seen.add((first, second))
        graph[first] |= 1 << second
        graph[second] |= 1 << first
    return tuple(graph)


def connected(graph: tuple[int, ...]) -> bool:
    seen = 1
    frontier = 1
    while frontier:
        bit = frontier & -frontier
        frontier ^= bit
        vertex = bit.bit_length() - 1
        new = graph[vertex] & ~seen
        seen |= new
        frontier |= new
    return seen.bit_count() == len(graph)


def first_cycle_dfs(graph: tuple[int, ...], length: int) -> tuple[int, ...] | None:
    order = len(graph)
    path = [0] * length
    for start in range(order):
        path[0] = start
        for first in iter_bits(graph[start] & ~((1 << (start + 1)) - 1)):
            path[1] = first

            def dfs(depth: int, current: int, used: int) -> tuple[int, ...] | None:
                if depth == length:
                    if ((graph[current] >> start) & 1) and path[1] < path[-1]:
                        return tuple(path)
                    return None
                candidates = graph[current] & ~used & ~((1 << (start + 1)) - 1)
                if depth == length - 1:
                    candidates &= graph[start]
                for nxt in iter_bits(candidates):
                    path[depth] = nxt
                    answer = dfs(depth + 1, nxt, used | (1 << nxt))
                    if answer is not None:
                        return answer
                return None

            answer = dfs(2, first, (1 << start) | (1 << first))
            if answer is not None:
                return answer
    return None


def first_cycle_sat(graph: tuple[int, ...], length: int) -> tuple[int, ...] | None:
    order = len(graph)
    pool = IDPool()

    def variable(position: int, vertex: int) -> int:
        return pool.id((position, vertex))

    with Solver(name="glucose42") as solver:
        for position in range(length):
            solver.append_formula(
                CardEnc.equals(
                    lits=[variable(position, vertex) for vertex in range(order)],
                    bound=1,
                    vpool=pool,
                    encoding=EncType.seqcounter,
                ).clauses
            )
        for vertex in range(order):
            solver.append_formula(
                CardEnc.atmost(
                    lits=[variable(position, vertex) for position in range(length)],
                    bound=1,
                    vpool=pool,
                    encoding=EncType.seqcounter,
                ).clauses
            )
        for position in range(length):
            nxt = (position + 1) % length
            for vertex in range(order):
                solver.add_clause(
                    [-variable(position, vertex)]
                    + [variable(nxt, neighbor) for neighbor in iter_bits(graph[vertex])]
                )
        for root in range(order):
            for position in range(1, length):
                for smaller in range(root):
                    solver.add_clause(
                        [-variable(0, root), -variable(position, smaller)]
                    )
        for first in range(order):
            for last in range(first + 1):
                solver.add_clause(
                    [-variable(1, first), -variable(length - 1, last)]
                )

        if not solver.solve():
            return None
        positive = {literal for literal in solver.get_model() if literal > 0}
        return tuple(
            next(vertex for vertex in range(order) if variable(position, vertex) in positive)
            for position in range(length)
        )


def verify(witness: dict) -> dict:
    graph = build_graph(int(witness["order"]), witness["edges"])
    assert connected(graph)
    degrees = [neighbors.bit_count() for neighbors in graph]
    assert all(degree == 3 for degree in degrees), degrees
    checked = []
    for length in (4, 8, 16, 32):
        cycle = first_cycle_dfs(graph, length)
        checked.append(length)
        if cycle is not None:
            raise AssertionError(f"forbidden C_{length}: {cycle}")
    cycle64 = first_cycle_sat(graph, 64)
    checked.append(64)
    if cycle64 is not None:
        raise AssertionError(f"forbidden C_64: {cycle64}")
    return {
        "verified": True,
        "construction": "normalized Z5 voltage lift",
        "order": len(graph),
        "regular_degree": 3,
        "power_cycle_lengths_checked": checked,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("witness")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = verify(json.loads(Path(args.witness).read_text(encoding="utf-8")))
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
