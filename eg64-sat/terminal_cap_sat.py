#!/usr/bin/env python3
"""Lazy exact SAT synthesis for one-terminal cubic caps.

Searches labelled simple graphs on odd n with vertex 0 of degree 2 and every
other vertex of degree 3. Symmetry fixes N(0)={1,2} and one further edge 1--3.
Connectivity, biconnectivity, and forbidden C_4/C_8/C_16 constraints are added
as exact lazy clauses. A satisfying cap H yields a cubic counterexample by
joining the terminals of two copies with a bridge; every cycle remains inside
one copy.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Iterator

import networkx as nx
from pysat.card import CardEnc, EncType
from pysat.formula import CNF, IDPool
from pysat.solvers import Cadical195, Glucose4, Minisat22


def edge_pairs(order: int) -> tuple[tuple[int, int], ...]:
    return tuple((first, second) for first in range(order) for second in range(first + 1, order))


def make_edge_map(order: int) -> tuple[tuple[tuple[int, int], ...], dict[tuple[int, int], int]]:
    pairs = edge_pairs(order)
    return pairs, {edge: index + 1 for index, edge in enumerate(pairs)}


def edge_var(edge_index: dict[tuple[int, int], int], first: int, second: int) -> int:
    if first > second:
        first, second = second, first
    return edge_index[(first, second)]


def build_base_cnf(order: int) -> tuple[CNF, tuple[tuple[int, int], ...], dict[tuple[int, int], int]]:
    if order < 5 or order % 2 == 0:
        raise ValueError("terminal-cap order must be odd and at least five")
    pairs, edge_index = make_edge_map(order)
    pool = IDPool(start_from=len(pairs) + 1)
    cnf = CNF()

    # Exact degrees.
    for vertex in range(order):
        incident = [edge_var(edge_index, vertex, other) for other in range(order) if other != vertex]
        degree = 2 if vertex == 0 else 3
        cnf.extend(
            CardEnc.equals(
                lits=incident,
                bound=degree,
                vpool=pool,
                encoding=EncType.seqcounter,
            ).clauses
        )

    # Safe label symmetry: the unique degree-two vertex is 0, its neighbours
    # are named 1 and 2, and one nonterminal neighbour of 1 is named 3.
    cnf.append([edge_var(edge_index, 0, 1)])
    cnf.append([edge_var(edge_index, 0, 2)])
    for vertex in range(3, order):
        cnf.append([-edge_var(edge_index, 0, vertex)])
    cnf.append([edge_var(edge_index, 1, 3)])
    return cnf, pairs, edge_index


def model_graph(
    order: int,
    pairs: tuple[tuple[int, int], ...],
    model: list[int],
) -> nx.Graph:
    positive = {literal for literal in model if literal > 0}
    graph = nx.Graph()
    graph.add_nodes_from(range(order))
    for variable, edge in enumerate(pairs, start=1):
        if variable in positive:
            graph.add_edge(*edge)
    return graph


def cut_clause(
    edge_index: dict[tuple[int, int], int],
    first_side: set[int],
    second_side: set[int],
) -> list[int]:
    return [
        edge_var(edge_index, first, second)
        for first in sorted(first_side)
        for second in sorted(second_side)
        if first != second
    ]


def connectivity_clauses(
    graph: nx.Graph,
    edge_index: dict[tuple[int, int], int],
) -> list[list[int]]:
    components = [set(component) for component in nx.connected_components(graph)]
    if len(components) <= 1:
        return []
    all_vertices = set(graph.nodes)
    clauses = []
    # Every current component must acquire an outgoing edge. Complementary
    # clauses may duplicate; canonical tuple deduplication occurs in the caller.
    for component in components:
        clause = cut_clause(edge_index, component, all_vertices - component)
        if not clause:
            raise AssertionError("empty connectivity cut")
        clauses.append(clause)
    return clauses


def biconnectivity_clauses(
    graph: nx.Graph,
    edge_index: dict[tuple[int, int], int],
) -> list[list[int]]:
    if not nx.is_connected(graph):
        return []
    clauses = []
    all_vertices = set(graph.nodes)
    for articulation in nx.articulation_points(graph):
        reduced = graph.copy()
        reduced.remove_node(articulation)
        components = [set(component) for component in nx.connected_components(reduced)]
        if len(components) <= 1:
            continue
        without_articulation = all_vertices - {articulation}
        for component in components:
            other = without_articulation - component
            clause = cut_clause(edge_index, component, other)
            if not clause:
                raise AssertionError("empty articulation cut")
            clauses.append(clause)
    return clauses


def canonical_cycles(
    graph: nx.Graph,
    length: int,
    limit: int,
) -> Iterator[tuple[int, ...]]:
    """Enumerate undirected simple cycles once, capped only after `limit`."""
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

            def search(depth: int, current: int) -> Iterator[tuple[int, ...]]:
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


def forbidden_cycle_clauses(
    graph: nx.Graph,
    edge_index: dict[tuple[int, int], int],
    lengths: tuple[int, ...],
    per_length_limit: int,
) -> tuple[list[list[int]], dict[int, int]]:
    clauses = []
    counts = {}
    for length in lengths:
        count = 0
        for cycle in canonical_cycles(graph, length, per_length_limit):
            clause = []
            for index, first in enumerate(cycle):
                second = cycle[(index + 1) % length]
                clause.append(-edge_var(edge_index, first, second))
            clauses.append(clause)
            count += 1
        counts[length] = count
    return clauses, counts


def graph6_text(graph: nx.Graph) -> str:
    return nx.to_graph6_bytes(graph, header=False).decode("ascii").strip()


def doubled_counterexample(cap: nx.Graph) -> nx.Graph:
    order = cap.number_of_nodes()
    doubled = nx.disjoint_union(cap, cap)
    doubled.add_edge(0, order)
    return doubled


def make_solver(cnf: CNF):
    for solver_class in (Cadical195, Glucose4, Minisat22):
        try:
            return solver_class(bootstrap_with=cnf.clauses), solver_class.__name__
        except Exception:
            continue
    raise RuntimeError("no supported PySAT solver backend is available")


def solve_with_deadline(solver, seconds: float) -> bool | None:
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


def search_cap(
    order: int,
    wall_seconds: float,
    cycle_batch: int,
    max_iterations: int,
    progress_every: int,
) -> dict:
    cnf, pairs, edge_index = build_base_cnf(order)
    solver, solver_name = make_solver(cnf)
    start = time.monotonic()
    deadline = start + wall_seconds
    seen_clauses: set[tuple[int, ...]] = set()
    stats = {
        "order": order,
        "solver": solver_name,
        "iterations": 0,
        "models": 0,
        "clauses_initial": len(cnf.clauses),
        "clauses_added": 0,
        "connectivity_cuts": 0,
        "articulation_cuts": 0,
        "cycle_clauses": {"4": 0, "8": 0, "16": 0},
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
            graph = model_graph(order, pairs, solver.get_model())
            new_clauses: list[tuple[str, list[int], int | None]] = []

            for clause in connectivity_clauses(graph, edge_index):
                new_clauses.append(("connectivity", clause, None))
            if not new_clauses:
                for clause in biconnectivity_clauses(graph, edge_index):
                    new_clauses.append(("articulation", clause, None))
            if not new_clauses:
                cycle_clauses, counts = forbidden_cycle_clauses(
                    graph,
                    edge_index,
                    tuple(length for length in (4, 8, 16) if length <= order),
                    cycle_batch,
                )
                position = 0
                for length in (4, 8, 16):
                    count = counts.get(length, 0)
                    for _ in range(count):
                        new_clauses.append(("cycle", cycle_clauses[position], length))
                        position += 1

            added = 0
            for kind, clause, length in new_clauses:
                key = tuple(sorted(clause))
                if key in seen_clauses:
                    continue
                seen_clauses.add(key)
                solver.add_clause(clause)
                stats["clauses_added"] += 1
                added += 1
                if kind == "connectivity":
                    stats["connectivity_cuts"] += 1
                elif kind == "articulation":
                    stats["articulation_cuts"] += 1
                else:
                    stats["cycle_clauses"][str(length)] += 1

            if not new_clauses:
                counterexample = doubled_counterexample(graph)
                witness = {
                    "kind": "terminal_cap_sat",
                    "cap_order": order,
                    "cap_graph6": graph6_text(graph),
                    "counterexample_order": counterexample.number_of_nodes(),
                    "counterexample_graph6": graph6_text(counterexample),
                }
                stats["status"] = "sat_witness"
                break
            if added == 0:
                # The current model violates a condition whose clause was seen,
                # which indicates a logic error because the solver should already
                # satisfy every previously added clause.
                raise AssertionError("violating model produced no new lazy clause")

            if progress_every and iteration % progress_every == 0:
                print(
                    json.dumps(
                        {
                            "progress": iteration,
                            "models": stats["models"],
                            "clauses_added": stats["clauses_added"],
                            "seconds": time.monotonic() - start,
                        },
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                    flush=True,
                )
        else:
            stats["status"] = "iteration_limit"
    finally:
        solver.delete()

    stats["seconds"] = time.monotonic() - start
    return {"stats": stats, "witness": witness}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order", type=int, required=True)
    parser.add_argument("--wall-seconds", type=float, default=2400.0)
    parser.add_argument("--cycle-batch", type=int, default=256)
    parser.add_argument("--max-iterations", type=int, default=2_000_000)
    parser.add_argument("--progress-every", type=int, default=1000)
    parser.add_argument("--output")
    parser.add_argument("--witness-out")
    args = parser.parse_args()

    result = search_cap(
        args.order,
        args.wall_seconds,
        args.cycle_batch,
        args.max_iterations,
        args.progress_every,
    )
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    if result["witness"] is not None and args.witness_out:
        Path(args.witness_out).write_text(
            json.dumps(result["witness"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
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
