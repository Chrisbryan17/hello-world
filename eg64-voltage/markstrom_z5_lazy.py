#!/usr/bin/env python3
"""Lazy algebraic search over normalized Z5 lifts of one order-24 extremal base.

Each forbidden lifted cycle projects to a closed walk in the base. Its signed
cotree-edge incidence vector c satisfies c·x = 0 mod 5 for the current voltage
assignment x. Adding c·x != 0 removes the entire obstruction hyperplane, not
just one assignment. Zero-homology obstructions fall back to an exact no-good.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from pysat.card import CardEnc, EncType
from pysat.formula import IDPool
from pysat.solvers import Solver
from z3 import And, Int, Mod, Or, Solver as Z3Solver, Sum, sat

from cyclic_lift_census import (
    connected,
    cyclic_lift,
    edge_list,
    first_cycle,
    lift_edges,
    spanning_tree_and_cotree,
)
from markstrom_z3_lift_shard import load_bases


def iter_bits(mask: int) -> Iterator[int]:
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def exact_cycle_sat(graph: tuple[int, ...], length: int) -> tuple[int, ...] | None:
    """Find one simple cycle of exact length using a position SAT encoding."""
    order = len(graph)
    pool = IDPool()

    def var(position: int, vertex: int) -> int:
        return pool.id((position, vertex))

    with Solver(name="cadical195") as solver:
        for position in range(length):
            encoding = CardEnc.equals(
                lits=[var(position, vertex) for vertex in range(order)],
                bound=1,
                vpool=pool,
                encoding=EncType.seqcounter,
            )
            solver.append_formula(encoding.clauses)
        for vertex in range(order):
            encoding = CardEnc.atmost(
                lits=[var(position, vertex) for position in range(length)],
                bound=1,
                vpool=pool,
                encoding=EncType.seqcounter,
            )
            solver.append_formula(encoding.clauses)
        for position in range(length):
            nxt = (position + 1) % length
            for vertex in range(order):
                neighbors = [var(nxt, neighbor) for neighbor in iter_bits(graph[vertex])]
                solver.add_clause([-var(position, vertex), *neighbors])

        # Position zero is the minimum-labeled cycle vertex.
        for root in range(order):
            for position in range(1, length):
                for smaller in range(root):
                    solver.add_clause([-var(0, root), -var(position, smaller)])
        # Choose one of the two orientations.
        for first in range(order):
            for last in range(first + 1):
                solver.add_clause([-var(1, first), -var(length - 1, last)])

        if not solver.solve():
            return None
        model = {literal for literal in solver.get_model() if literal > 0}
        cycle = []
        for position in range(length):
            choices = [vertex for vertex in range(order) if var(position, vertex) in model]
            if len(choices) != 1:
                raise AssertionError("SAT cycle model did not choose one vertex per position")
            cycle.append(choices[0])
        return tuple(cycle)


def first_forbidden_cycle(graph: tuple[int, ...]) -> tuple[int, tuple[int, ...]] | None:
    for length in (4, 8, 16, 32):
        cycle = first_cycle(graph, length)
        if cycle is not None:
            return length, cycle
    cycle64 = exact_cycle_sat(graph, 64)
    if cycle64 is not None:
        return 64, cycle64
    return None


def cycle_coefficients(
    cycle: tuple[int, ...],
    modulus: int,
    cotree: tuple[tuple[int, int], ...],
) -> tuple[int, ...]:
    index = {edge: position for position, edge in enumerate(cotree)}
    coefficients = [0] * len(cotree)
    for position, lifted_first in enumerate(cycle):
        lifted_second = cycle[(position + 1) % len(cycle)]
        base_first = lifted_first // modulus
        base_second = lifted_second // modulus
        if base_first == base_second:
            raise AssertionError("cover edge projected to a base loop")
        edge = tuple(sorted((base_first, base_second)))
        if edge not in index:
            continue
        sign = 1 if base_first < base_second else -1
        coefficients[index[edge]] = (coefficients[index[edge]] + sign) % modulus
    return tuple(coefficients)


@dataclass
class Stats:
    base_index: int
    base_file: str
    modulus: int = 5
    iterations: int = 0
    hyperplanes: int = 0
    nogoods: int = 0
    rejected_by_length: dict[str, int] | None = None
    elapsed_seconds: float = 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--special-dir", required=True)
    parser.add_argument("--base-index", type=int, required=True)
    parser.add_argument("--max-seconds", type=float, default=3000.0)
    parser.add_argument("--result", required=True)
    parser.add_argument("--witness-out", required=True)
    args = parser.parse_args()

    bases = load_bases(Path(args.special_dir))
    base_file, base = bases[args.base_index]
    tree, cotree = spanning_tree_and_cotree(base)
    if len(cotree) != 13:
        raise AssertionError(f"expected cycle rank 13, got {len(cotree)}")

    variables = [Int(f"x_{index}") for index in range(len(cotree))]
    solver = Z3Solver()
    for variable in variables:
        solver.add(variable >= 0, variable < 5)
    # Nonzero connected assignment, modulo multiplication by F5*.
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

    stats = Stats(base_index=args.base_index, base_file=base_file, rejected_by_length={})
    start = time.monotonic()
    witness = None
    seen_constraints: set[tuple[int, ...]] = set()

    while time.monotonic() - start < args.max_seconds:
        if solver.check() != sat:
            status = "unsat"
            break
        model = solver.model()
        assignment = tuple(model.eval(variable).as_long() for variable in variables)
        stats.iterations += 1
        lift = cyclic_lift(base, 5, cotree, assignment)
        if not connected(lift) or any(neighbors.bit_count() != 3 for neighbors in lift):
            raise AssertionError("normalized nonzero Z5 lift was not connected cubic")

        forbidden = first_forbidden_cycle(lift)
        if forbidden is None:
            witness = {
                "kind": "lazy_markstrom_z5_voltage_lift",
                "base_file": base_file,
                "base_index": args.base_index,
                "modulus": 5,
                "tree_edges": [list(edge) for edge in tree],
                "cotree_edges": [list(edge) for edge in cotree],
                "cotree_voltages": list(assignment),
                "order": len(lift),
                "edges": lift_edges(lift),
            }
            status = "witness"
            Path(args.witness_out).write_text(
                json.dumps(witness, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            break

        length, cycle = forbidden
        key = str(length)
        stats.rejected_by_length[key] = stats.rejected_by_length.get(key, 0) + 1
        coefficients = cycle_coefficients(cycle, 5, cotree)
        if any(coefficients):
            if coefficients in seen_constraints:
                raise AssertionError("current assignment violates a previously added hyperplane exclusion")
            seen_constraints.add(coefficients)
            solver.add(Mod(Sum(*[c * x for c, x in zip(coefficients, variables)]), 5) != 0)
            stats.hyperplanes += 1
        else:
            solver.add(Or(*[variable != value for variable, value in zip(variables, assignment)]))
            stats.nogoods += 1
    else:
        status = "timeout"

    stats.elapsed_seconds = time.monotonic() - start
    payload = {"status": status, "stats": asdict(stats), "witness": witness}
    Path(args.result).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))
    return 10 if status == "witness" else (0 if status == "unsat" else 124)


if __name__ == "__main__":
    raise SystemExit(main())
