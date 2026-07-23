#!/usr/bin/env python3
"""Exhaust connected F_3^2 voltage lifts of connected cubic base graphs.

A fixed spanning-tree gauge sets all tree-edge voltages to zero. Cotree edges
receive vectors in F_3^2. The 9-fold lift is connected exactly when those
vectors span the full two-dimensional vector space. Every connected normalized
assignment is tested exactly for cycles of lengths 4,8,16,... up to the lift
order.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from cyclic_lift_census import (
    connected,
    edge_list,
    first_power_cycle,
    lift_edges,
    parse_graph6,
    spanning_tree_and_cotree,
    validate_connected_cubic,
)

ELEMENTS: tuple[tuple[int, int], ...] = tuple(
    (first, second) for first in range(3) for second in range(3)
)


def add_vector(left: tuple[int, int], right: tuple[int, int]) -> tuple[int, int]:
    return ((left[0] + right[0]) % 3, (left[1] + right[1]) % 3)


def rank_two(vectors: tuple[tuple[int, int], ...]) -> bool:
    nonzero = [vector for vector in vectors if vector != (0, 0)]
    for index, first in enumerate(nonzero):
        for second in nonzero[index + 1 :]:
            if (first[0] * second[1] - first[1] * second[0]) % 3 != 0:
                return True
    return False


def lift_f3_square(
    base: tuple[int, ...],
    cotree: tuple[tuple[int, int], ...],
    assignment: tuple[tuple[int, int], ...],
) -> tuple[int, ...]:
    voltages = {edge: vector for edge, vector in zip(cotree, assignment)}
    fiber_index = {vector: index for index, vector in enumerate(ELEMENTS)}
    order = len(base) * 9
    graph = [0] * order

    def index(vertex: int, vector: tuple[int, int]) -> int:
        return vertex * 9 + fiber_index[vector]

    for first, second in edge_list(base):
        voltage = voltages.get((first, second), (0, 0))
        for vector in ELEMENTS:
            left = index(first, vector)
            right = index(second, add_vector(vector, voltage))
            graph[left] |= 1 << right
            graph[right] |= 1 << left
    return tuple(graph)


@dataclass
class Stats:
    base_order: int
    expected_bases: int | None
    bases: int = 0
    normalized_assignments: int = 0
    connected_lifts: int = 0
    rejected_by_length: dict[str, int] | None = None
    elapsed_seconds: float = 0.0
    input_sha256: str = ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-order", type=int, required=True)
    parser.add_argument("--expected-bases", type=int)
    parser.add_argument("--checkpoint")
    parser.add_argument("--witness-out")
    args = parser.parse_args()

    stats = Stats(
        base_order=args.base_order,
        expected_bases=args.expected_bases,
        rejected_by_length={},
    )
    start = time.monotonic()
    digest = hashlib.sha256()
    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    witness_path = Path(args.witness_out) if args.witness_out else None
    witness = None

    def save(status: str) -> None:
        stats.elapsed_seconds = time.monotonic() - start
        if checkpoint is not None:
            checkpoint.write_text(
                json.dumps(
                    {"status": status, "stats": asdict(stats), "witness": witness},
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )

    for raw in sys.stdin.buffer:
        if not raw.strip() or raw.startswith(b">>"):
            continue
        digest.update(raw)
        base = parse_graph6(raw)
        if len(base) != args.base_order:
            raise ValueError(f"expected base order {args.base_order}, got {len(base)}")
        validate_connected_cubic(base)
        stats.bases += 1
        tree, cotree = spanning_tree_and_cotree(base)
        expected_rank = len(edge_list(base)) - len(base) + 1
        if len(cotree) != expected_rank:
            raise AssertionError("incorrect cycle rank")

        for assignment in itertools.product(ELEMENTS, repeat=len(cotree)):
            stats.normalized_assignments += 1
            if not rank_two(assignment):
                continue
            lift = lift_f3_square(base, cotree, assignment)
            if not connected(lift):
                raise AssertionError("rank-two normalized lift was disconnected")
            if any(neighbors.bit_count() != 3 for neighbors in lift):
                raise AssertionError("lift is not cubic")
            stats.connected_lifts += 1
            forbidden = first_power_cycle(lift)
            if forbidden is None:
                witness = {
                    "kind": "f3_square_voltage_lift",
                    "group": "F_3^2",
                    "base_order": len(base),
                    "base_graph6": raw.strip().decode("ascii"),
                    "tree_edges": [list(edge) for edge in tree],
                    "cotree_edges": [list(edge) for edge in cotree],
                    "cotree_voltages": [list(vector) for vector in assignment],
                    "order": len(lift),
                    "edges": lift_edges(lift),
                    "stats": asdict(stats),
                }
                if witness_path is not None:
                    witness_path.write_text(
                        json.dumps(witness, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                save("witness")
                print(
                    json.dumps(
                        {"status": "witness", "stats": asdict(stats), "witness": witness},
                        sort_keys=True,
                    )
                )
                return 10
            key = str(forbidden[0])
            stats.rejected_by_length[key] = stats.rejected_by_length.get(key, 0) + 1

        save("running")

    stats.input_sha256 = digest.hexdigest()
    stats.elapsed_seconds = time.monotonic() - start
    if args.expected_bases is not None and stats.bases != args.expected_bases:
        save("count_error")
        print(json.dumps({"status": "count_error", "stats": asdict(stats)}, sort_keys=True))
        return 2
    save("exhausted")
    print(json.dumps({"status": "exhausted", "stats": asdict(stats), "witness": None}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
