#!/usr/bin/env python3
"""Exhaust cubic replacement products built from internally clean three-poles.

A gadget base Q is a connected cubic graph. Deleting a vertex v gives a
three-pole H with three degree-2 terminals. We retain exactly those (Q,v) for
which H has no cycle of power-of-two length. For every connected cubic host R,
every bijection from the three incident host edges to the three terminals is
chosen independently at every host vertex. Joining the selected terminals
produces a finite simple cubic graph, which is checked exactly for every
power-of-two cycle length.
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
from typing import Iterable, Iterator

PORT_PERMUTATIONS = tuple(itertools.permutations(range(3)))


def parse_graph6(raw: bytes) -> tuple[int, tuple[int, ...], str]:
    data = raw.strip()
    if data.startswith(b">>graph6<<"):
        data = data[len(b">>graph6<<"):]
    values = [byte - 63 for byte in data]
    if not values or any(value < 0 or value > 63 for value in values):
        raise ValueError("invalid graph6")
    if values[0] <= 62:
        order, position = values[0], 1
    elif len(values) >= 4 and values[0] == 63 and values[1] != 63:
        order = (values[1] << 12) | (values[2] << 6) | values[3]
        position = 4
    else:
        raise ValueError("unsupported graph6 order encoding")
    bits: list[int] = []
    for value in values[position:]:
        bits.extend((value >> shift) & 1 for shift in range(5, -1, -1))
    needed = order * (order - 1) // 2
    if len(bits) < needed:
        raise ValueError("truncated graph6")
    adjacency = [0] * order
    index = 0
    for high in range(1, order):
        for low in range(high):
            if bits[index]:
                adjacency[low] |= 1 << high
                adjacency[high] |= 1 << low
            index += 1
    return order, tuple(adjacency), data.decode("ascii")


def graph6_records(paths: Iterable[str]) -> Iterator[tuple[int, tuple[int, ...], str]]:
    for name in paths:
        for raw in Path(name).read_bytes().splitlines():
            if raw.strip() and raw.strip() != b">>graph6<<":
                yield parse_graph6(raw)


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
        raise ValueError("graph is not cubic")
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
        raise ValueError("graph is disconnected")


def canonical_cycles(adjacency: tuple[int, ...], length: int) -> Iterator[tuple[int, ...]]:
    order = len(adjacency)
    if length < 3 or length > order:
        return
    path = [0] * length
    for start in range(order):
        path[0] = start
        first_mask = adjacency[start] & ~((1 << (start + 1)) - 1)
        for first in iter_bits(first_mask):
            path[1] = first

            def dfs(depth: int, current: int, used: int) -> Iterator[tuple[int, ...]]:
                if depth == length:
                    if ((adjacency[current] >> start) & 1) and path[1] < path[-1]:
                        yield tuple(path)
                    return
                candidates = adjacency[current] & ~used & ~((1 << (start + 1)) - 1)
                if depth == length - 1:
                    candidates &= adjacency[start]
                for nxt in iter_bits(candidates):
                    path[depth] = nxt
                    yield from dfs(depth + 1, nxt, used | (1 << nxt))

            yield from dfs(2, first, (1 << start) | (1 << first))


def power_cycle_vertex_intersection(adjacency: tuple[int, ...]) -> tuple[bool, int]:
    intersection = (1 << len(adjacency)) - 1
    saw = False
    power = 4
    while power <= len(adjacency):
        for cycle in canonical_cycles(adjacency, power):
            saw = True
            mask = 0
            for vertex in cycle:
                mask |= 1 << vertex
            intersection &= mask
            if intersection == 0:
                return saw, 0
        power *= 2
    return saw, intersection


def delete_vertex(
    adjacency: tuple[int, ...], deleted: int
) -> tuple[tuple[int, ...], tuple[int, int, int]]:
    retained = [vertex for vertex in range(len(adjacency)) if vertex != deleted]
    index = {old: new for new, old in enumerate(retained)}
    gadget = [0] * len(retained)
    for old in retained:
        for neighbor in iter_bits(adjacency[old]):
            if neighbor != deleted:
                gadget[index[old]] |= 1 << index[neighbor]
    terminals = tuple(index[neighbor] for neighbor in iter_bits(adjacency[deleted]))
    if len(terminals) != 3:
        raise AssertionError("deleted cubic vertex did not expose three terminals")
    if any(gadget[v].bit_count() != (2 if v in terminals else 3) for v in range(len(gadget))):
        raise AssertionError("invalid three-pole degrees")
    return tuple(gadget), terminals


def first_four_cycle(adjacency: tuple[int, ...]) -> tuple[int, int, int, int] | None:
    for first in range(len(adjacency)):
        for third in range(first + 1, len(adjacency)):
            common = adjacency[first] & adjacency[third]
            if common.bit_count() >= 2:
                bit = common & -common
                second = bit.bit_length() - 1
                common ^= bit
                fourth = (common & -common).bit_length() - 1
                return first, second, third, fourth
    return None


def first_cycle(adjacency: tuple[int, ...], length: int) -> tuple[int, ...] | None:
    if length == 4:
        return first_four_cycle(adjacency)
    return next(canonical_cycles(adjacency, length), None)


def first_forbidden_cycle(adjacency: tuple[int, ...]) -> tuple[int, tuple[int, ...]] | None:
    power = 4
    while power <= len(adjacency):
        cycle = first_cycle(adjacency, power)
        if cycle is not None:
            return power, cycle
        power *= 2
    return None


def construct_product(
    gadget: tuple[int, ...], terminals: tuple[int, int, int],
    host: tuple[int, ...], assignments: tuple[tuple[int, int, int], ...],
) -> tuple[int, ...] | None:
    gadget_order = len(gadget)
    total = gadget_order * len(host)
    product = [0] * total
    for copy in range(len(host)):
        offset = copy * gadget_order
        for u, neighbors in enumerate(gadget):
            for v in iter_bits(neighbors):
                product[offset + u] |= 1 << (offset + v)
    host_neighbors = tuple(tuple(iter_bits(neighbors)) for neighbors in host)
    positions = tuple({neighbor: index for index, neighbor in enumerate(row)} for row in host_neighbors)
    for left, right in edge_list(host):
        left_port = assignments[left][positions[left][right]]
        right_port = assignments[right][positions[right][left]]
        u = left * gadget_order + terminals[left_port]
        v = right * gadget_order + terminals[right_port]
        if u == v or ((product[u] >> v) & 1):
            return None
        product[u] |= 1 << v
        product[v] |= 1 << u
    if any(neighbors.bit_count() != 3 for neighbors in product):
        raise AssertionError("replacement product is not cubic")
    return tuple(product)


def adjacency_digest(adjacency: tuple[int, ...]) -> str:
    digest = hashlib.sha256()
    for u, v in edge_list(adjacency):
        digest.update(f"{u},{v}\n".encode())
    return digest.hexdigest()


@dataclass
class Stats:
    gadget_bases: int = 0
    internally_clean_three_poles: int = 0
    host_graphs: int = 0
    products_tested: int = 0
    invalid_products: int = 0
    rejected_c4: int = 0
    rejected_c8: int = 0
    rejected_c16: int = 0
    rejected_c32: int = 0
    rejected_c64: int = 0
    seconds: float = 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gadget-file", action="append", required=True)
    parser.add_argument("--host-file", action="append", required=True)
    parser.add_argument("--witness-out")
    parser.add_argument("--progress", type=int, default=100000)
    args = parser.parse_args()

    started = time.monotonic()
    stats = Stats()
    hosts = list(graph6_records(args.host_file))
    for _order, adjacency, _code in hosts:
        validate_connected_cubic(adjacency)
    stats.host_graphs = len(hosts)
    witness = None
    clean_gadgets: list[tuple[str, int, tuple[int, ...], tuple[int, int, int]]] = []

    for _order, base, code in graph6_records(args.gadget_file):
        validate_connected_cubic(base)
        stats.gadget_bases += 1
        saw, intersection = power_cycle_vertex_intersection(base)
        if not saw:
            witness = {
                "kind": "base_graph_counterexample",
                "graph6": code,
                "order": len(base),
            }
            break
        for deleted in iter_bits(intersection):
            gadget, terminals = delete_vertex(base, deleted)
            if first_forbidden_cycle(gadget) is not None:
                raise AssertionError("intersection candidate was not internally clean")
            clean_gadgets.append((code, deleted, gadget, terminals))
            stats.internally_clean_three_poles += 1

    if witness is None:
        for base_code, deleted, gadget, terminals in clean_gadgets:
            for _host_order, host, host_code in hosts:
                for assignment in itertools.product(PORT_PERMUTATIONS, repeat=len(host)):
                    product = construct_product(gadget, terminals, host, assignment)
                    if product is None:
                        stats.invalid_products += 1
                        continue
                    stats.products_tested += 1
                    forbidden = first_forbidden_cycle(product)
                    if forbidden is None:
                        witness = {
                            "kind": "replacement_product",
                            "gadget_base_graph6": base_code,
                            "deleted_vertex": deleted,
                            "gadget_terminals": list(terminals),
                            "host_graph6": host_code,
                            "port_assignments": [list(item) for item in assignment],
                            "order": len(product),
                            "adjacency_sha256": adjacency_digest(product),
                        }
                        break
                    length, _cycle = forbidden
                    field = f"rejected_c{length}"
                    if hasattr(stats, field):
                        setattr(stats, field, getattr(stats, field) + 1)
                    if args.progress and stats.products_tested % args.progress == 0:
                        print(json.dumps({
                            "products_tested": stats.products_tested,
                            "seconds": time.monotonic() - started,
                        }), file=sys.stderr, flush=True)
                if witness is not None:
                    break
            if witness is not None:
                break

    stats.seconds = time.monotonic() - started
    result = {"stats": asdict(stats), "witness": witness}
    if witness is not None and args.witness_out:
        Path(args.witness_out).write_text(
            json.dumps(witness, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(result, sort_keys=True))
    return 10 if witness is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
