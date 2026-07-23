#!/usr/bin/env python3
"""Independent verifier for a one-terminal cap counterexample witness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def decode(text: str) -> list[set[int]]:
    values = [ord(char) - 63 for char in text.strip()]
    if not values or values[0] > 62:
        raise ValueError("unsupported graph6")
    n = values[0]
    bits = []
    for value in values[1:]:
        bits.extend((value >> shift) & 1 for shift in range(5, -1, -1))
    graph = [set() for _ in range(n)]
    index = 0
    for high in range(1, n):
        for low in range(high):
            if bits[index]:
                graph[low].add(high)
                graph[high].add(low)
            index += 1
    return graph


def first_cycle(graph: list[set[int]], length: int) -> list[int] | None:
    n = len(graph)
    path = [-1] * length
    for start in range(n):
        path[0] = start
        for first in sorted(vertex for vertex in graph[start] if vertex > start):
            path[1] = first
            used = {start, first}

            def dfs(depth: int, current: int) -> list[int] | None:
                if depth == length:
                    if start in graph[current] and path[1] < path[-1]:
                        return path.copy()
                    return None
                for nxt in sorted(graph[current]):
                    if nxt <= start or nxt in used:
                        continue
                    if depth == length - 1 and start not in graph[nxt]:
                        continue
                    path[depth] = nxt
                    used.add(nxt)
                    answer = dfs(depth + 1, nxt)
                    if answer is not None:
                        return answer
                    used.remove(nxt)
                return None

            answer = dfs(2, first)
            if answer is not None:
                return answer
    return None


def connected(graph: list[set[int]]) -> bool:
    seen = {0}
    stack = [0]
    while stack:
        vertex = stack.pop()
        for neighbor in graph[vertex]:
            if neighbor not in seen:
                seen.add(neighbor)
                stack.append(neighbor)
    return len(seen) == len(graph)


def verify(witness: dict) -> dict:
    cap = decode(witness["cap_graph6"])
    n = len(cap)
    terminals = [vertex for vertex, neighbors in enumerate(cap) if len(neighbors) == 2]
    assert len(terminals) == 1
    assert all(len(neighbors) in (2, 3) for neighbors in cap)
    terminal = terminals[0]
    assert terminal == witness["terminal"]
    assert connected(cap)

    graph = [set() for _ in range(2 * n)]
    for vertex, neighbors in enumerate(cap):
        graph[vertex].update(neighbors)
    for vertex, neighbors in enumerate(cap):
        graph[n + vertex].update(n + neighbor for neighbor in neighbors)
    graph[terminal].add(n + terminal)
    graph[n + terminal].add(terminal)

    assert connected(graph)
    assert min(map(len, graph)) >= 3
    checked = []
    power = 4
    while power <= len(graph):
        cycle = first_cycle(graph, power)
        checked.append(power)
        if cycle is not None:
            raise AssertionError(f"C_{power} found: {cycle}")
        power *= 2
    return {
        "verified": True,
        "order": len(graph),
        "minimum_degree": min(map(len, graph)),
        "checked_power_cycle_lengths": checked,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("witness")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = verify(json.loads(Path(args.witness).read_text(encoding="utf-8")))
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
