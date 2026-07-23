#!/usr/bin/env python3
"""Search cubic graphs for a power-avoiding three-pole multiplier gadget.

Delete a vertex v from a connected cubic graph Q. If every power-of-two cycle
of Q contains v, then H=Q-v has no internal power-of-two cycle. Let T be its
three degree-2 terminals. If an odd q>1 divides |P|+1 for every simple path P
between every pair of terminals, replacing every vertex of any simple cubic
base graph by H makes every non-internal cycle length divisible by q. Since q
is odd and all internal cycles are non-powers, this yields a cubic
Erdos--Gyarfas counterexample.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from typing import Iterator


def parse_graph6(line: bytes) -> tuple[int, tuple[int, ...]]:
    data = line.strip()
    if data.startswith(b">>graph6<<"):
        data = data[len(b">>graph6<<"):]
    values = [value - 63 for value in data]
    if not values or values[0] > 62 or any(value < 0 or value > 63 for value in values):
        raise ValueError("unsupported graph6 record")
    n = values[0]
    bits_out: list[int] = []
    for value in values[1:]:
        bits_out.extend((value >> shift) & 1 for shift in range(5, -1, -1))
    if len(bits_out) < n * (n - 1) // 2:
        raise ValueError("truncated graph6")
    adj = [0] * n
    index = 0
    for high in range(1, n):
        for low in range(high):
            if bits_out[index]:
                adj[low] |= 1 << high
                adj[high] |= 1 << low
            index += 1
    return n, tuple(adj)


def iter_bits(mask: int) -> Iterator[int]:
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def validate_connected_cubic(adj: tuple[int, ...]) -> None:
    if not adj or any(neighbors.bit_count() != 3 for neighbors in adj):
        raise ValueError("input is not cubic")
    seen = 1
    frontier = 1
    while frontier:
        bit = frontier & -frontier
        frontier ^= bit
        vertex = bit.bit_length() - 1
        new = adj[vertex] & ~seen
        seen |= new
        frontier |= new
    if seen.bit_count() != len(adj):
        raise ValueError("input is disconnected")


def canonical_cycles(adj: tuple[int, ...], length: int) -> Iterator[tuple[int, ...]]:
    n = len(adj)
    if length > n:
        return
    path = [0] * length
    for start in range(n):
        path[0] = start
        for first in iter_bits(adj[start] & ~((1 << (start + 1)) - 1)):
            path[1] = first

            def dfs(depth: int, current: int, used: int) -> Iterator[tuple[int, ...]]:
                if depth == length:
                    if ((adj[current] >> start) & 1) and path[1] < path[-1]:
                        yield tuple(path)
                    return
                candidates = adj[current] & ~used & ~((1 << (start + 1)) - 1)
                if depth == length - 1:
                    candidates &= adj[start]
                for nxt in iter_bits(candidates):
                    path[depth] = nxt
                    yield from dfs(depth + 1, nxt, used | (1 << nxt))

            yield from dfs(2, first, (1 << start) | (1 << first))


def power_cycle_vertex_intersection(
    adj: tuple[int, ...],
) -> tuple[bool, int, dict[int, int]]:
    intersection = (1 << len(adj)) - 1
    saw_cycle = False
    counts: dict[int, int] = {}
    power = 4
    while power <= len(adj):
        count = 0
        for cycle in canonical_cycles(adj, power):
            saw_cycle = True
            count += 1
            vertex_mask = 0
            for vertex in cycle:
                vertex_mask |= 1 << vertex
            intersection &= vertex_mask
            if intersection == 0:
                counts[power] = count
                return saw_cycle, 0, counts
        counts[power] = count
        power *= 2
    return saw_cycle, intersection, counts


def delete_vertex(
    adj: tuple[int, ...], vertex: int
) -> tuple[tuple[int, ...], tuple[int, int, int]]:
    retained = [old for old in range(len(adj)) if old != vertex]
    new_index = {old: new for new, old in enumerate(retained)}
    smaller = [0] * len(retained)
    for old in retained:
        for neighbor in iter_bits(adj[old]):
            if neighbor != vertex:
                smaller[new_index[old]] |= 1 << new_index[neighbor]
    terminals = tuple(new_index[neighbor] for neighbor in iter_bits(adj[vertex]))
    if len(terminals) != 3:
        raise AssertionError("deleted cubic vertex did not expose three terminals")
    return tuple(smaller), terminals


def odd_part(number: int) -> int:
    while number and number % 2 == 0:
        number //= 2
    return number


def path_gcd_plus_one(
    graph: tuple[int, ...], start: int, target: int, current_gcd: int
) -> tuple[int, int]:
    """GCD of length+1 over all simple start-target paths, with early rejection."""

    def dfs(vertex: int, used: int, length: int, running_gcd: int) -> tuple[int, int]:
        if vertex == target:
            return math.gcd(running_gcd, length + 1), 1
        paths = 0
        for neighbor in iter_bits(graph[vertex] & ~used):
            contribution, count = dfs(
                neighbor, used | (1 << neighbor), length + 1, running_gcd
            )
            running_gcd = math.gcd(running_gcd, contribution)
            paths += count
            if odd_part(running_gcd) == 1:
                return running_gcd, paths
        return running_gcd, paths

    return dfs(start, 1 << start, 0, current_gcd)


def gadget_at(
    adj: tuple[int, ...], vertex: int
) -> tuple[dict | None, dict[str, int], int]:
    gadget, terminals = delete_vertex(adj, vertex)
    running_gcd = 0
    path_counts: dict[str, int] = {}
    for first in range(3):
        for second in range(first + 1, 3):
            running_gcd, count = path_gcd_plus_one(
                gadget, terminals[first], terminals[second], running_gcd
            )
            path_counts[f"{terminals[first]}-{terminals[second]}"] = count
            if odd_part(running_gcd) == 1:
                return None, path_counts, running_gcd
    multiplier = odd_part(running_gcd)
    if multiplier <= 1:
        return None, path_counts, running_gcd
    return (
        {
            "deleted_vertex": vertex,
            "terminals": list(terminals),
            "path_plus_one_gcd": running_gcd,
            "odd_multiplier": multiplier,
        },
        path_counts,
        running_gcd,
    )


@dataclass
class Stats:
    order: int
    expected: int | None
    graphs: int = 0
    graphs_with_vertex_intersection: int = 0
    candidate_vertices: int = 0
    seconds: float = 0.0
    input_sha256: str = ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order", type=int, required=True)
    parser.add_argument("--expected", type=int)
    parser.add_argument("--progress", type=int, default=100000)
    parser.add_argument("--witness-out")
    args = parser.parse_args()

    stats = Stats(args.order, args.expected)
    digest = hashlib.sha256()
    start_time = time.monotonic()
    witness = None

    for raw in sys.stdin.buffer:
        if not raw.strip() or raw.startswith(b">>"):
            continue
        digest.update(raw)
        order, adj = parse_graph6(raw)
        if order != args.order:
            raise ValueError(f"expected order {args.order}, received {order}")
        validate_connected_cubic(adj)
        stats.graphs += 1
        saw_cycle, intersection, scanned = power_cycle_vertex_intersection(adj)
        if not saw_cycle:
            witness = {
                "kind": "base_graph_counterexample",
                "graph6": raw.strip().decode("ascii"),
                "order": order,
            }
            break
        if intersection:
            stats.graphs_with_vertex_intersection += 1
            for vertex in iter_bits(intersection):
                stats.candidate_vertices += 1
                candidate, path_counts, _gcd = gadget_at(adj, vertex)
                if candidate is not None:
                    witness = {
                        "kind": "three_pole_multiplier",
                        "base_graph6": raw.strip().decode("ascii"),
                        "base_order": order,
                        **candidate,
                        "path_counts": path_counts,
                        "power_cycles_scanned": scanned,
                    }
                    break
            if witness is not None:
                break
        if args.progress and stats.graphs % args.progress == 0:
            print(
                json.dumps(
                    {"order": order, "progress": stats.graphs,
                     "seconds": time.monotonic() - start_time}
                ),
                file=sys.stderr,
                flush=True,
            )

    stats.seconds = time.monotonic() - start_time
    stats.input_sha256 = digest.hexdigest()
    result = {"stats": asdict(stats), "witness": witness}
    if args.expected is not None and witness is None and stats.graphs != args.expected:
        result["count_error"] = {"expected": args.expected, "actual": stats.graphs}
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
