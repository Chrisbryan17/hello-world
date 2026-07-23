#!/usr/bin/env python3
"""Exhaust gauge-normalized odd cyclic lifts of connected cubic base graphs.

For an oriented base edge u<v carrying voltage a in Z_q, the q-lift joins
(u,i) to (v,i+a). Switching at base vertices allows every voltage on a fixed
spanning tree to be set to zero, so enumerating the cotree-edge voltages is
complete up to switching. For prime q, the lift is connected exactly when at
least one normalized cotree voltage is nonzero.

This program reads connected cubic graph6 records from stdin and exhausts all
normalized voltage assignments for a specified odd prime q. Every connected
lift is checked exactly for cycles of lengths 4,8,16,... up to its order.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator


def parse_graph6(raw: bytes) -> tuple[int, ...]:
    data = raw.strip()
    if data.startswith(b">>graph6<<"):
        data = data[len(b">>graph6<<"):]
    values = [value - 63 for value in data]
    if not values or values[0] > 62 or any(value < 0 or value > 63 for value in values):
        raise ValueError("unsupported graph6 record")
    order = values[0]
    bits: list[int] = []
    for value in values[1:]:
        bits.extend((value >> shift) & 1 for shift in range(5, -1, -1))
    required = order * (order - 1) // 2
    if len(bits) < required:
        raise ValueError("truncated graph6")
    adjacency = [0] * order
    index = 0
    for high in range(1, order):
        for low in range(high):
            if bits[index]:
                adjacency[low] |= 1 << high
                adjacency[high] |= 1 << low
            index += 1
    return tuple(adjacency)


def iter_bits(mask: int) -> Iterator[int]:
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def edge_list(adjacency: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
    return tuple(
        (first, second)
        for first, neighbors in enumerate(adjacency)
        for second in range(first + 1, len(adjacency))
        if (neighbors >> second) & 1
    )


def validate_connected_cubic(adjacency: tuple[int, ...]) -> None:
    if not adjacency or any(neighbors.bit_count() != 3 for neighbors in adjacency):
        raise ValueError("base graph is not cubic")
    if not connected(adjacency):
        raise ValueError("base graph is disconnected")


def connected(adjacency: tuple[int, ...]) -> bool:
    if not adjacency:
        return False
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


def spanning_tree_and_cotree(
    adjacency: tuple[int, ...],
) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]:
    discovered = {0}
    stack = [0]
    tree: set[tuple[int, int]] = set()
    while stack:
        vertex = stack.pop()
        for neighbor in iter_bits(adjacency[vertex]):
            if neighbor in discovered:
                continue
            discovered.add(neighbor)
            stack.append(neighbor)
            tree.add(tuple(sorted((vertex, neighbor))))
    all_edges = set(edge_list(adjacency))
    return tuple(sorted(tree)), tuple(sorted(all_edges - tree))


def cyclic_lift(
    base: tuple[int, ...],
    modulus: int,
    cotree: tuple[tuple[int, int], ...],
    assignment: tuple[int, ...],
) -> tuple[int, ...]:
    voltages = {edge: value % modulus for edge, value in zip(cotree, assignment)}
    order = len(base) * modulus
    lift = [0] * order

    def index(vertex: int, fiber: int) -> int:
        return vertex * modulus + fiber

    for first, second in edge_list(base):
        voltage = voltages.get((first, second), 0)
        for fiber in range(modulus):
            left = index(first, fiber)
            right = index(second, (fiber + voltage) % modulus)
            lift[left] |= 1 << right
            lift[right] |= 1 << left
    return tuple(lift)


def first_cycle(adjacency: tuple[int, ...], length: int) -> tuple[int, ...] | None:
    order = len(adjacency)
    if length < 3 or length > order:
        return None
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


def first_power_cycle(adjacency: tuple[int, ...]) -> tuple[int, tuple[int, ...]] | None:
    power = 4
    while power <= len(adjacency):
        cycle = first_cycle(adjacency, power)
        if cycle is not None:
            return power, cycle
        power *= 2
    return None


def lift_edges(adjacency: tuple[int, ...]) -> list[list[int]]:
    return [list(edge) for edge in edge_list(adjacency)]


@dataclass
class Stats:
    base_order: int
    modulus: int
    expected_bases: int | None
    bases: int = 0
    normalized_assignments: int = 0
    connected_lifts: int = 0
    rejected_c4: int = 0
    rejected_c8: int = 0
    rejected_c16: int = 0
    elapsed_seconds: float = 0.0
    input_sha256: str = ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-order", type=int, required=True)
    parser.add_argument("--modulus", type=int, required=True)
    parser.add_argument("--expected-bases", type=int)
    parser.add_argument("--checkpoint")
    parser.add_argument("--witness-out")
    args = parser.parse_args()

    if args.modulus < 3 or args.modulus % 2 == 0:
        raise ValueError("modulus must be odd and at least 3")
    stats = Stats(args.base_order, args.modulus, args.expected_bases)
    start = time.monotonic()
    digest = hashlib.sha256()
    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    witness_path = Path(args.witness_out) if args.witness_out else None
    witness = None

    def write_checkpoint(status: str) -> None:
        stats.elapsed_seconds = time.monotonic() - start
        if checkpoint is not None:
            checkpoint.write_text(
                json.dumps({"status": status, "stats": asdict(stats), "witness": witness},
                           indent=2, sort_keys=True) + "\n",
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

        for assignment in itertools.product(range(args.modulus), repeat=len(cotree)):
            stats.normalized_assignments += 1
            if math.gcd(args.modulus, *assignment) != 1:
                continue
            lift = cyclic_lift(base, args.modulus, cotree, assignment)
            if not connected(lift):
                raise AssertionError("gcd-connected normalized lift was disconnected")
            if any(neighbors.bit_count() != 3 for neighbors in lift):
                raise AssertionError("lift is not cubic")
            stats.connected_lifts += 1
            forbidden = first_power_cycle(lift)
            if forbidden is None:
                witness = {
                    "kind": "odd_cyclic_voltage_lift",
                    "base_order": len(base),
                    "base_graph6": raw.strip().decode("ascii"),
                    "modulus": args.modulus,
                    "tree_edges": [list(edge) for edge in tree],
                    "cotree_edges": [list(edge) for edge in cotree],
                    "cotree_voltages": list(assignment),
                    "order": len(lift),
                    "edges": lift_edges(lift),
                    "stats": asdict(stats),
                }
                if witness_path is not None:
                    witness_path.write_text(json.dumps(witness, indent=2, sort_keys=True) + "\n")
                write_checkpoint("witness")
                print(json.dumps({"status": "witness", "stats": asdict(stats), "witness": witness}, sort_keys=True))
                return 10
            length = forbidden[0]
            if length == 4:
                stats.rejected_c4 += 1
            elif length == 8:
                stats.rejected_c8 += 1
            elif length == 16:
                stats.rejected_c16 += 1
            else:
                raise AssertionError(f"unexpected power length {length} at order {len(lift)}")

        write_checkpoint("running")

    stats.input_sha256 = digest.hexdigest()
    stats.elapsed_seconds = time.monotonic() - start
    if args.expected_bases is not None and stats.bases != args.expected_bases:
        write_checkpoint("count_error")
        print(json.dumps({"status": "count_error", "stats": asdict(stats)}, sort_keys=True))
        return 2
    write_checkpoint("exhausted")
    print(json.dumps({"status": "exhausted", "stats": asdict(stats), "witness": None}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
