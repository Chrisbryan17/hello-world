#!/usr/bin/env python3
"""Interruptible, memory-bounded lazy SAT search for cubic counterexamples.

The target is a connected bridgeless simple cubic graph with no cycle whose
length is a power of two. Exact degree and all C4 exclusions are installed in
the base CNF. Each model contributes connectivity/bridge cuts and at most one
shortest forbidden-cycle clause. Any surviving model is independently
verifiable as an explicit Erdős--Gyárfás counterexample.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from pysat.card import CardEnc, EncType
from pysat.formula import IDPool
from pysat.solvers import Solver

from lazy_terminal_sat import (
    EdgeVariables,
    all_c4_clauses,
    bridge_sides,
    connected_components,
    edge_list,
    emit_checkpoint,
    graph6,
    graph_from_model,
    powers_of_two_le,
)
from lazy_terminal_sat_stable import (
    first_new_power_cycle_clause,
    solve_with_deadline,
)


@dataclass
class DirectStats:
    order: int
    solver: str
    status: str = "running"
    iterations: int = 0
    models: int = 0
    connectivity_cuts: int = 0
    bridge_cuts: int = 0
    cycle_clauses: int = 0
    c4_clauses: int = 0
    elapsed_seconds: float = 0.0


def write_checkpoint(
    path: Path | None, stats: DirectStats, extra: dict | None = None
) -> None:
    if path is None:
        return
    payload = {"stats": asdict(stats)}
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order", type=int, required=True)
    parser.add_argument("--solver", default="m22")
    parser.add_argument("--max-seconds", type=float, default=3000.0)
    parser.add_argument("--checkpoint")
    parser.add_argument("--witness-out")
    parser.add_argument("--log-every", type=int, default=100)
    args = parser.parse_args()

    order = args.order
    if order < 4 or order % 2 != 0:
        raise ValueError("a cubic graph requires even order at least four")
    if order < 6:
        raise ValueError("the symmetry-breaking scheme requires order at least six")

    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    witness_path = Path(args.witness_out) if args.witness_out else None
    pool = IDPool()
    edges = EdgeVariables(order, pool)
    stats = DirectStats(order=order, solver=args.solver)
    start = time.monotonic()
    learned_cycles: set[tuple[int, ...]] = set()
    learned_cuts: set[tuple[str, tuple[int, ...]]] = set()

    with Solver(name=args.solver) as solver:
        # Lossless labeling: N(0)={1,2,3}. In a C4-free cubic graph, vertex 1
        # has at least one neighbor outside {0,2,3}; label one such vertex 4.
        for neighbor in (1, 2, 3):
            solver.add_clause([edges.var(0, neighbor)])
        for vertex in range(4, order):
            solver.add_clause([-edges.var(0, vertex)])
        solver.add_clause([edges.var(1, 4)])

        for vertex in range(order):
            encoding = CardEnc.equals(
                lits=edges.incident(vertex),
                bound=3,
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
                    key = ("connected", tuple(sorted(canonical)))
                    if key in learned_cuts:
                        continue
                    learned_cuts.add(key)
                    solver.add_clause(edges.crossing(canonical))
                    stats.connectivity_cuts += 1
                    new_constraints += 1
            else:
                for shore in bridge_sides(adjacency):
                    key = ("bridge", tuple(sorted(shore)))
                    if key in learned_cuts:
                        continue
                    learned_cuts.add(key)
                    encoding = CardEnc.atleast(
                        lits=edges.crossing(shore),
                        bound=2,
                        vpool=pool,
                        encoding=EncType.seqcounter,
                    )
                    solver.append_formula(encoding.clauses)
                    stats.bridge_cuts += 1
                    new_constraints += 1

                clause = first_new_power_cycle_clause(
                    adjacency, order, edges, learned_cycles
                )
                if clause is not None:
                    learned_cycles.add(clause)
                    solver.add_clause(list(clause))
                    stats.cycle_clauses += 1
                    new_constraints += 1

            if new_constraints == 0:
                degrees = [neighbors.bit_count() for neighbors in adjacency]
                if any(degree != 3 for degree in degrees):
                    raise AssertionError(degrees)
                stats.status = "witness"
                witness = {
                    "kind": "sat_cubic_counterexample",
                    "order": order,
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
                print(
                    json.dumps(
                        {"stats": asdict(stats), "witness": witness},
                        sort_keys=True,
                    )
                )
                return 10

            if args.log_every and stats.iterations % args.log_every == 0:
                write_checkpoint(checkpoint, stats)
                print(
                    json.dumps(
                        {
                            "progress": asdict(stats),
                            "new_constraints": new_constraints,
                            "components": len(components),
                            "learned_cycle_set_size": len(learned_cycles),
                            "learned_cut_set_size": len(learned_cuts),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )


if __name__ == "__main__":
    raise SystemExit(main())
