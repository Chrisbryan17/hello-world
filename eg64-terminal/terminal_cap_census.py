#!/usr/bin/env python3
"""Exact census checker for one-terminal subcubic caps.

A terminal cap is a connected simple graph with exactly one degree-2 vertex and
all other vertices degree 3. If such a cap has no cycle of power-of-two length,
two disjoint copies joined at their degree-2 vertices by one bridge form a
finite simple graph of minimum degree 3 with the same cycle spectrum inside its
blocks, hence a counterexample to the Erdős--Gyárfás conjecture.

Input: graph6 records on stdin, normally produced exactly by
  geng -q -c -d2 -D3 n m:m
where n is odd and m=(3n-1)/2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict, dataclass
from typing import Iterator


def parse_graph6(line: bytes) -> tuple[int, tuple[int, ...]]:
    data = line.strip()
    if data.startswith(b">>graph6<<"):
        data = data[len(b">>graph6<<"):]
    values = [char - 63 for char in data]
    if not values or any(value < 0 or value > 63 for value in values):
        raise ValueError("invalid graph6 record")
    if values[0] <= 62:
        n, pos = values[0], 1
    elif len(values) >= 4 and values[0] == 63 and values[1] != 63:
        n = (values[1] << 12) | (values[2] << 6) | values[3]
        pos = 4
    else:
        raise ValueError("unsupported graph6 order encoding")
    required = n * (n - 1) // 2
    bits: list[int] = []
    for value in values[pos:]:
        bits.extend((value >> shift) & 1 for shift in range(5, -1, -1))
    if len(bits) < required:
        raise ValueError("truncated graph6 record")
    adj = [0] * n
    bit_index = 0
    for high in range(1, n):
        for low in range(high):
            if bits[bit_index]:
                adj[low] |= 1 << high
                adj[high] |= 1 << low
            bit_index += 1
    return n, tuple(adj)


def iter_bits(mask: int) -> Iterator[int]:
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def validate_terminal_cap(adj: tuple[int, ...]) -> int:
    degrees = [neighbors.bit_count() for neighbors in adj]
    terminals = [v for v, degree in enumerate(degrees) if degree == 2]
    if len(terminals) != 1 or any(degree not in (2, 3) for degree in degrees):
        raise ValueError(f"not a one-terminal cap: degree sequence {sorted(degrees)}")
    seen = 1
    frontier = 1
    while frontier:
        bit = frontier & -frontier
        frontier ^= bit
        vertex = bit.bit_length() - 1
        unseen = adj[vertex] & ~seen
        seen |= unseen
        frontier |= unseen
    if seen.bit_count() != len(adj):
        raise ValueError("terminal cap is disconnected")
    return terminals[0]


def first_cycle(adj: tuple[int, ...], length: int) -> tuple[int, ...] | None:
    """Find one undirected simple cycle, using canonical start/orientation."""
    n = len(adj)
    if length < 3 or length > n:
        return None
    path = [0] * length
    for start in range(n):
        path[0] = start
        larger = adj[start] & ~((1 << (start + 1)) - 1)
        for first in iter_bits(larger):
            path[1] = first
            used = (1 << start) | (1 << first)

            def dfs(depth: int, current: int, occupied: int) -> tuple[int, ...] | None:
                if depth == length:
                    if ((adj[current] >> start) & 1) and path[1] < path[-1]:
                        return tuple(path)
                    return None
                candidates = adj[current] & ~occupied & ~((1 << (start + 1)) - 1)
                if depth == length - 1:
                    candidates &= adj[start]
                for nxt in iter_bits(candidates):
                    path[depth] = nxt
                    found = dfs(depth + 1, nxt, occupied | (1 << nxt))
                    if found is not None:
                        return found
                return None

            found = dfs(2, first, used)
            if found is not None:
                return found
    return None


def first_forbidden_cycle(adj: tuple[int, ...]) -> tuple[int, tuple[int, ...]] | None:
    power = 4
    while power <= len(adj):
        cycle = first_cycle(adj, power)
        if cycle is not None:
            return power, cycle
        power *= 2
    return None


@dataclass
class Stats:
    order: int
    expected: int | None
    graphs: int = 0
    rejected_by_length: dict[str, int] | None = None
    seconds: float = 0.0
    input_sha256: str = ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order", type=int, required=True)
    parser.add_argument("--expected", type=int)
    parser.add_argument("--progress", type=int, default=100000)
    parser.add_argument("--witness-out")
    args = parser.parse_args()

    if args.order % 2 == 0:
        raise ValueError("a one-degree-2/all-degree-3 graph has odd order")
    stats = Stats(order=args.order, expected=args.expected, rejected_by_length={})
    digest = hashlib.sha256()
    start = time.monotonic()
    witness = None

    for raw in sys.stdin.buffer:
        if not raw.strip() or raw.startswith(b">>"):
            continue
        digest.update(raw)
        order, adj = parse_graph6(raw)
        if order != args.order:
            raise ValueError(f"expected order {args.order}, received {order}")
        terminal = validate_terminal_cap(adj)
        stats.graphs += 1
        forbidden = first_forbidden_cycle(adj)
        if forbidden is None:
            witness = {
                "kind": "terminal_cap",
                "cap_order": order,
                "cap_graph6": raw.strip().decode("ascii"),
                "terminal": terminal,
                "doubled_counterexample_order": 2 * order,
            }
            break
        length, _cycle = forbidden
        key = str(length)
        stats.rejected_by_length[key] = stats.rejected_by_length.get(key, 0) + 1
        if args.progress and stats.graphs % args.progress == 0:
            print(
                json.dumps(
                    {"order": order, "progress": stats.graphs,
                     "seconds": time.monotonic() - start}
                ),
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
        with open(args.witness_out, "w", encoding="utf-8") as handle:
            json.dump(witness, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(json.dumps(result, sort_keys=True))
    return 10 if witness is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
