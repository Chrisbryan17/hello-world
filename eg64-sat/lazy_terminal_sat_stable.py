#!/usr/bin/env python3
"""Memory-bounded, interruptible lazy SAT search for one-terminal caps.

This is the hardened successor to ``lazy_terminal_sat.py``. It reuses the
verified graph and CNF helpers but changes two operational properties:

* each model contributes at most one new forbidden-cycle clause; and
* every SAT call is wrapped in PySAT's documented interrupt mechanism.

Consequently, a wall-clock budget always yields a checkpoint instead of
leaving the process trapped inside one native solver call or accumulating every
cycle of every intermediate model in Python memory.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from threading import Timer

from pysat.card import CardEnc, EncType
from pysat.formula import IDPool
from pysat.solvers import Solver

from lazy_terminal_sat import (
    EdgeVariables,
    Statistics,
    all_c4_clauses,
    bridge_sides,
    canonical_cycles,
    connected_components,
    cycle_clause,
    edge_list,
    emit_checkpoint,
    graph6,
    graph_from_model,
    powers_of_two_le,
)


def solve_with_deadline(solver: Solver, seconds: float) -> bool | None:
    """Return SAT/UNSAT, or ``None`` when the timer interrupts the call."""
    if seconds <= 0:
        return None
    timer = Timer(seconds, solver.interrupt)
    timer.daemon = True
    timer.start()
    try:
        result = solver.solve_limited(expect_interrupt=True)
    finally:
        timer.cancel()
    if result is None:
        solver.clear_interrupt()
    return result


def first_new_power_cycle_clause(
    adjacency: tuple[int, ...],
    order: int,
    edges: EdgeVariables,
    learned: set[tuple[int, ...]],
) -> tuple[int, ...] | None:
    """Return one shortest unlearned forbidden-cycle clause for the model."""
    for length in powers_of_two_le(order):
        if length == 4:
            continue
        for cycle in canonical_cycles(adjacency, length):
            clause = cycle_clause(cycle, edges)
            if clause not in learned:
                return clause
            # A current model cannot satisfy a previously installed blocking
            # clause. Reaching this branch indicates a solver/model mismatch.
            raise AssertionError("current model contains an already-blocked cycle")
    return None


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
    if order < 5 or order % 2 == 0:
        raise ValueError("one-terminal degree sequence requires odd order at least 5")

    checkpoint = Path(args.checkpoint) if args.checkpoint else None
    witness_path = Path(args.witness_out) if args.witness_out else None
    pool = IDPool()
    edges = EdgeVariables(order, pool)
    stats = Statistics(order=order, solver=args.solver)
    start_time = time.monotonic()
    learned_cycles: set[tuple[int, ...]] = set()
    learned_cuts: set[tuple[str, tuple[int, ...]]] = set()

    with Solver(name=args.solver) as solver:
        # Lossless label symmetry breaking.
        solver.add_clause([edges.var(0, 1)])
        solver.add_clause([edges.var(0, 2)])
        for vertex in range(3, order):
            solver.add_clause([-edges.var(0, vertex)])
        solver.add_clause([edges.var(1, 3)])

        for vertex in range(order):
            target = 2 if vertex == 0 else 3
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
            stats.elapsed_seconds = time.monotonic() - start_time
            remaining = args.max_seconds - stats.elapsed_seconds
            if remaining <= 0:
                stats.status = "timeout"
                emit_checkpoint(checkpoint, stats)
                print(json.dumps({"stats": asdict(stats)}, sort_keys=True))
                return 124

            stats.iterations += 1
            satisfiable = solve_with_deadline(solver, remaining)
            stats.elapsed_seconds = time.monotonic() - start_time
            if satisfiable is None:
                stats.status = "timeout"
                emit_checkpoint(checkpoint, stats)
                print(json.dumps({"stats": asdict(stats)}, sort_keys=True))
                return 124
            if satisfiable is False:
                stats.status = "unsat"
                emit_checkpoint(checkpoint, stats)
                print(json.dumps({"stats": asdict(stats)}, sort_keys=True))
                return 0

            stats.models += 1
            adjacency = graph_from_model(order, edges, solver.get_model())
            new_constraints = 0
            components = connected_components(adjacency)

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
                stats.status = "witness"
                witness = {
                    "kind": "sat_terminal_cap",
                    "order": order,
                    "terminal": 0,
                    "graph6": graph6(adjacency),
                    "edges": edge_list(adjacency),
                    "degree_sequence": degrees,
                    "doubled_counterexample_order": 2 * order,
                    "power_cycle_lengths_checked": list(powers_of_two_le(order)),
                    "stats": asdict(stats),
                }
                if witness_path is not None:
                    witness_path.write_text(
                        json.dumps(witness, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                emit_checkpoint(checkpoint, stats, {"witness": witness})
                print(
                    json.dumps(
                        {"stats": asdict(stats), "witness": witness},
                        sort_keys=True,
                    )
                )
                return 10

            if args.log_every and stats.iterations % args.log_every == 0:
                emit_checkpoint(checkpoint, stats)
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
