#!/usr/bin/env python3
"""Independent verifier for a cyclic Petersen voltage-lift witness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PETERSEN_EDGES = [
    (0, 1), (0, 4), (0, 5), (1, 2), (1, 6),
    (2, 3), (2, 7), (3, 4), (3, 8), (4, 9),
    (5, 7), (5, 8), (6, 8), (6, 9), (7, 9),
]
CHORDS = [(2, 3), (2, 7), (3, 8), (6, 8), (6, 9), (7, 9)]


def construct_lift(modulus: int, voltages: list[int]) -> list[set[int]]:
    if len(voltages) != 6:
        raise ValueError("six chord voltages are required")
    if any(value < 0 or value >= modulus for value in voltages):
        raise ValueError("a voltage lies outside the cyclic group")
    chord_voltage = dict(zip(CHORDS, voltages))
    order = 10 * modulus
    graph = [set() for _ in range(order)]
    for first_base, second_base in PETERSEN_EDGES:
        voltage = chord_voltage.get((first_base, second_base), 0)
        for fibre in range(modulus):
            first = first_base * modulus + fibre
            second = second_base * modulus + ((fibre + voltage) % modulus)
            if second in graph[first]:
                raise AssertionError("duplicate edge in derived lift")
            graph[first].add(second)
            graph[second].add(first)
    return graph


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
    modulus = int(witness["modulus"])
    voltages = [int(value) for value in witness["voltages"]]
    graph = construct_lift(modulus, voltages)
    degrees = [len(neighbours) for neighbours in graph]
    if any(degree != 3 for degree in degrees):
        raise AssertionError(f"derived graph is not cubic: {sorted(degrees)}")
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
        "modulus": modulus,
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
