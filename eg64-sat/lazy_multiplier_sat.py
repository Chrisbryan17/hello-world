#!/usr/bin/env python3
"""Lazy SAT search for a three-terminal odd-multiplier cubic gadget.

The graph has terminals 0,1,2 of degree 2 and every other vertex of degree 3.
It must contain no power-of-two cycle. For every simple path between distinct
terminals, ``length + 1`` must be divisible by the chosen odd modulus.

Replacing each vertex of any cubic base graph by such a gadget makes every
cross-gadget cycle length divisible by the odd modulus, while internal cycles
remain non-powers. Thus one verified gadget yields an explicit cubic
counterexample to the Erdős--Gyárfás conjecture.
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

from lazy_terminal_sat import (
    EdgeVariables,
    all_c4_clauses,
    connected_components,
    edge_list,
    graph6,
    graph_from_model,
    iter_bits,
    powers_of_two_le,
)
from lazy_terminal_sat_stable import (
    first_new_power_cycle_clause,
    solve_with_deadline,
)


@dataclass
class MultiplierStats:
    order: int
    modulus: int
    solver: str
    status: str = "running"
    iterations: int = 0
    models: int = 0
    connectivity_cuts: int = 0
    c4_clauses: int = 0
    cycle_clauses: int = 0
    path_clauses: int = 0
    elapsed_seconds: float = 0.0


def write_checkpoint(
    path: Path | None, stats: MultiplierStats, extra: dict | None = None
) -> None:
    if path is None:
        return
    payload = {"stats": asdict(stats)}
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def first_bad_terminal_path(
    adjacency: tuple[int, ...],
    terminals: tuple[int, int, int],
    modulus: int,
) -> tuple[int, ...] | None:
    """Return one simple terminal path violating ``(length+1) mod q = 0``."""
    order = len(adjacency)
    path = [0] * order
    for pair_index, (start, target) in enumerate(
        ((terminals[0], terminals[1]),
         (terminals[0], terminals[2]),
         (terminals[1], terminals[2]))
    ):
        path[0] = start

        def dfs(depth: int, current: int, used: int) -> tuple[int, ...] | None:
            if current == target:
                length = depth - 1
                if (length + 1) % modulus != 0:
                    return tuple(path[:depth])
                return None
            for neighbor in iter_bits(adjacency[current] & ~used):
                path[depth] = neighbor
                answer = dfs(depth + 1, neighbor, used | (1 << neighbor))
                if answer is not None:
                    return answer
            return None

        answer = dfs(1, start, 1 << start)
        if answer is not None:
            return answer
    return None


def path_clause(path: tuple[int, ...], edges: EdgeVariables) -> tuple[int, ...]:
    return tuple(
        sorted(-edges.var(path[index], path[index + 1]) for index in range(len(path) - 1))
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order", type=int, required=True)
    parser.add_argument("--modulus", type=int, default=3)
    parser.add_argument("--solver", default="m22")
    parser.add_argument("--max-seconds", type=float, default=3000.0)
    parser.add_argument("--checkpoint")
    parser.add_argument("--witness-out")
    parser.add_argument("--log-every", type=int, default=100)
    args = parser.parse_args()

    order = args.order
    modulus = args.modulus
    if order < 5 or order % 2 == 0:
        raise ValueError("three degree-2 terminals and all other degree-3 vertices require odd order")
    if modulus <= 1 or modulus % 2 == 0:
        raise ValueError("the multiplier modulus must be odd and greater than one")

    terminals = (0, 1, 2)
    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    witness_path = Path(args.witness_out) if args.witness_out else None
    pool = IDPool()
    edges = EdgeVariables(order, pool)
    stats = MultiplierStats(order=order, modulus=modulus, solver=args.solver)
    start = time.monotonic()
    learned_cycles: set[tuple[int, ...]] = set()
    learned_paths: set[tuple[int, ...]] = set()
    learned_cuts: set[tuple[int, ...]] = set()

    with Solver(name=args.solver) as solver:
        # Fix terminal 0's two neighbors by relabeling.
        solver.add_clause([edges.var(0, 3)])
        solver.add_clause([edges.var(0, 4)])
        for vertex in range(1, order):
            if vertex not in (3, 4):
                solver.add_clause([-edges.var(0, vertex)])

        for vertex in range(order):
            target = 2 if vertex in terminals else 3
            encoding = CardEnc.equals(
                lits=edges.incident(vertex),
                bound=target,
                vpool=pool,
                encoding=EncType.seqcounter,
            )
            solver.append_formula(encoding.clauses)

        for clause in all_c4_clauses(order, edges):
            solver.add_clause(list(clause))
            stats.c4_clauses += 1

        while True:
            stats.elapsed_seconds = time.monotonic() - start
            remaining = args.max_seconds - stats.elapsed_seconds
            if remaining <= 0:
                stats.status = "timeout"
                write_checkpoint(checkpoint, stats)
                print(json.dumps({"stats": asdict(stats)}, sort_keys=True))
                return 124

            stats.iterations += 1
            satisfiable = solve_with_deadline(solver, remaining)
            stats.elapsed_seconds = time.monotonic() - start
            if satisfiable is None:
                stats.status = "timeout"
                write_checkpoint(checkpoint, stats)
                print(json.dumps({"stats": asdict(stats)}, sort_keys=True))
                return 124
            if satisfiable is False:
                stats.status = "unsat"
                write_checkpoint(checkpoint, stats)
                print(json.dumps({"stats": asdict(stats)}, sort_keys=True))
                return 0

            stats.models += 1
            adjacency = graph_from_model(order, edges, solver.get_model())
            components = connected_components(adjacency)
            new_constraints = 0

            if len(components) > 1:
                for component in components:
                    if len(component) == order:
                        continue
                    complement = set(range(order)) - component
                    canonical = (
                        component
                        if (len(component), sorted(component))
                        <= (len(complement), sorted(complement))
                        else complement
                    )
                    key = tuple(sorted(canonical))
                    if key in learned_cuts:
                        continue
                    learned_cuts.add(key)
                    solver.add_clause(edges.crossing(canonical))
                    stats.connectivity_cuts += 1
                    new_constraints += 1
            else:
                cycle = first_new_power_cycle_clause(
                    adjacency, order, edges, learned_cycles
                )
                if cycle is not None:
                    learned_cycles.add(cycle)
                    solver.add_clause(list(cycle))
                    stats.cycle_clauses += 1
                    new_constraints += 1

                bad_path = first_bad_terminal_path(adjacency, terminals, modulus)
                if bad_path is not None:
                    clause = path_clause(bad_path, edges)
                    if clause in learned_paths:
                        raise AssertionError("current model contains an already-blocked terminal path")
                    learned_paths.add(clause)
                    solver.add_clause(list(clause))
                    stats.path_clauses += 1
                    new_constraints += 1

            if new_constraints == 0:
                degrees = [neighbors.bit_count() for neighbors in adjacency]
                stats.status = "witness"
                witness = {
                    "kind": "sat_three_terminal_multiplier",
                    "order": order,
                    "terminals": list(terminals),
                    "modulus": modulus,
                    "graph6": graph6(adjacency),
                    "edges": edge_list(adjacency),
                    "degree_sequence": degrees,
                    "power_cycle_lengths_checked": list(powers_of_two_le(order)),
                    "stats": asdict(stats),
                }
                if witness_path is not None:
                    witness_path.write_text(
                        json.dumps(witness, indent=2, sort_keys=True) + "\n"
                    )
                write_checkpoint(checkpoint, stats, {"witness": witness})
                print(json.dumps({"stats": asdict(stats), "witness": witness}, sort_keys=True))
                return 10

            if args.log_every and stats.iterations % args.log_every == 0:
                write_checkpoint(checkpoint, stats)
                print(
                    json.dumps(
                        {
                            "progress": asdict(stats),
                            "new_constraints": new_constraints,
                            "components": len(components),
                            "learned_cycles": len(learned_cycles),
                            "learned_paths": len(learned_paths),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )


if __name__ == "__main__":
    raise SystemExit(main())
