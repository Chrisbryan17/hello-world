#!/usr/bin/env python3
"""Terminal-cap SAT driver with every C4 excluded statically.

This reuses terminal_cap_sat's exact degree, connectivity, articulation and lazy
C8/C16 machinery. It adds the complete set of C4 clauses before search and
selects an interruptible backend.
"""
from __future__ import annotations

from itertools import combinations

import terminal_cap_sat as core
from pysat.solvers import Glucose4, Minisat22


_original_build_base_cnf = core.build_base_cnf


def build_base_cnf_with_all_c4(order: int):
    cnf, pairs, edge_index = _original_build_base_cnf(order)

    def edge(first: int, second: int) -> int:
        return core.edge_var(edge_index, first, second)

    for first, second, third, fourth in combinations(range(order), 4):
        # The three distinct undirected four-cycles on this four-set.
        cnf.append([
            -edge(first, second), -edge(second, third),
            -edge(third, fourth), -edge(fourth, first),
        ])
        cnf.append([
            -edge(first, second), -edge(second, fourth),
            -edge(fourth, third), -edge(third, first),
        ])
        cnf.append([
            -edge(first, third), -edge(third, second),
            -edge(second, fourth), -edge(fourth, first),
        ])
    return cnf, pairs, edge_index


def make_interruptible_solver(cnf):
    for solver_class in (Glucose4, Minisat22):
        try:
            return solver_class(bootstrap_with=cnf.clauses), solver_class.__name__
        except Exception:
            continue
    raise RuntimeError("no interruptible PySAT backend is available")


core.build_base_cnf = build_base_cnf_with_all_c4
core.make_solver = make_interruptible_solver


if __name__ == "__main__":
    raise SystemExit(core.main())
