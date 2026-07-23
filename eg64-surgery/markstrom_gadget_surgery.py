#!/usr/bin/env python3
"""Exhaust small one-terminal surgeries on the public order-24 extremal graphs.

The input directory is the `special/` directory from the public
rbsandeep/Erdos-Gyarfas `special-graphs` branch. Every 24-vertex cubic matrix
with no C4 or C8 is loaded and deduplicated.

Two complete local replacement classes are searched.

1. Edge replacement. Remove an edge uv and insert a connected subcubic gadget
   F. Two external stubs reconnect F to u and v. One designated vertex of F
   has final degree 2; every other gadget vertex has final degree 3.

2. Vertex replacement. Remove a cubic vertex v and insert F. Three external
   stubs reconnect F to the three former neighbors of v. Again, one designated
   gadget vertex has final degree 2 and all other vertices have final degree 3.

For a fixed gadget order, the edge count is forced. `geng` enumerates every
connected simple internal gadget up to isomorphism; all possible terminal
choices and all assignments of external stubs are tested. Thus the search is
exhaustive within the declared gadget-size bounds, not heuristic.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence


def iter_bits(mask: int) -> Iterator[int]:
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def parse_matrix(path: Path) -> tuple[int, ...]:
    rows = [
        [int(value) for value in line.split()]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    order = len(rows)
    if order == 0 or any(len(row) != order for row in rows):
        raise ValueError(f"{path}: not a square matrix")
    adjacency = [0] * order
    for first in range(order):
        if rows[first][first] != 0:
            raise ValueError(f"{path}: loop at {first}")
        for second in range(order):
            if rows[first][second] not in (0, 1):
                raise ValueError(f"{path}: nonbinary entry")
            if rows[first][second] != rows[second][first]:
                raise ValueError(f"{path}: asymmetric matrix")
            if rows[first][second]:
                adjacency[first] |= 1 << second
    return tuple(adjacency)


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
        raise ValueError("truncated graph6 record")
    adjacency = [0] * order
    index = 0
    for high in range(1, order):
        for low in range(high):
            if bits[index]:
                adjacency[low] |= 1 << high
                adjacency[high] |= 1 << low
            index += 1
    return tuple(adjacency)


def graph6(adjacency: tuple[int, ...]) -> str:
    order = len(adjacency)
    if order > 62:
        raise ValueError("compact graph6 writer supports order at most 62")
    bits: list[int] = []
    for high in range(1, order):
        for low in range(high):
            bits.append((adjacency[low] >> high) & 1)
    while len(bits) % 6:
        bits.append(0)
    output = [chr(order + 63)]
    for start in range(0, len(bits), 6):
        value = sum(bits[start + offset] << (5 - offset) for offset in range(6))
        output.append(chr(value + 63))
    return "".join(output)


def edges(adjacency: tuple[int, ...]) -> list[tuple[int, int]]:
    return [
        (first, second)
        for first, neighbors in enumerate(adjacency)
        for second in range(first + 1, len(adjacency))
        if (neighbors >> second) & 1
    ]


def connected(adjacency: tuple[int, ...]) -> bool:
    if not adjacency:
        return False
    seen = 1
    frontier = 1
    while frontier:
        bit = frontier & -frontier
        frontier ^= bit
        vertex = bit.bit_length() - 1
        unseen = adjacency[vertex] & ~seen
        seen |= unseen
        frontier |= unseen
    return seen.bit_count() == len(adjacency)


def first_cycle(adjacency: tuple[int, ...], length: int) -> tuple[int, ...] | None:
    """Return one simple undirected cycle, canonically enumerated, or None."""
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


def canonical_fingerprint(adjacency: tuple[int, ...]) -> str:
    """Stable labeled fingerprint used only to remove byte-identical matrices."""
    payload = ",".join(f"{value:x}" for value in adjacency).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def unique_multiset_permutations(values: Sequence[int]) -> Iterator[tuple[int, ...]]:
    counter = Counter(values)
    length = len(values)
    path: list[int] = []

    def recurse() -> Iterator[tuple[int, ...]]:
        if len(path) == length:
            yield tuple(path)
            return
        for value in sorted(counter):
            if counter[value] == 0:
                continue
            counter[value] -= 1
            path.append(value)
            yield from recurse()
            path.pop()
            counter[value] += 1

    yield from recurse()


def gadget_records(geng: str, order: int, edge_count: int) -> Iterator[tuple[int, ...]]:
    if order == 1:
        if edge_count == 0:
            yield (0,)
        return
    command = [geng, "-q", "-c", "-D3", str(order), f"{edge_count}:{edge_count}"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None
    for raw in process.stdout:
        if raw.strip() and not raw.startswith(b">>"):
            yield parse_graph6(raw)
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"geng failed ({return_code}): {stderr}")


def target_deficits(gadget: tuple[int, ...], terminal: int) -> tuple[int, ...] | None:
    deficits = []
    for vertex, neighbors in enumerate(gadget):
        target = 2 if vertex == terminal else 3
        deficit = target - neighbors.bit_count()
        if deficit < 0:
            return None
        deficits.append(deficit)
    return tuple(deficits)


def add_edge(mutable: list[int], first: int, second: int) -> None:
    if first == second or ((mutable[first] >> second) & 1):
        raise ValueError(f"invalid edge insertion {(first, second)}")
    mutable[first] |= 1 << second
    mutable[second] |= 1 << first


def remove_edge(mutable: list[int], first: int, second: int) -> None:
    if not ((mutable[first] >> second) & 1):
        raise ValueError(f"missing edge {(first, second)}")
    mutable[first] &= ~(1 << second)
    mutable[second] &= ~(1 << first)


def edge_replacement(
    base: tuple[int, ...],
    base_edge: tuple[int, int],
    gadget: tuple[int, ...],
    assignment: tuple[int, int],
) -> tuple[int, ...]:
    base_order = len(base)
    output = list(base) + [0] * len(gadget)
    first, second = base_edge
    remove_edge(output, first, second)
    for gadget_vertex, neighbors in enumerate(gadget):
        for neighbor in iter_bits(neighbors):
            if gadget_vertex < neighbor:
                add_edge(output, base_order + gadget_vertex, base_order + neighbor)
    add_edge(output, first, base_order + assignment[0])
    add_edge(output, second, base_order + assignment[1])
    return tuple(output)


def vertex_replacement(
    base: tuple[int, ...],
    removed: int,
    gadget: tuple[int, ...],
    assignment: tuple[int, int, int],
) -> tuple[int, ...]:
    retained = [vertex for vertex in range(len(base)) if vertex != removed]
    mapping = {old: new for new, old in enumerate(retained)}
    former_neighbors = sorted(iter_bits(base[removed]))
    output = [0] * (len(base) - 1 + len(gadget))
    for old_first in retained:
        for old_second in iter_bits(base[old_first]):
            if old_second == removed or old_first >= old_second:
                continue
            add_edge(output, mapping[old_first], mapping[old_second])
    offset = len(base) - 1
    for gadget_vertex, neighbors in enumerate(gadget):
        for neighbor in iter_bits(neighbors):
            if gadget_vertex < neighbor:
                add_edge(output, offset + gadget_vertex, offset + neighbor)
    for old_neighbor, gadget_vertex in zip(former_neighbors, assignment):
        add_edge(output, mapping[old_neighbor], offset + gadget_vertex)
    return tuple(output)


def validate_cap(adjacency: tuple[int, ...]) -> int:
    degrees = [neighbors.bit_count() for neighbors in adjacency]
    terminals = [vertex for vertex, degree in enumerate(degrees) if degree == 2]
    if len(terminals) != 1 or any(degree not in (2, 3) for degree in degrees):
        raise AssertionError(f"bad cap degree sequence: {sorted(degrees)}")
    if not connected(adjacency):
        raise AssertionError("constructed cap disconnected")
    return terminals[0]


@dataclass
class SearchStats:
    base_files_seen: int = 0
    base_graphs_selected: int = 0
    base_graphs_unique: int = 0
    gadget_graphs: int = 0
    terminal_roles: int = 0
    surgeries: int = 0
    rejected_c4: int = 0
    rejected_c8: int = 0
    rejected_c16: int = 0
    rejected_c32: int = 0
    elapsed_seconds: float = 0.0


def load_bases(directory: Path, stats: SearchStats) -> list[tuple[str, tuple[int, ...]]]:
    selected: list[tuple[str, tuple[int, ...]]] = []
    seen: set[str] = set()
    for path in sorted(directory.rglob("*.txt")):
        stats.base_files_seen += 1
        try:
            adjacency = parse_matrix(path)
        except Exception:
            continue
        if len(adjacency) != 24:
            continue
        if any(neighbors.bit_count() != 3 for neighbors in adjacency):
            continue
        if not connected(adjacency):
            continue
        if first_cycle(adjacency, 4) is not None or first_cycle(adjacency, 8) is not None:
            continue
        stats.base_graphs_selected += 1
        fingerprint = canonical_fingerprint(adjacency)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        selected.append((path.name, adjacency))
    stats.base_graphs_unique = len(selected)
    if not selected:
        raise RuntimeError("no order-24 cubic C4/C8-free matrices found")
    return selected


def record_rejection(stats: SearchStats, forbidden: tuple[int, tuple[int, ...]]) -> None:
    length = forbidden[0]
    if length == 4:
        stats.rejected_c4 += 1
    elif length == 8:
        stats.rejected_c8 += 1
    elif length == 16:
        stats.rejected_c16 += 1
    elif length == 32:
        stats.rejected_c32 += 1
    else:
        raise AssertionError(f"unexpected forbidden length {length}")


def witness_payload(
    operation: str,
    base_name: str,
    cap: tuple[int, ...],
    terminal: int,
    gadget: tuple[int, ...],
    gadget_terminal: int,
    location: object,
    assignment: Sequence[int],
    stats: SearchStats,
) -> dict:
    return {
        "kind": "one_terminal_local_surgery",
        "operation": operation,
        "base_file": base_name,
        "cap_order": len(cap),
        "terminal": terminal,
        "cap_graph6": graph6(cap),
        "cap_edges": [list(edge) for edge in edges(cap)],
        "doubled_counterexample_order": 2 * len(cap),
        "gadget_order": len(gadget),
        "gadget_graph6": graph6(gadget),
        "gadget_terminal": gadget_terminal,
        "location": location,
        "external_assignment": list(assignment),
        "stats": asdict(stats),
    }


def run_search(
    bases: list[tuple[str, tuple[int, ...]]],
    geng: str,
    max_edge_gadget: int,
    max_vertex_gadget: int,
    stats: SearchStats,
    checkpoint: Path | None,
) -> dict | None:
    start_time = time.monotonic()

    def checkpoint_now(extra: dict | None = None) -> None:
        stats.elapsed_seconds = time.monotonic() - start_time
        if checkpoint is not None:
            payload = {"stats": asdict(stats)}
            if extra:
                payload.update(extra)
            checkpoint.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    # Edge replacement: odd gadget size, total internal deficits exactly two.
    for size in range(1, max_edge_gadget + 1, 2):
        edge_count = (3 * size - 3) // 2
        for gadget in gadget_records(geng, size, edge_count):
            stats.gadget_graphs += 1
            for gadget_terminal in range(size):
                deficits = target_deficits(gadget, gadget_terminal)
                if deficits is None or sum(deficits) != 2:
                    continue
                ports = [vertex for vertex, count in enumerate(deficits) for _ in range(count)]
                assignments = list(unique_multiset_permutations(ports))
                stats.terminal_roles += 1
                for base_name, base in bases:
                    for base_edge in edges(base):
                        for assignment in assignments:
                            stats.surgeries += 1
                            cap = edge_replacement(base, base_edge, gadget, assignment)
                            terminal = validate_cap(cap)
                            forbidden = first_power_cycle(cap)
                            if forbidden is None:
                                checkpoint_now()
                                return witness_payload(
                                    "edge_replacement", base_name, cap, terminal,
                                    gadget, gadget_terminal, list(base_edge), assignment, stats,
                                )
                            record_rejection(stats, forbidden)
            if stats.gadget_graphs % 1000 == 0:
                checkpoint_now({"phase": "edge", "gadget_size": size})

    # Vertex replacement: even gadget size, total internal deficits exactly three.
    for size in range(2, max_vertex_gadget + 1, 2):
        edge_count = (3 * size - 4) // 2
        for gadget in gadget_records(geng, size, edge_count):
            stats.gadget_graphs += 1
            for gadget_terminal in range(size):
                deficits = target_deficits(gadget, gadget_terminal)
                if deficits is None or sum(deficits) != 3:
                    continue
                ports = [vertex for vertex, count in enumerate(deficits) for _ in range(count)]
                assignments = list(unique_multiset_permutations(ports))
                stats.terminal_roles += 1
                for base_name, base in bases:
                    for removed in range(len(base)):
                        for assignment in assignments:
                            stats.surgeries += 1
                            cap = vertex_replacement(base, removed, gadget, assignment)
                            terminal = validate_cap(cap)
                            forbidden = first_power_cycle(cap)
                            if forbidden is None:
                                checkpoint_now()
                                return witness_payload(
                                    "vertex_replacement", base_name, cap, terminal,
                                    gadget, gadget_terminal, removed, assignment, stats,
                                )
                            record_rejection(stats, forbidden)
            if stats.gadget_graphs % 1000 == 0:
                checkpoint_now({"phase": "vertex", "gadget_size": size})

    checkpoint_now({"status": "exhausted"})
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--special-dir", required=True)
    parser.add_argument("--geng", required=True)
    parser.add_argument("--max-edge-gadget", type=int, default=9)
    parser.add_argument("--max-vertex-gadget", type=int, default=10)
    parser.add_argument("--checkpoint")
    parser.add_argument("--witness-out")
    args = parser.parse_args()

    stats = SearchStats()
    bases = load_bases(Path(args.special_dir), stats)
    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    witness = run_search(
        bases=bases,
        geng=args.geng,
        max_edge_gadget=args.max_edge_gadget,
        max_vertex_gadget=args.max_vertex_gadget,
        stats=stats,
        checkpoint=checkpoint,
    )
    payload = {
        "status": "witness" if witness is not None else "exhausted",
        "base_graphs": [name for name, _ in bases],
        "bounds": {
            "max_edge_gadget": args.max_edge_gadget,
            "max_vertex_gadget": args.max_vertex_gadget,
        },
        "stats": asdict(stats),
        "witness": witness,
    }
    if checkpoint is not None:
        checkpoint.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if witness is not None and args.witness_out:
        Path(args.witness_out).write_text(json.dumps(witness, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 10 if witness is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
