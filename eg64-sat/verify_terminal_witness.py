#!/usr/bin/env python3
"""Independent verifier for a SAT-generated one-terminal cap witness."""
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


def build_graph(order: int, edge_list: list[list[int]]) -> tuple[int, ...]:
    adjacency = [0] * order
    seen: set[tuple[int, int]] = set()
    for raw_first, raw_second in edge_list:
        first, second = sorted((int(raw_first), int(raw_second)))
        if first == second or first < 0 or second >= order:
            raise AssertionError(f"invalid edge {(raw_first, raw_second)}")
        edge = (first, second)
        if edge in seen:
            raise AssertionError(f"duplicate edge {edge}")
        seen.add(edge)
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


def bridges(adjacency: tuple[int, ...]) -> list[tuple[int, int]]:
    order = len(adjacency)
    discovery = [-1] * order
    low = [0] * order
    parent = [-1] * order
    clock = 0
    found: list[tuple[int, int]] = []

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
                    found.append(tuple(sorted((vertex, neighbor))))
            elif neighbor != parent[vertex]:
                low[vertex] = min(low[vertex], discovery[neighbor])

    dfs(0)
    return sorted(set(found))


def first_cycle(adjacency: tuple[int, ...], length: int) -> tuple[int, ...] | None:
    order = len(adjacency)
    path = [0] * length
    for start in range(order):
        path[0] = start
        first_candidates = adjacency[start] & ~((1 << (start + 1)) - 1)
        for first in iter_bits(first_candidates):
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


def double_cap(adjacency: tuple[int, ...], terminal: int) -> tuple[int, ...]:
    order = len(adjacency)
    doubled = [0] * (2 * order)
    for vertex, neighbors in enumerate(adjacency):
        doubled[vertex] = neighbors
        for neighbor in iter_bits(neighbors):
            doubled[order + vertex] |= 1 << (order + neighbor)
    doubled[terminal] |= 1 << (order + terminal)
    doubled[order + terminal] |= 1 << terminal
    return tuple(doubled)


def verify(payload: dict) -> dict:
    order = int(payload["order"])
    terminal = int(payload["terminal"])
    adjacency = build_graph(order, payload["edges"])
    degrees = [neighbors.bit_count() for neighbors in adjacency]
    assert 0 <= terminal < order
    assert degrees[terminal] == 2, degrees
    assert all(degree == 3 for vertex, degree in enumerate(degrees) if vertex != terminal), degrees
    assert connected(adjacency)
    assert bridges(adjacency) == [], bridges(adjacency)

    cap_checked: list[int] = []
    power = 4
    while power <= order:
        cycle = first_cycle(adjacency, power)
        cap_checked.append(power)
        if cycle is not None:
            raise AssertionError(f"cap contains C_{power}: {cycle}")
        power *= 2

    full = double_cap(adjacency, terminal)
    full_degrees = [neighbors.bit_count() for neighbors in full]
    assert connected(full)
    assert min(full_degrees) == 3 and max(full_degrees) == 3
    full_checked: list[int] = []
    power = 4
    while power <= len(full):
        cycle = first_cycle(full, power)
        full_checked.append(power)
        if cycle is not None:
            raise AssertionError(f"doubled graph contains C_{power}: {cycle}")
        power *= 2

    return {
        "verified": True,
        "cap_order": order,
        "counterexample_order": len(full),
        "cap_degree_sequence": degrees,
        "counterexample_regular_degree": 3,
        "cap_power_lengths_checked": cap_checked,
        "counterexample_power_lengths_checked": full_checked,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("witness")
    parser.add_argument("--output")
    args = parser.parse_args()
    payload = json.loads(Path(args.witness).read_text(encoding="utf-8"))
    result = verify(payload)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
