#!/usr/bin/env python3
"""Exact lazy SAT search for irregular minimal-counterexample structure.

For fixed order n and b=|B|, labels are chosen so A={0,...,n-b-1} is the
cubic class and B is the independent degree-at-least-four class. This loses no
isomorphism class because A/B are intrinsic degree classes. Necessary minimal
counterexample conditions encoded:
  * every A vertex has degree exactly 3;
  * every B vertex has degree at least 4;
  * B is independent;
  * every vertex has a neighbour in A (for A this is an explicit clause);
  * |A| >= 2|B| is enforced by the caller's admissible b range;
  * connectedness and forbidden C4/C8/C16 are enforced exactly.
All C4 clauses are static; connectivity and longer cycles are lazy.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from itertools import combinations
from pathlib import Path

import networkx as nx
from pysat.card import CardEnc, EncType
from pysat.formula import CNF, IDPool
from pysat.solvers import Glucose4, Minisat22


def edge_pairs(order: int):
    return tuple((u, v) for u in range(order) for v in range(u + 1, order))


def edge_var(index, u: int, v: int) -> int:
    if u > v:
        u, v = v, u
    return index[(u, v)]


def build_cnf(order: int, b_size: int):
    if b_size < 1 or 3 * b_size > order:
        raise ValueError("admissibility requires 1 <= |B| <= floor(n/3)")
    a_size = order - b_size
    pairs = edge_pairs(order)
    index = {edge: variable for variable, edge in enumerate(pairs, start=1)}
    pool = IDPool(start_from=len(pairs) + 1)
    cnf = CNF()

    # A vertices are exactly cubic.
    for vertex in range(a_size):
        incident = [edge_var(index, vertex, other) for other in range(order) if other != vertex]
        cnf.extend(CardEnc.equals(
            lits=incident, bound=3, vpool=pool, encoding=EncType.seqcounter
        ).clauses)
        # Every cubic vertex has a cubic neighbour.
        cnf.append([edge_var(index, vertex, other) for other in range(a_size) if other != vertex])

    # B vertices have degree at least four and B is independent.
    for vertex in range(a_size, order):
        incident_to_a = [edge_var(index, vertex, other) for other in range(a_size)]
        cnf.extend(CardEnc.atleast(
            lits=incident_to_a, bound=4, vpool=pool, encoding=EncType.seqcounter
        ).clauses)
    for u in range(a_size, order):
        for v in range(u + 1, order):
            cnf.append([-edge_var(index, u, v)])

    # Complete static C4 elimination.
    for first, second, third, fourth in combinations(range(order), 4):
        cnf.append([
            -edge_var(index, first, second), -edge_var(index, second, third),
            -edge_var(index, third, fourth), -edge_var(index, fourth, first),
        ])
        cnf.append([
            -edge_var(index, first, second), -edge_var(index, second, fourth),
            -edge_var(index, fourth, third), -edge_var(index, third, first),
        ])
        cnf.append([
            -edge_var(index, first, third), -edge_var(index, third, second),
            -edge_var(index, second, fourth), -edge_var(index, fourth, first),
        ])
    return cnf, pairs, index, a_size


def make_solver(cnf):
    for solver_class in (Glucose4, Minisat22):
        try:
            return solver_class(bootstrap_with=cnf.clauses), solver_class.__name__
        except Exception:
            continue
    raise RuntimeError("no interruptible SAT backend available")


def solve_with_deadline(solver, seconds: float):
    if seconds <= 0:
        return None
    timer = threading.Timer(seconds, solver.interrupt)
    timer.daemon = True
    timer.start()
    try:
        return solver.solve_limited(expect_interrupt=True)
    finally:
        timer.cancel()
        solver.clear_interrupt()


def graph_from_model(order, pairs, model):
    positive = {literal for literal in model if literal > 0}
    graph = nx.Graph()
    graph.add_nodes_from(range(order))
    graph.add_edges_from(edge for variable, edge in enumerate(pairs, start=1) if variable in positive)
    return graph


def connectivity_clauses(graph, index):
    components = [set(component) for component in nx.connected_components(graph)]
    if len(components) == 1:
        return []
    all_vertices = set(graph.nodes)
    clauses = []
    for component in components:
        complement = all_vertices - component
        clauses.append([
            edge_var(index, u, v)
            for u in sorted(component)
            for v in sorted(complement)
        ])
    return clauses


def canonical_cycles(graph, length, limit):
    adjacency = {vertex: tuple(sorted(graph.neighbors(vertex))) for vertex in graph.nodes}
    found = 0
    path = [-1] * length
    for start in sorted(graph.nodes):
        path[0] = start
        for first in adjacency[start]:
            if first <= start:
                continue
            path[1] = first
            used = {start, first}

            def search(depth, current):
                nonlocal found
                if found >= limit:
                    return
                if depth == length:
                    if start in adjacency[current] and path[1] < path[-1]:
                        found += 1
                        yield tuple(path)
                    return
                for neighbour in adjacency[current]:
                    if neighbour <= start or neighbour in used:
                        continue
                    if depth == length - 1 and start not in adjacency[neighbour]:
                        continue
                    path[depth] = neighbour
                    used.add(neighbour)
                    yield from search(depth + 1, neighbour)
                    used.remove(neighbour)
                    if found >= limit:
                        return

            yield from search(2, first)
            if found >= limit:
                return


def cycle_clauses(graph, index, lengths, limit):
    clauses = []
    counts = {}
    for length in lengths:
        count = 0
        for cycle in canonical_cycles(graph, length, limit):
            clauses.append([
                -edge_var(index, cycle[i], cycle[(i + 1) % length])
                for i in range(length)
            ])
            count += 1
        counts[length] = count
    return clauses, counts


def graph6_text(graph):
    return nx.to_graph6_bytes(graph, header=False).decode("ascii").strip()


def search(order, b_size, wall_seconds, cycle_batch, max_iterations):
    cnf, pairs, index, a_size = build_cnf(order, b_size)
    solver, solver_name = make_solver(cnf)
    start = time.monotonic()
    deadline = start + wall_seconds
    seen = set()
    stats = {
        "order": order,
        "a_size": a_size,
        "b_size": b_size,
        "solver": solver_name,
        "clauses_initial": len(cnf.clauses),
        "models": 0,
        "iterations": 0,
        "connectivity_cuts": 0,
        "cycle_clauses": {"8": 0, "16": 0},
        "clauses_added": 0,
        "status": "running",
        "seconds": 0.0,
    }
    witness = None
    try:
        for iteration in range(1, max_iterations + 1):
            stats["iterations"] = iteration
            sat = solve_with_deadline(solver, deadline - time.monotonic())
            if sat is None:
                stats["status"] = "timeout"
                break
            if sat is False:
                stats["status"] = "unsat"
                break
            stats["models"] += 1
            graph = graph_from_model(order, pairs, solver.get_model())
            pending = [("connectivity", clause, None) for clause in connectivity_clauses(graph, index)]
            if not pending:
                clauses, counts = cycle_clauses(
                    graph, index, tuple(length for length in (8, 16) if length <= order), cycle_batch
                )
                position = 0
                for length in (8, 16):
                    for _ in range(counts.get(length, 0)):
                        pending.append(("cycle", clauses[position], length))
                        position += 1
            if not pending:
                degrees = [graph.degree(vertex) for vertex in range(order)]
                witness = {
                    "kind": "minimal_structural_sat",
                    "order": order,
                    "a_size": a_size,
                    "b_size": b_size,
                    "graph6": graph6_text(graph),
                    "degrees": degrees,
                }
                stats["status"] = "sat_witness"
                break
            added = 0
            for kind, clause, length in pending:
                key = tuple(sorted(clause))
                if key in seen:
                    continue
                seen.add(key)
                solver.add_clause(clause)
                stats["clauses_added"] += 1
                added += 1
                if kind == "connectivity":
                    stats["connectivity_cuts"] += 1
                else:
                    stats["cycle_clauses"][str(length)] += 1
            if added == 0:
                raise AssertionError("violating model produced no new clause")
        else:
            stats["status"] = "iteration_limit"
    finally:
        solver.delete()
    stats["seconds"] = time.monotonic() - start
    return {"stats": stats, "witness": witness}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--order", type=int, required=True)
    parser.add_argument("--b-size", type=int, required=True)
    parser.add_argument("--wall-seconds", type=float, default=2400)
    parser.add_argument("--cycle-batch", type=int, default=512)
    parser.add_argument("--max-iterations", type=int, default=5_000_000)
    parser.add_argument("--output")
    parser.add_argument("--witness-out")
    args = parser.parse_args()
    result = search(args.order, args.b_size, args.wall_seconds, args.cycle_batch, args.max_iterations)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    if result["witness"] is not None and args.witness_out:
        Path(args.witness_out).write_text(
            json.dumps(result["witness"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(text, end="")
    status = result["stats"]["status"]
    if status == "sat_witness":
        return 10
    if status == "unsat":
        return 0
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
