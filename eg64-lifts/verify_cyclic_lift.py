#!/usr/bin/env python3
"""Independent verifier for an odd cyclic-voltage-lift witness.

The verifier does not import the search implementation. It reconstructs the
cover directly from the full oriented edge-voltage table, checks simplicity,
cubicity, and the adjacency digest, then exhaustively searches every relevant
power-of-two cycle length in every connected component.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def decode_graph6(text: str) -> list[set[int]]:
    data = text.strip()
    values = [ord(char) - 63 for char in data]
    if not values or values[0] > 62:
        raise ValueError("unsupported graph6 base")
    n = values[0]
    bits: list[int] = []
    for value in values[1:]:
        bits.extend((value >> shift) & 1 for shift in range(5, -1, -1))
    graph = [set() for _ in range(n)]
    index = 0
    for high in range(1, n):
        for low in range(high):
            if bits[index]:
                graph[low].add(high)
                graph[high].add(low)
            index += 1
    return graph


def build_lift(witness: dict) -> list[set[int]]:
    base = decode_graph6(witness["base_graph6"])
    q = int(witness["q"])
    if q <= 1 or q % 2 == 0:
        raise AssertionError("lift modulus is not odd and greater than one")
    supplied: dict[tuple[int, int], int] = {}
    for u_raw, v_raw, shift_raw in witness["edge_voltages"]:
        u, v, shift = int(u_raw), int(v_raw), int(shift_raw) % q
        if not (0 <= u < v < len(base)):
            raise AssertionError("edge voltage has invalid orientation")
        if v not in base[u]:
            raise AssertionError("voltage supplied for a non-edge")
        if (u, v) in supplied:
            raise AssertionError("duplicate edge voltage")
        supplied[(u, v)] = shift
    expected = {
        (u, v)
        for u in range(len(base))
        for v in base[u]
        if u < v
    }
    if set(supplied) != expected:
        raise AssertionError("edge-voltage table is incomplete")

    lift = [set() for _ in range(len(base) * q)]
    for (u, v), shift in supplied.items():
        for fiber in range(q):
            left = u * q + fiber
            right = v * q + ((fiber + shift) % q)
            if right == left or right in lift[left]:
                raise AssertionError("lift is not simple")
            lift[left].add(right)
            lift[right].add(left)
    if any(len(neighbors) != 3 for neighbors in lift):
        raise AssertionError("lift is not cubic")
    return lift


def adjacency_digest(graph: list[set[int]]) -> str:
    digest = hashlib.sha256()
    for u, neighbors in enumerate(graph):
        for v in sorted(neighbors):
            if u < v:
                digest.update(f"{u},{v}\n".encode())
    return digest.hexdigest()


def components(graph: list[set[int]]) -> list[list[int]]:
    unseen = set(range(len(graph)))
    result: list[list[int]] = []
    while unseen:
        root = min(unseen)
        unseen.remove(root)
        seen = {root}
        stack = [root]
        while stack:
            vertex = stack.pop()
            for neighbor in graph[vertex]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    unseen.discard(neighbor)
                    stack.append(neighbor)
        result.append(sorted(seen))
    return result


def induced_component(graph: list[set[int]], vertices: list[int]) -> list[set[int]]:
    index = {old: new for new, old in enumerate(vertices)}
    return [
        {index[neighbor] for neighbor in graph[old] if neighbor in index}
        for old in vertices
    ]


def first_cycle(graph: list[set[int]], length: int) -> list[int] | None:
    n = len(graph)
    if length > n:
        return None
    path = [-1] * length
    for start in range(n):
        path[0] = start
        for first in sorted(vertex for vertex in graph[start] if vertex > start):
            path[1] = first
            used = {start, first}

            def dfs(depth: int, current: int) -> list[int] | None:
                if depth == length:
                    if start in graph[current] and path[1] < path[-1]:
                        return path.copy()
                    return None
                for nxt in sorted(graph[current]):
                    if nxt <= start or nxt in used:
                        continue
                    if depth == length - 1 and start not in graph[nxt]:
                        continue
                    path[depth] = nxt
                    used.add(nxt)
                    answer = dfs(depth + 1, nxt)
                    if answer is not None:
                        return answer
                    used.remove(nxt)
                return None

            answer = dfs(2, first)
            if answer is not None:
                return answer
    return None


def verify(witness: dict) -> dict:
    lift = build_lift(witness)
    if len(lift) != witness["lift_order"]:
        raise AssertionError("lift order mismatch")
    digest = adjacency_digest(lift)
    component_results = []
    for vertices in components(lift):
        component = induced_component(lift, vertices)
        if min(map(len, component)) != 3:
            raise AssertionError("component is not cubic")
        checked = []
        power = 4
        while power <= len(component):
            cycle = first_cycle(component, power)
            checked.append(power)
            if cycle is not None:
                raise AssertionError(
                    f"forbidden C_{power} in component on fibers {vertices}: {cycle}"
                )
            power *= 2
        component_results.append({
            "order": len(component),
            "minimum_degree": min(map(len, component)),
            "power_lengths_checked": checked,
        })
    if digest != witness["lift_adjacency_sha256"]:
        raise AssertionError("lift adjacency digest mismatch")
    return {
        "verified": True,
        "lift_order": len(lift),
        "lift_adjacency_sha256": digest,
        "components": component_results,
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
