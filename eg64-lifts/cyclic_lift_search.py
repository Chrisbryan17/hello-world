#!/usr/bin/env python3
"""Exhaust cyclic odd voltage lifts of connected cubic graph6 bases.

For each base graph, a deterministic spanning tree is assigned voltage zero.
Every Z/qZ voltage assignment is switching-equivalent to exactly such a
normalization, so enumerating the cotree voltages covers every cyclic q-lift
(up to harmless duplication). A lift with no cycle of power-of-two length is
an explicit cubic counterexample to the Erdős--Gyárfás conjecture.
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


def parse_graph6(raw: bytes) -> tuple[int, tuple[int, ...]]:
    data = raw.strip()
    if data.startswith(b">>graph6<<"):
        data = data[len(b">>graph6<<"):]
    values = [char - 63 for char in data]
    if not values or values[0] > 62 or any(value < 0 or value > 63 for value in values):
        raise ValueError("only graph6 bases of order at most 62 are supported")
    n = values[0]
    bits: list[int] = []
    for value in values[1:]:
        bits.extend((value >> shift) & 1 for shift in range(5, -1, -1))
    required = n * (n - 1) // 2
    if len(bits) < required:
        raise ValueError("truncated graph6 record")
    adjacency = [0] * n
    index = 0
    for high in range(1, n):
        for low in range(high):
            if bits[index]:
                adjacency[low] |= 1 << high
                adjacency[high] |= 1 << low
            index += 1
    return n, tuple(adjacency)


def iter_bits(mask: int) -> Iterator[int]:
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def edge_list(adjacency: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
    return tuple(
        (u, v)
        for u, neighbors in enumerate(adjacency)
        for v in range(u + 1, len(adjacency))
        if (neighbors >> v) & 1
    )


def validate_connected_cubic(adjacency: tuple[int, ...]) -> None:
    if not adjacency or any(neighbors.bit_count() != 3 for neighbors in adjacency):
        raise ValueError("base graph is not cubic")
    seen = 1
    frontier = 1
    while frontier:
        bit = frontier & -frontier
        frontier ^= bit
        vertex = bit.bit_length() - 1
        unseen = adjacency[vertex] & ~seen
        seen |= unseen
        frontier |= unseen
    if seen.bit_count() != len(adjacency):
        raise ValueError("base graph is disconnected")


def deterministic_tree(adjacency: tuple[int, ...]) -> frozenset[tuple[int, int]]:
    seen = {0}
    queue = [0]
    tree: set[tuple[int, int]] = set()
    cursor = 0
    while cursor < len(queue):
        u = queue[cursor]
        cursor += 1
        for v in iter_bits(adjacency[u]):
            if v not in seen:
                seen.add(v)
                queue.append(v)
                tree.add((u, v) if u < v else (v, u))
    if len(seen) != len(adjacency):
        raise ValueError("base graph is disconnected")
    return frozenset(tree)


def construct_lift(
    adjacency: tuple[int, ...], q: int,
    cotree: tuple[tuple[int, int], ...], voltages: tuple[int, ...],
) -> tuple[int, ...]:
    n = len(adjacency)
    lift = [0] * (n * q)
    voltage = dict(zip(cotree, voltages, strict=True))
    for u, v in edge_list(adjacency):
        shift = voltage.get((u, v), 0)
        for fiber in range(q):
            left = u * q + fiber
            right = v * q + ((fiber + shift) % q)
            lift[left] |= 1 << right
            lift[right] |= 1 << left
    if any(neighbors.bit_count() != 3 for neighbors in lift):
        raise AssertionError("constructed lift is not cubic")
    return tuple(lift)


def first_four_cycle(adjacency: tuple[int, ...]) -> tuple[int, ...] | None:
    n = len(adjacency)
    for u in range(n):
        for v in range(u + 1, n):
            common = adjacency[u] & adjacency[v]
            if common.bit_count() >= 2:
                a = (common & -common).bit_length() - 1
                common ^= common & -common
                b = (common & -common).bit_length() - 1
                return (u, a, v, b)
    return None


def first_cycle(adjacency: tuple[int, ...], length: int) -> tuple[int, ...] | None:
    if length == 4:
        return first_four_cycle(adjacency)
    n = len(adjacency)
    if length < 3 or length > n:
        return None
    path = [0] * length
    for start in range(n):
        path[0] = start
        larger_neighbors = adjacency[start] & ~((1 << (start + 1)) - 1)
        for first in iter_bits(larger_neighbors):
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


def first_forbidden_cycle(adjacency: tuple[int, ...]) -> tuple[int, tuple[int, ...]] | None:
    power = 4
    while power <= len(adjacency):
        cycle = first_cycle(adjacency, power)
        if cycle is not None:
            return power, cycle
        power *= 2
    return None


def adjacency_sha256(adjacency: tuple[int, ...]) -> str:
    digest = hashlib.sha256()
    for u, neighbors in enumerate(adjacency):
        for v in range(u + 1, len(adjacency)):
            if (neighbors >> v) & 1:
                digest.update(f"{u},{v}\n".encode())
    return digest.hexdigest()


@dataclass
class Stats:
    base_order: int
    q: int
    expected_bases: int | None
    expected_assignments: int | None
    bases: int = 0
    assignments: int = 0
    rejected_c4: int = 0
    rejected_c8: int = 0
    rejected_c16: int = 0
    rejected_c32: int = 0
    rejected_c64: int = 0
    seconds: float = 0.0
    input_sha256: str = ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order", type=int, required=True)
    parser.add_argument("--q", type=int, required=True)
    parser.add_argument("--expected-bases", type=int)
    parser.add_argument("--progress", type=int, default=100000)
    parser.add_argument("--witness-out")
    args = parser.parse_args()
    if args.q <= 1 or args.q % 2 == 0:
        raise ValueError("q must be odd and greater than one")

    rank = args.order // 2 + 1
    expected_assignments = (
        args.expected_bases * args.q ** rank if args.expected_bases is not None else None
    )
    stats = Stats(args.order, args.q, args.expected_bases, expected_assignments)
    input_digest = hashlib.sha256()
    started = time.monotonic()
    witness = None

    for raw in sys.stdin.buffer:
        if not raw.strip() or raw.startswith(b">>"):
            continue
        input_digest.update(raw)
        order, base = parse_graph6(raw)
        if order != args.order:
            raise ValueError(f"expected base order {args.order}, received {order}")
        validate_connected_cubic(base)
        stats.bases += 1
        tree = deterministic_tree(base)
        cotree = tuple(edge for edge in edge_list(base) if edge not in tree)
        if len(cotree) != rank:
            raise AssertionError((len(cotree), rank))
        for assignment in itertools.product(range(args.q), repeat=rank):
            stats.assignments += 1
            lift = construct_lift(base, args.q, cotree, assignment)
            forbidden = first_forbidden_cycle(lift)
            if forbidden is None:
                full_voltages = [
                    [u, v, dict(zip(cotree, assignment, strict=True)).get((u, v), 0)]
                    for u, v in edge_list(base)
                ]
                witness = {
                    "kind": "cyclic_voltage_lift",
                    "base_graph6": raw.strip().decode("ascii"),
                    "base_order": order,
                    "q": args.q,
                    "edge_voltages": full_voltages,
                    "lift_order": len(lift),
                    "lift_adjacency_sha256": adjacency_sha256(lift),
                }
                break
            length, _cycle = forbidden
            field = f"rejected_c{length}"
            if hasattr(stats, field):
                setattr(stats, field, getattr(stats, field) + 1)
            if args.progress and stats.assignments % args.progress == 0:
                print(json.dumps({
                    "order": order, "q": args.q,
                    "assignments": stats.assignments,
                    "seconds": time.monotonic() - started,
                }), file=sys.stderr, flush=True)
        if witness is not None:
            break

    stats.seconds = time.monotonic() - started
    stats.input_sha256 = input_digest.hexdigest()
    result = {"stats": asdict(stats), "witness": witness}
    if witness is None:
        if args.expected_bases is not None and stats.bases != args.expected_bases:
            result["base_count_error"] = {
                "expected": args.expected_bases, "actual": stats.bases,
            }
            print(json.dumps(result, sort_keys=True))
            return 2
        if expected_assignments is not None and stats.assignments != expected_assignments:
            result["assignment_count_error"] = {
                "expected": expected_assignments, "actual": stats.assignments,
            }
            print(json.dumps(result, sort_keys=True))
            return 3
    if witness is not None and args.witness_out:
        Path(args.witness_out).write_text(
            json.dumps(witness, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(result, sort_keys=True))
    return 10 if witness is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
