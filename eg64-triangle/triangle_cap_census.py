#!/usr/bin/env python3
"""Exact rooted cubic census for terminal-triangle cap expansions.

Replace a cubic base edge uv by vertices p,q,t and edges
u-p, p-q, q-v, p-t, q-t. Vertex t is the unique degree-2 terminal; p,q and all
base vertices have degree 3.

A base cycle not using uv survives unchanged. A base cycle of length L using uv
lifts to cycles of lengths L+2 and L+3, corresponding to the two p-q paths in
the triangle. Therefore an edge is valid exactly when:
  * it lies in every power-of-two cycle of the base; and
  * it lies in no cycle of length 2^k-2 or 2^k-3 relevant to the cap order.
The test is exact and avoids constructing every expanded graph.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eg64-census"))
from cubic_cap_census import (  # noqa: E402
    edge_index_map,
    edges_from_adj,
    has_cycle_length_through_edge,
    parse_graph6,
    power_cycle_intersection,
    powers_of_two_le,
    validate_connected_cubic,
)


def add_edge(adjacency: list[int], first: int, second: int) -> None:
    if first == second or ((adjacency[first] >> second) & 1):
        raise ValueError(f"invalid edge insertion {(first, second)}")
    adjacency[first] |= 1 << second
    adjacency[second] |= 1 << first


def remove_edge(adjacency: list[int], first: int, second: int) -> None:
    if not ((adjacency[first] >> second) & 1):
        raise ValueError(f"missing edge {(first, second)}")
    adjacency[first] &= ~(1 << second)
    adjacency[second] &= ~(1 << first)


def triangle_expand(base: tuple[int, ...], edge: tuple[int, int]) -> tuple[tuple[int, ...], int]:
    order = len(base)
    p, q, terminal = order, order + 1, order + 2
    graph = list(base) + [0, 0, 0]
    first, second = edge
    remove_edge(graph, first, second)
    add_edge(graph, first, p)
    add_edge(graph, p, q)
    add_edge(graph, q, second)
    add_edge(graph, p, terminal)
    add_edge(graph, q, terminal)
    degrees = [neighbors.bit_count() for neighbors in graph]
    if degrees[terminal] != 2 or any(
        degree != 3 for vertex, degree in enumerate(degrees) if vertex != terminal
    ):
        raise AssertionError(degrees)
    return tuple(graph), terminal


def graph_edges(adjacency: tuple[int, ...]) -> list[list[int]]:
    return [list(edge) for edge in edges_from_adj(adjacency)]


def relevant_precursor_lengths(cap_order: int) -> tuple[int, ...]:
    lengths = set()
    for power in powers_of_two_le(cap_order):
        for offset in (2, 3):
            length = power - offset
            if length >= 3:
                lengths.add(length)
    return tuple(sorted(lengths))


def candidate_edges(
    base: tuple[int, ...],
) -> tuple[list[tuple[int, int]], dict[int, int], str | None]:
    edges, _index = edge_index_map(base)
    saw_power, intersection, scanned = power_cycle_intersection(base)
    if not saw_power:
        return [], scanned, "base_graph_is_counterexample"
    candidates = []
    precursors = relevant_precursor_lengths(len(base) + 3)
    for index, edge in enumerate(edges):
        if not ((intersection >> index) & 1):
            continue
        if any(has_cycle_length_through_edge(base, length, edge) for length in precursors):
            continue
        candidates.append(edge)
    return candidates, scanned, None


@dataclass
class Stats:
    base_order: int
    expected: int | None
    graphs: int = 0
    rooted_edges_tested: int = 0
    graphs_with_common_power_edge: int = 0
    valid_triangle_edges: int = 0
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
    start = time.monotonic()
    witness = None

    for raw in sys.stdin.buffer:
        if not raw.strip() or raw.startswith(b">>"):
            continue
        digest.update(raw)
        order, base = parse_graph6(raw)
        if order != args.order:
            raise ValueError(f"expected order {args.order}, got {order}")
        validate_connected_cubic(base)
        stats.graphs += 1
        candidates, scanned, special = candidate_edges(base)
        if special == "base_graph_is_counterexample":
            witness = {
                "kind": special,
                "order": order,
                "base_graph6": raw.strip().decode("ascii"),
                "base_edges": graph_edges(base),
                "cycles_scanned": scanned,
            }
            break
        _edges, _ = edge_index_map(base)
        saw, intersection, _ = power_cycle_intersection(base)
        if saw and intersection:
            stats.graphs_with_common_power_edge += 1
            stats.rooted_edges_tested += intersection.bit_count()
        if candidates:
            stats.valid_triangle_edges += len(candidates)
            cap, terminal = triangle_expand(base, candidates[0])
            witness = {
                "kind": "terminal_triangle_cap",
                "base_order": order,
                "base_graph6": raw.strip().decode("ascii"),
                "expanded_edge": list(candidates[0]),
                "all_valid_edges": [list(edge) for edge in candidates],
                "cap_order": len(cap),
                "terminal": terminal,
                "cap_edges": graph_edges(cap),
                "doubled_counterexample_order": 2 * len(cap),
                "precursor_lengths_checked": list(relevant_precursor_lengths(len(cap))),
                "cycles_scanned": scanned,
            }
            break
        if args.progress and stats.graphs % args.progress == 0:
            print(
                json.dumps({"order": order, "progress": stats.graphs,
                            "seconds": time.monotonic() - start}),
                file=sys.stderr,
                flush=True,
            )

    stats.seconds = time.monotonic() - start
    stats.input_sha256 = digest.hexdigest()
    result = {"stats": asdict(stats), "witness": witness}
    if args.expected is not None and witness is None and stats.graphs != args.expected:
        result["count_error"] = {"expected": args.expected, "actual": stats.graphs}
        print(json.dumps(result, sort_keys=True))
        return 2
    if witness is not None and args.witness_out:
        Path(args.witness_out).write_text(json.dumps(witness, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 10 if witness is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
