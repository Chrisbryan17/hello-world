#!/usr/bin/env python3
"""Independent verifier for an odd cyclic voltage-lift witness."""
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


def graph_from_edges(order: int, listed: list[list[int]]) -> tuple[int, ...]:
    adjacency = [0] * order
    seen: set[tuple[int, int]] = set()
    for raw_first, raw_second in listed:
        first, second = sorted((int(raw_first), int(raw_second)))
        assert 0 <= first < second < order
        assert (first, second) not in seen
        seen.add((first, second))
        adjacency[first] |= 1 << second
        adjacency[second] |= 1 << first
    return tuple(adjacency)


def connected(adjacency: tuple[int, ...]) -> bool:
    seen = 1
    frontier = 1
    while frontier:
        bit = frontier & -frontier
        frontier ^= bit
        vertex = bit.bit_length() - 1
        new = adjacency[vertex] & ~seen
        seen |= new
        frontier |= new
    return seen.bit_count() == len(adjacency)


def first_cycle(adjacency: tuple[int, ...], length: int) -> tuple[int, ...] | None:
    order = len(adjacency)
    path = [0] * length
    for start in range(order):
        path[0] = start
        for first in iter_bits(adjacency[start] & ~((1 << (start + 1)) - 1)):
            path[1] = first

            def dfs(depth: int, current: int, used: int) -> tuple[int, ...] | None:
                if depth == length:
                    if ((adjacency[current] >> start) & 1) and path[1] < path[-1]:
                        return tuple(path)
                    return None
                candidates = adjacency[current] & ~used & ~((1 << (start + 1)) - 1)
                if depth == length - 1:
                    candidates &= adjacency[start]
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
    graph = graph_from_edges(int(witness["order"]), witness["edges"])
    assert connected(graph)
    assert all(neighbors.bit_count() == 3 for neighbors in graph)
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
        "construction": "odd cyclic voltage lift",
        "order": len(graph),
        "regular_degree": 3,
        "power_lengths_checked": checked,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("witness")
    parser.add_argument("--output")
    args = parser.parse_args()
    witness = json.loads(Path(args.witness).read_text(encoding="utf-8"))
    result = verify(witness)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
