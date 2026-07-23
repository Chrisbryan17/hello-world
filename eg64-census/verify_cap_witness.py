#!/usr/bin/env python3
"""Independent verifier for cubic cap-census witnesses.

This intentionally does not import the census checker. It reconstructs either
an asserted cubic counterexample or the doubled subdivided-edge cap, verifies
connectivity and minimum degree, then performs a fresh canonical cycle search
for every power-of-two length up to the resulting order.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def decode_graph6(text: str) -> list[set[int]]:
    raw = text.strip()
    if raw.startswith(">>graph6<<"):
        raw = raw[len(">>graph6<<"):]
    vals = [ord(ch) - 63 for ch in raw]
    if not vals or any(x < 0 or x > 63 for x in vals):
        raise ValueError("invalid graph6")
    if vals[0] <= 62:
        n, pos = vals[0], 1
    elif len(vals) >= 4 and vals[0] == 63 and vals[1] != 63:
        n = (vals[1] << 12) | (vals[2] << 6) | vals[3]
        pos = 4
    else:
        raise ValueError("unsupported graph6 order encoding")
    bits = []
    for value in vals[pos:]:
        bits += [(value >> shift) & 1 for shift in range(5, -1, -1)]
    need = n * (n - 1) // 2
    if len(bits) < need:
        raise ValueError("truncated graph6")
    graph = [set() for _ in range(n)]
    k = 0
    for j in range(1, n):
        for i in range(j):
            if bits[k]:
                graph[i].add(j)
                graph[j].add(i)
            k += 1
    return graph


def is_connected(graph: list[set[int]]) -> bool:
    if not graph:
        return False
    seen = {0}
    stack = [0]
    while stack:
        vertex = stack.pop()
        for neighbor in graph[vertex]:
            if neighbor not in seen:
                seen.add(neighbor)
                stack.append(neighbor)
    return len(seen) == len(graph)


def first_cycle_of_length(graph: list[set[int]], length: int) -> list[int] | None:
    """Return one undirected simple cycle exactly once, or None."""
    n = len(graph)
    if length < 3 or length > n:
        return None
    path = [-1] * length
    for start in range(n):
        path[0] = start
        for first in sorted(w for w in graph[start] if w > start):
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
                    found = dfs(depth + 1, nxt)
                    if found is not None:
                        return found
                    used.remove(nxt)
                return None

            found = dfs(2, first)
            if found is not None:
                return found
    return None


def doubled_subdivision(base: list[set[int]], edge: tuple[int, int]) -> list[set[int]]:
    u, v = edge
    if v not in base[u]:
        raise ValueError("witness edge is absent")
    n = len(base)

    def one_cap() -> list[set[int]]:
        cap = [set(neighbors) for neighbors in base] + [set()]
        cap[u].remove(v)
        cap[v].remove(u)
        cap[u].add(n)
        cap[v].add(n)
        cap[n].update((u, v))
        return cap

    left = one_cap()
    right = one_cap()
    size = n + 1
    graph = [set() for _ in range(2 * size)]
    for i, neighbors in enumerate(left):
        graph[i].update(neighbors)
    for i, neighbors in enumerate(right):
        graph[size + i].update(size + neighbor for neighbor in neighbors)
    graph[n].add(size + n)
    graph[size + n].add(n)
    return graph


def verify(witness: dict) -> dict:
    kind = witness.get("kind")
    if kind == "base_graph_is_counterexample":
        graph = decode_graph6(witness["graph6"])
        construction = "base cubic graph"
    elif kind == "edge_subdivision_cap":
        base = decode_graph6(witness["base_graph6"])
        edges = witness.get("edges") or []
        if not edges:
            raise ValueError("cap witness has no edge")
        graph = doubled_subdivision(base, tuple(edges[0]))
        construction = "two subdivided cubic caps joined by a bridge"
    else:
        raise ValueError(f"unsupported witness kind: {kind!r}")

    degrees = [len(neighbors) for neighbors in graph]
    if not is_connected(graph):
        raise AssertionError("constructed graph is disconnected")
    if min(degrees) < 3:
        raise AssertionError(f"minimum degree is {min(degrees)}, not at least 3")
    checked = []
    power = 4
    while power <= len(graph):
        cycle = first_cycle_of_length(graph, power)
        checked.append(power)
        if cycle is not None:
            raise AssertionError(f"forbidden cycle C_{power} found: {cycle}")
        power *= 2
    return {
        "verified": True,
        "construction": construction,
        "order": len(graph),
        "minimum_degree": min(degrees),
        "power_cycle_lengths_checked": checked,
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
