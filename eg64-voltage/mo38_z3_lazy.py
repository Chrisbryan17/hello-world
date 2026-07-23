#!/usr/bin/env python3
"""Lazy algebraic Z3-cover search over a public 38-vertex cubic C4/C8-free base."""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from z3 import And, Int, Mod, Or, Solver as Z3Solver, Sum, sat

from cyclic_lift_census import connected, cyclic_lift, lift_edges, spanning_tree_and_cotree
from markstrom_z5_lazy import cycle_coefficients, first_forbidden_cycle


NEIGHBORS = {
    0: (1, 2, 3), 1: (0, 4, 7), 2: (0, 6, 9), 3: (0, 5, 8),
    4: (1, 10, 13), 5: (3, 11, 15), 6: (2, 12, 14), 7: (1, 11, 16),
    8: (3, 12, 18), 9: (2, 10, 17), 10: (4, 9, 28), 11: (5, 7, 26),
    12: (6, 8, 27), 13: (4, 32, 35), 14: (6, 34, 37), 15: (5, 33, 36),
    16: (7, 29, 35), 17: (9, 31, 37), 18: (8, 30, 36), 19: (29, 30, 31),
    20: (27, 32, 34), 21: (28, 32, 33), 22: (26, 33, 34), 23: (27, 30, 35),
    24: (28, 31, 36), 25: (26, 29, 37), 26: (11, 22, 25), 27: (12, 20, 23),
    28: (10, 21, 24), 29: (16, 19, 25), 30: (18, 19, 23), 31: (17, 19, 24),
    32: (13, 20, 21), 33: (15, 21, 22), 34: (14, 20, 22), 35: (13, 16, 23),
    36: (15, 18, 24), 37: (14, 17, 25),
}


def base_graph() -> tuple[int, ...]:
    graph = [0] * 38
    for vertex, neighbors in NEIGHBORS.items():
        if len(neighbors) != 3:
            raise AssertionError("base is not cubic")
        for neighbor in neighbors:
            if vertex not in NEIGHBORS.get(neighbor, ()):
                raise AssertionError(f"asymmetric base edge {vertex}-{neighbor}")
            graph[vertex] |= 1 << neighbor
    result = tuple(graph)
    if not connected(result) or any(mask.bit_count() != 3 for mask in result):
        raise AssertionError("invalid embedded base graph")
    return result


@dataclass
class Stats:
    modulus: int = 3
    base_order: int = 38
    lift_order: int = 114
    cycle_rank: int = 20
    iterations: int = 0
    hyperplanes: int = 0
    nogoods: int = 0
    rejected_by_length: dict[str, int] | None = None
    elapsed_seconds: float = 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-seconds", type=float, default=3000.0)
    parser.add_argument("--result", required=True)
    parser.add_argument("--witness-out", required=True)
    args = parser.parse_args()

    base = base_graph()
    tree, cotree = spanning_tree_and_cotree(base)
    if len(cotree) != 20:
        raise AssertionError(f"expected cycle rank 20, got {len(cotree)}")

    variables = [Int(f"x_{index}") for index in range(len(cotree))]
    solver = Z3Solver()
    for variable in variables:
        solver.add(variable >= 0, variable < 3)
    solver.add(
        Or(
            *[
                And(
                    *[variables[earlier] == 0 for earlier in range(index)],
                    variables[index] == 1,
                )
                for index in range(len(variables))
            ]
        )
    )

    stats = Stats(rejected_by_length={})
    start = time.monotonic()
    witness = None
    seen_hyperplanes: set[tuple[int, ...]] = set()

    while time.monotonic() - start < args.max_seconds:
        if solver.check() != sat:
            status = "unsat"
            break
        model = solver.model()
        assignment = tuple(model.eval(variable).as_long() for variable in variables)
        stats.iterations += 1
        lift = cyclic_lift(base, 3, cotree, assignment)
        if not connected(lift) or any(mask.bit_count() != 3 for mask in lift):
            raise AssertionError("normalized nonzero Z3 lift was not connected cubic")

        forbidden = first_forbidden_cycle(lift)
        if forbidden is None:
            witness = {
                "kind": "lazy_mo38_z3_voltage_lift",
                "base_order": 38,
                "base_adjacency": {str(k): list(v) for k, v in NEIGHBORS.items()},
                "modulus": 3,
                "tree_edges": [list(edge) for edge in tree],
                "cotree_edges": [list(edge) for edge in cotree],
                "cotree_voltages": list(assignment),
                "order": len(lift),
                "edges": lift_edges(lift),
            }
            Path(args.witness_out).write_text(
                json.dumps(witness, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            status = "witness"
            break

        length, cycle = forbidden
        key = str(length)
        stats.rejected_by_length[key] = stats.rejected_by_length.get(key, 0) + 1
        coefficients = cycle_coefficients(cycle, 3, cotree)
        if any(coefficients):
            if coefficients in seen_hyperplanes:
                raise AssertionError("current model violates an installed hyperplane exclusion")
            seen_hyperplanes.add(coefficients)
            solver.add(Mod(Sum(*[c * x for c, x in zip(coefficients, variables)]), 3) != 0)
            stats.hyperplanes += 1
        else:
            solver.add(Or(*[variable != value for variable, value in zip(variables, assignment)]))
            stats.nogoods += 1
    else:
        status = "timeout"

    stats.elapsed_seconds = time.monotonic() - start
    payload = {"status": status, "stats": asdict(stats), "witness": witness}
    Path(args.result).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, sort_keys=True))
    return 10 if status == "witness" else (0 if status == "unsat" else 124)


if __name__ == "__main__":
    raise SystemExit(main())
