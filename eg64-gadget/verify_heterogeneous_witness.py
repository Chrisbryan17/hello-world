#!/usr/bin/env python3
"""Independent graph-level verifier for heterogeneous gadget assemblies."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def decode_graph6(text: str) -> list[set[int]]:
    data = text.strip()
    if data.startswith(">>graph6<<"):
        data = data[len(">>graph6<<"):]
    values = [ord(character) - 63 for character in data]
    if not values or any(value < 0 or value > 63 for value in values):
        raise ValueError("invalid graph6")
    if values[0] <= 62:
        order, position = values[0], 1
    elif len(values) >= 4 and values[0] == 63 and values[1] != 63:
        order = (values[1] << 12) | (values[2] << 6) | values[3]
        position = 4
    else:
        raise ValueError("unsupported graph6 order")
    bits = []
    for value in values[position:]:
        bits.extend((value >> shift) & 1 for shift in range(5, -1, -1))
    if len(bits) < order * (order - 1) // 2:
        raise ValueError("truncated graph6")
    graph = [set() for _ in range(order)]
    index = 0
    for high in range(1, order):
        for low in range(high):
            if bits[index]:
                graph[low].add(high)
                graph[high].add(low)
            index += 1
    return graph


def delete_vertex(
    graph: list[set[int]], deleted: int
) -> tuple[list[set[int]], tuple[int, int, int]]:
    retained = [vertex for vertex in range(len(graph)) if vertex != deleted]
    relabel = {old: new for new, old in enumerate(retained)}
    gadget = [set() for _ in retained]
    for old in retained:
        for neighbour in graph[old]:
            if neighbour != deleted:
                gadget[relabel[old]].add(relabel[neighbour])
    terminals = tuple(relabel[neighbour] for neighbour in sorted(graph[deleted]))
    if len(terminals) != 3:
        raise AssertionError("source deletion did not expose three terminals")
    return gadget, terminals


def connected(graph: list[set[int]]) -> bool:
    if not graph:
        return False
    seen = {0}
    stack = [0]
    while stack:
        vertex = stack.pop()
        for neighbour in graph[vertex]:
            if neighbour not in seen:
                seen.add(neighbour)
                stack.append(neighbour)
    return len(seen) == len(graph)


def first_cycle_of_length(graph: list[set[int]], length: int) -> list[int] | None:
    path = [-1] * length
    for start in range(len(graph)):
        path[0] = start
        for first in sorted(neighbour for neighbour in graph[start] if neighbour > start):
            path[1] = first
            used = {start, first}

            def search(depth: int, current: int) -> list[int] | None:
                if depth == length:
                    if start in graph[current] and path[1] < path[-1]:
                        return path.copy()
                    return None
                for neighbour in sorted(graph[current]):
                    if neighbour <= start or neighbour in used:
                        continue
                    if depth == length - 1 and start not in graph[neighbour]:
                        continue
                    path[depth] = neighbour
                    used.add(neighbour)
                    answer = search(depth + 1, neighbour)
                    if answer is not None:
                        return answer
                    used.remove(neighbour)
                return None

            answer = search(2, first)
            if answer is not None:
                return answer
    return None


def verify(witness: dict) -> dict:
    if witness.get("kind") != "heterogeneous_spectrum_wiring":
        raise ValueError("unsupported witness kind")
    base = decode_graph6(witness["base_graph6"])
    choices = witness["choices"]
    if len(choices) != len(base):
        raise AssertionError("choice count does not match base order")

    gadgets = []
    terminals_by_copy = []
    permutations = []
    for choice in choices:
        record = choice["gadget"]
        source = decode_graph6(record["source_graph6"])
        gadget, terminals = delete_vertex(source, int(record["deleted_vertex"]))
        if len(gadget) != int(record["gadget_order"]):
            raise AssertionError("gadget order mismatch")
        if list(terminals) != record["terminals"]:
            raise AssertionError("terminal list mismatch")
        permutation = choice["permutation"]
        if sorted(permutation) != [0, 1, 2]:
            raise AssertionError("terminal assignment is not a permutation")
        gadgets.append(gadget)
        terminals_by_copy.append(terminals)
        permutations.append(permutation)

    offsets = []
    total = 0
    for gadget in gadgets:
        offsets.append(total)
        total += len(gadget)
    if total != int(witness["assembled_order"]):
        raise AssertionError("assembled order mismatch")

    graph = [set() for _ in range(total)]
    for copy, gadget in enumerate(gadgets):
        offset = offsets[copy]
        for vertex, neighbours in enumerate(gadget):
            graph[offset + vertex].update(offset + neighbour for neighbour in neighbours)

    base_neighbours = [sorted(neighbours) for neighbours in base]
    base_slots = [
        {neighbour: slot for slot, neighbour in enumerate(neighbours)}
        for neighbours in base_neighbours
    ]
    for first in range(len(base)):
        for second in base_neighbours[first]:
            if first >= second:
                continue
            first_terminal = terminals_by_copy[first][
                permutations[first][base_slots[first][second]]
            ]
            second_terminal = terminals_by_copy[second][
                permutations[second][base_slots[second][first]]
            ]
            first_vertex = offsets[first] + first_terminal
            second_vertex = offsets[second] + second_terminal
            if second_vertex in graph[first_vertex]:
                raise AssertionError("assembly attempted to create a duplicate edge")
            graph[first_vertex].add(second_vertex)
            graph[second_vertex].add(first_vertex)

    if not connected(graph):
        raise AssertionError("assembled graph is disconnected")
    degrees = [len(neighbours) for neighbours in graph]
    if any(degree != 3 for degree in degrees):
        raise AssertionError(f"assembled graph is not cubic: {sorted(degrees)}")

    checked = []
    power = 4
    while power <= len(graph):
        checked.append(power)
        cycle = first_cycle_of_length(graph, power)
        if cycle is not None:
            raise AssertionError(f"forbidden C_{power} found: {cycle}")
        power *= 2
    return {
        "verified": True,
        "order": len(graph),
        "degree": 3,
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
