#!/usr/bin/env python3
"""Independent graph-level verifier for irregular structural SAT witnesses."""
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
    if witness.get("kind") != "minimal_structural_sat":
        raise ValueError("unsupported witness kind")
    graph = decode_graph6(witness["graph6"])
    order = int(witness["order"])
    a_size = int(witness["a_size"])
    b_size = int(witness["b_size"])
    if len(graph) != order or a_size + b_size != order:
        raise AssertionError("partition/order mismatch")
    if a_size < 2 * b_size:
        raise AssertionError("the verified 2/3 cubic bound is violated")
    if not connected(graph):
        raise AssertionError("graph is disconnected")
    degrees = [len(neighbours) for neighbours in graph]
    if degrees != witness["degrees"]:
        raise AssertionError("reported degree sequence mismatch")
    if any(degrees[vertex] != 3 for vertex in range(a_size)):
        raise AssertionError("an A vertex is not cubic")
    if any(degrees[vertex] < 4 for vertex in range(a_size, order)):
        raise AssertionError("a B vertex has degree below four")
    if any(
        neighbour >= a_size
        for vertex in range(a_size, order)
        for neighbour in graph[vertex]
    ):
        raise AssertionError("B is not independent")
    if any(
        not any(neighbour < a_size for neighbour in graph[vertex])
        for vertex in range(a_size)
    ):
        raise AssertionError("a cubic vertex has no cubic neighbour")

    checked = []
    power = 4
    while power <= order:
        checked.append(power)
        cycle = first_cycle_of_length(graph, power)
        if cycle is not None:
            raise AssertionError(f"forbidden C_{power} found: {cycle}")
        power *= 2
    return {
        "verified": True,
        "order": order,
        "a_size": a_size,
        "b_size": b_size,
        "minimum_degree": min(degrees),
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
