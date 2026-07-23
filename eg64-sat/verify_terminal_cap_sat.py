#!/usr/bin/env python3
"""Independent graph-level verifier for a SAT-generated terminal-cap witness."""
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
    required = order * (order - 1) // 2
    if len(bits) < required:
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


def articulation_vertices(graph: list[set[int]]) -> list[int]:
    articulation = []
    for removed in range(len(graph)):
        start = next((vertex for vertex in range(len(graph)) if vertex != removed), None)
        if start is None:
            continue
        seen = {start}
        stack = [start]
        while stack:
            vertex = stack.pop()
            for neighbour in graph[vertex]:
                if neighbour == removed or neighbour in seen:
                    continue
                seen.add(neighbour)
                stack.append(neighbour)
        if len(seen) != len(graph) - 1:
            articulation.append(removed)
    return articulation


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
    if witness.get("kind") != "terminal_cap_sat":
        raise ValueError("unsupported witness kind")
    cap = decode_graph6(witness["cap_graph6"])
    if len(cap) != int(witness["cap_order"]):
        raise AssertionError("cap order mismatch")
    degrees = [len(neighbours) for neighbours in cap]
    terminals = [vertex for vertex, degree in enumerate(degrees) if degree == 2]
    if terminals != [0]:
        raise AssertionError(f"terminal degree pattern is wrong: {degrees}")
    if any(degree != 3 for vertex, degree in enumerate(degrees) if vertex != 0):
        raise AssertionError(f"nonterminal degree pattern is wrong: {degrees}")
    if not connected(cap):
        raise AssertionError("cap is disconnected")
    articulation = articulation_vertices(cap)
    if articulation:
        raise AssertionError(f"cap is not biconnected: {articulation}")

    checked_cap = []
    power = 4
    while power <= len(cap):
        checked_cap.append(power)
        cycle = first_cycle_of_length(cap, power)
        if cycle is not None:
            raise AssertionError(f"cap contains forbidden C_{power}: {cycle}")
        power *= 2

    order = len(cap)
    doubled = [set() for _ in range(2 * order)]
    for vertex, neighbours in enumerate(cap):
        doubled[vertex].update(neighbours)
        doubled[order + vertex].update(order + neighbour for neighbour in neighbours)
    doubled[0].add(order)
    doubled[order].add(0)
    if len(doubled) != int(witness["counterexample_order"]):
        raise AssertionError("counterexample order mismatch")
    if not connected(doubled):
        raise AssertionError("doubled graph is disconnected")
    doubled_degrees = [len(neighbours) for neighbours in doubled]
    if any(degree != 3 for degree in doubled_degrees):
        raise AssertionError(f"doubled graph is not cubic: {doubled_degrees}")

    checked_counterexample = []
    power = 4
    while power <= len(doubled):
        checked_counterexample.append(power)
        cycle = first_cycle_of_length(doubled, power)
        if cycle is not None:
            raise AssertionError(f"doubled graph contains forbidden C_{power}: {cycle}")
        power *= 2
    return {
        "verified": True,
        "cap_order": len(cap),
        "counterexample_order": len(doubled),
        "counterexample_degree": 3,
        "cap_power_lengths_checked": checked_cap,
        "counterexample_power_lengths_checked": checked_counterexample,
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
