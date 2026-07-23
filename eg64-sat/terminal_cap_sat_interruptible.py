#!/usr/bin/env python3
"""Interruptible backend driver for terminal_cap_sat.

The mathematical encoding and lazy-clause loop remain in terminal_cap_sat.
This driver changes only solver selection because PySAT's CaDiCaL wrapper does
not implement solve_limited/clear_interrupt, while Glucose4 and Minisat22 do.
"""
from __future__ import annotations

import terminal_cap_sat as core
from pysat.solvers import Glucose4, Minisat22


def make_interruptible_solver(cnf):
    for solver_class in (Glucose4, Minisat22):
        try:
            return solver_class(bootstrap_with=cnf.clauses), solver_class.__name__
        except Exception:
            continue
    raise RuntimeError("no interruptible PySAT backend is available")


core.make_solver = make_interruptible_solver


if __name__ == "__main__":
    raise SystemExit(core.main())
