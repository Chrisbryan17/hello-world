#!/usr/bin/env python3
"""Independent verifier for a one-terminal local-surgery witness."""
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
    if not adjacency:
        return False
    seen = 1
    stack = [0]
    while stack:
        vertex = stack.pop()
        for neighbor in iter_bits(adjacency[vertex]):
            if not ((seen >> neighbor) & 1):
                seen |= 1 << neighbor
                stack.append(neighbor)
    return seen.bit_count() == len(adjacency)


def first_cycle(adjacency: tuple[int, ...], length: int) -> tuple[int, ...] | None:
    order = len(adjacency)
    if length > order:
        return None
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


def doubled(cap: tuple[int, ...], terminal: int) -> tuple[int, ...]:
    order = len(cap)
    graph = [0] * (2 * order)
    for vertex, neighbors in enumerate(cap):
        graph[vertex] = neighbors
        for neighbor in iter_bits(neighbors):
            graph[order + vertex] |= 1 << (order + neighbor)
    graph[terminal] |= 1 << (order + terminal)
    graph[order + terminal] |= 1 << terminal
    return tuple(graph)


def check_all_powers(adjacency: tuple[int, ...]) -> list[int]:
    checked = []
    power = 4
    while power <= len(adjacency):
        cycle = first_cycle(adjacency, power)
        checked.append(power)
        if cycle is not None:
            raise AssertionError(f"forbidden C_{power}: {cycle}")
        power *= 2
    return checked


def verify(witness: dict) -> dict:
    cap = graph_from_edges(int(witness["cap_order"]), witness["cap_edges"])
    terminal = int(witness["terminal"])
    degrees = [neighbors.bit_count() for neighbors in cap]
    assert connected(cap)
    assert degrees[terminal] == 2
    assert all(degree == 3 for vertex, degree in enumerate(degrees) if vertex != terminal)
    assert sum(degree == 2 for degree in degrees) == 1
    cap_checked = check_all_powers(cap)

    full = doubled(cap, terminal)
    assert connected(full)
    assert all(neighbors.bit_count() == 3 for neighbors in full)
    full_checked = check_all_powers(full)
    return {
        "verified": True,
        "operation": witness["operation"],
        "cap_order": len(cap),
        "counterexample_order": len(full),
        "cap_power_lengths_checked": cap_checked,
        "counterexample_power_lengths_checked": full_checked,
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
