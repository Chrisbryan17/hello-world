#!/usr/bin/env python3
"""Independent verifier for a SAT-generated cubic counterexample witness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterator


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


def first_cycle(graph: tuple[int, ...], length: int) -> tuple[int, ...] | None:
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


def verify(witness: dict) -> dict:
    graph = build_graph(int(witness["order"]), witness["edges"])
    assert connected(graph)
    degrees = [neighbors.bit_count() for neighbors in graph]
    assert all(degree == 3 for degree in degrees), degrees
    checked = []
    power = 4
    while power <= len(graph):
        cycle = first_cycle(graph, power)
        checked.append(power)
        if cycle is not None:
            raise AssertionError(f"forbidden C_{power}: {cycle}")
        power *= 2
    return {
        "verified": True,
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
