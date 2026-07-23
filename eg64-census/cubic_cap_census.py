#!/usr/bin/env python3
"""Exact edge-subdivision cap census for connected cubic graphs in graph6.

For each connected cubic graph Q, test whether subdividing some edge e produces
an almost-cubic cap H (one degree-2 vertex, all others degree 3) with no cycle
whose length is a power of two. If so, joining two copies of H at their unique
degree-2 vertices by a bridge gives an Erdős--Gyárfás counterexample.

The test is exact:
  * every power-of-two cycle of Q must contain e (otherwise it survives), and
  * no (2^k - 1)-cycle of Q may contain e (otherwise subdivision creates C_{2^k}).

Input: one graph6 graph per line on stdin.
Output: JSON summary to stdout; progress goes to stderr.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict, dataclass
from typing import Iterator


def powers_of_two_le(n: int) -> tuple[int, ...]:
    out = []
    p = 4
    while p <= n:
        out.append(p)
        p *= 2
    return tuple(out)


def parse_graph6(line: bytes) -> tuple[int, tuple[int, ...]]:
    data = line.strip()
    if data.startswith(b">>graph6<<"):
        data = data[len(b">>graph6<<"):]
    if not data:
        raise ValueError("empty graph6 line")
    values = [b - 63 for b in data]
    if any(v < 0 or v > 63 for v in values):
        raise ValueError("invalid graph6 character")
    if values[0] <= 62:
        n = values[0]
        pos = 1
    elif len(values) >= 4 and values[0] == 63 and values[1] != 63:
        n = (values[1] << 12) | (values[2] << 6) | values[3]
        pos = 4
    else:
        raise ValueError("large graph6 orders are not supported by this census")
    need = n * (n - 1) // 2
    bits: list[int] = []
    for value in values[pos:]:
        bits.extend((value >> shift) & 1 for shift in range(5, -1, -1))
    if len(bits) < need:
        raise ValueError(f"truncated graph6: need {need} bits, got {len(bits)}")
    adj = [0] * n
    k = 0
    for j in range(1, n):
        for i in range(j):
            if bits[k]:
                adj[i] |= 1 << j
                adj[j] |= 1 << i
            k += 1
    return n, tuple(adj)


def edges_from_adj(adj: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
    return tuple(
        (u, v)
        for u, mask in enumerate(adj)
        for v in range(u + 1, len(adj))
        if (mask >> v) & 1
    )


def validate_connected_cubic(adj: tuple[int, ...]) -> None:
    n = len(adj)
    if n == 0 or any(mask.bit_count() != 3 for mask in adj):
        raise ValueError("input is not cubic")
    seen = 1
    frontier = 1
    while frontier:
        bit = frontier & -frontier
        frontier ^= bit
        v = bit.bit_length() - 1
        new = adj[v] & ~seen
        seen |= new
        frontier |= new
    if seen.bit_count() != n:
        raise ValueError("input cubic graph is disconnected")


def iter_bits(mask: int) -> Iterator[int]:
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def canonical_cycles(adj: tuple[int, ...], length: int) -> Iterator[tuple[int, ...]]:
    """Enumerate each undirected simple cycle exactly once."""
    n = len(adj)
    if length < 3 or length > n:
        return
    path = [0] * length
    for start in range(n):
        path[0] = start
        start_bit = 1 << start
        first_mask = adj[start] & ~((1 << (start + 1)) - 1)
        for first in iter_bits(first_mask):
            path[1] = first
            visited = start_bit | (1 << first)

            def dfs(depth: int, vertex: int, used: int) -> Iterator[tuple[int, ...]]:
                if depth == length:
                    if ((adj[vertex] >> start) & 1) and path[1] < path[-1]:
                        yield tuple(path)
                    return
                candidates = adj[vertex] & ~used & ~((1 << (start + 1)) - 1)
                if depth == length - 1:
                    candidates &= adj[start]
                for nxt in iter_bits(candidates):
                    path[depth] = nxt
                    yield from dfs(depth + 1, nxt, used | (1 << nxt))

            yield from dfs(2, first, visited)


def edge_index_map(
    adj: tuple[int, ...],
) -> tuple[tuple[tuple[int, int], ...], dict[tuple[int, int], int]]:
    edges = edges_from_adj(adj)
    return edges, {e: i for i, e in enumerate(edges)}


def cycle_edge_mask(
    cycle: tuple[int, ...], edge_index: dict[tuple[int, int], int]
) -> int:
    mask = 0
    length = len(cycle)
    for i, u in enumerate(cycle):
        v = cycle[(i + 1) % length]
        edge = (u, v) if u < v else (v, u)
        mask |= 1 << edge_index[edge]
    return mask


def power_cycle_intersection(
    adj: tuple[int, ...],
) -> tuple[bool, int, dict[int, int]]:
    """Return (saw_power_cycle, intersection edge mask, cycles scanned by length)."""
    edges, index = edge_index_map(adj)
    candidate = (1 << len(edges)) - 1
    saw = False
    scanned: dict[int, int] = {}
    for length in powers_of_two_le(len(adj)):
        count = 0
        for cycle in canonical_cycles(adj, length):
            saw = True
            count += 1
            candidate &= cycle_edge_mask(cycle, index)
            if candidate == 0:
                scanned[length] = count
                return saw, 0, scanned
        scanned[length] = count
    return saw, candidate, scanned


def has_cycle_length_through_edge(
    adj: tuple[int, ...], length: int, edge: tuple[int, int]
) -> bool:
    """Exact DFS for a simple cycle of given length containing edge."""
    if length < 3 or length > len(adj):
        return False
    u, v = edge
    target_edges = length - 1

    def dfs(cur: int, depth_edges: int, used: int) -> bool:
        if depth_edges == target_edges:
            return cur == v
        remaining = target_edges - depth_edges
        candidates = adj[cur]
        if cur == u:
            candidates &= ~(1 << v)
        candidates &= ~used
        if remaining == 1:
            return bool((adj[cur] >> v) & 1)
        candidates &= ~(1 << v)
        for nxt in iter_bits(candidates):
            if dfs(nxt, depth_edges + 1, used | (1 << nxt)):
                return True
        return False

    return dfs(u, 0, 1 << u)


def candidate_subdivision_edges(
    adj: tuple[int, ...],
) -> tuple[list[tuple[int, int]], dict[int, int], str | None]:
    edges, _ = edge_index_map(adj)
    saw, intersection, scanned = power_cycle_intersection(adj)
    if not saw:
        return [], scanned, "base_graph_is_counterexample"
    candidates: list[tuple[int, int]] = []
    for i, edge in enumerate(edges):
        if not ((intersection >> i) & 1):
            continue
        creates_power = False
        for power in powers_of_two_le(len(adj) + 1):
            if has_cycle_length_through_edge(adj, power - 1, edge):
                creates_power = True
                break
        if not creates_power:
            candidates.append(edge)
    return candidates, scanned, None


@dataclass
class OrderStats:
    order: int
    expected: int | None
    graphs: int = 0
    graphs_with_power_cycle_intersection: int = 0
    subdivision_candidates: int = 0
    seconds: float = 0.0
    input_sha256: str = ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order", type=int, required=True)
    parser.add_argument("--expected", type=int)
    parser.add_argument("--progress", type=int, default=100000)
    parser.add_argument("--witness-out")
    args = parser.parse_args()

    stats = OrderStats(order=args.order, expected=args.expected)
    digest = hashlib.sha256()
    start = time.monotonic()
    witness = None

    for raw in sys.stdin.buffer:
        if not raw.strip() or raw.startswith(b">>"):
            continue
        digest.update(raw)
        n, adj = parse_graph6(raw)
        if n != args.order:
            raise ValueError(f"expected order {args.order}, got {n}")
        validate_connected_cubic(adj)
        stats.graphs += 1
        candidates, scanned, special = candidate_subdivision_edges(adj)
        if special == "base_graph_is_counterexample":
            witness = {
                "kind": special,
                "order": n,
                "graph6": raw.strip().decode("ascii"),
                "cycles_scanned": scanned,
            }
            break
        if candidates:
            stats.graphs_with_power_cycle_intersection += 1
            stats.subdivision_candidates += len(candidates)
            witness = {
                "kind": "edge_subdivision_cap",
                "base_order": n,
                "base_graph6": raw.strip().decode("ascii"),
                "edges": [list(e) for e in candidates],
                "cycles_scanned": scanned,
            }
            break
        if args.progress and stats.graphs % args.progress == 0:
            elapsed = time.monotonic() - start
            print(
                json.dumps({"progress": stats.graphs, "order": n, "seconds": elapsed}),
                file=sys.stderr,
                flush=True,
            )

    stats.seconds = time.monotonic() - start
    stats.input_sha256 = digest.hexdigest()
    result = {"stats": asdict(stats), "witness": witness}
    if args.expected is not None and witness is None and stats.graphs != args.expected:
        result["count_error"] = {"expected": args.expected, "actual": stats.graphs}
        print(json.dumps(result, sort_keys=True), flush=True)
        return 2
    if witness and args.witness_out:
        with open(args.witness_out, "w", encoding="utf-8") as handle:
            json.dump(witness, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(json.dumps(result, sort_keys=True), flush=True)
    return 10 if witness else 0


if __name__ == "__main__":
    raise SystemExit(main())
