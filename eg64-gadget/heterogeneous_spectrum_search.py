#!/usr/bin/env python3
"""Exact heterogeneous path-spectrum CSP for three-terminal gadgets.

Each base vertex independently chooses a surviving gadget spectrum and one of
its six physical terminal assignments. Catalog entries are deduplicated only
when gadget order and all three ordered terminal-pair path spectra are exactly
identical; such entries are interchangeable for cycle existence and one source
representative is retained for witness reconstruction.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from spectrum_wiring_search import PERMUTATIONS, encoded_base_cycles, parse_graph6

SLOT_PAIR_INDEX = {(0, 1): 0, (0, 2): 1, (1, 2): 2}
PHYSICAL_PAIR_INDEX = {(0, 1): 0, (0, 2): 1, (1, 2): 2}


def deduplicate_catalog(raw_entries: list[dict]) -> list[dict]:
    catalog = []
    seen = set()
    for entry in raw_entries:
        spectra = tuple(tuple(spectrum) for spectrum in entry["path_spectra"])
        key = int(entry["gadget_order"]), spectra
        if key in seen:
            continue
        seen.add(key)
        representative = dict(entry)
        representative["path_spectra"] = [list(spectrum) for spectrum in spectra]
        catalog.append(representative)
    return catalog


def build_domains(
    catalog: list[dict],
) -> tuple[
    tuple[tuple[int, tuple[int, int, int]], ...],
    tuple[tuple[int, int, int], ...],
    tuple[tuple[int, ...], ...],
]:
    spectrum_ids: dict[tuple[int, ...], int] = {}
    spectra: list[tuple[int, ...]] = []

    def spectrum_id(values: tuple[int, ...]) -> int:
        if values not in spectrum_ids:
            spectrum_ids[values] = len(spectra)
            spectra.append(values)
        return spectrum_ids[values]

    domains = []
    pair_spectrum_ids = []
    for gadget_index, gadget in enumerate(catalog):
        gadget_spectra = [tuple(values) for values in gadget["path_spectra"]]
        for permutation in PERMUTATIONS:
            row = []
            for first_slot, second_slot in ((0, 1), (0, 2), (1, 2)):
                first = permutation[first_slot]
                second = permutation[second_slot]
                if first > second:
                    first, second = second, first
                spectrum = gadget_spectra[PHYSICAL_PAIR_INDEX[(first, second)]]
                row.append(spectrum_id(spectrum))
            domains.append((gadget_index, permutation))
            pair_spectrum_ids.append(tuple(row))
    return tuple(domains), tuple(pair_spectrum_ids), tuple(spectra)


def slot_pair_index(first: int, second: int) -> int:
    if first > second:
        first, second = second, first
    return SLOT_PAIR_INDEX[(first, second)]


def solve_exact(
    catalog: list[dict], base: tuple[int, ...]
) -> tuple[
    tuple[int, ...] | None,
    int,
    int,
    int,
    tuple[tuple[int, tuple[int, int, int]], ...],
    int,
]:
    domains, pair_spectrum_ids, spectra = build_domains(catalog)
    domain_size = len(domains)
    constraints = encoded_base_cycles(base)

    # Every spectrum in the recovered catalog is a complete integer interval.
    # Retain an assertion so this fast path can never silently over-approximate.
    spectrum_bounds = []
    for spectrum in spectra:
        if spectrum != tuple(range(spectrum[0], spectrum[-1] + 1)):
            raise AssertionError(("non-interval spectrum", spectrum))
        spectrum_bounds.append((spectrum[0], spectrum[-1]))
    domain_pair_bounds = tuple(
        tuple(spectrum_bounds[spectrum_id] for spectrum_id in row)
        for row in pair_spectrum_ids
    )
    slot_options = tuple(
        tuple(sorted({domain_pair_bounds[domain][pair] for domain in range(domain_size)}))
        for pair in range(3)
    )

    occurrences = [0] * len(base)
    constraints_by_vertex = [[] for _ in base]
    for constraint in constraints:
        for vertex, _, _ in constraint:
            occurrences[vertex] += 1
            constraints_by_vertex[vertex].append(constraint)
    variable_order = tuple(
        sorted(range(len(base)), key=lambda vertex: (-occurrences[vertex], vertex))
    )

    maximum_order = max(int(gadget["gadget_order"]) for gadget in catalog) * len(base)
    powers = []
    power = 4
    while power <= maximum_order:
        powers.append(power)
        power *= 2

    def interval_contains_power(lower: int, upper: int) -> bool:
        return any(lower <= power <= upper for power in powers)

    completion_cache: dict[tuple[int, int, int], tuple[tuple[int, int], ...]] = {}

    def completion_bounds(counts: tuple[int, int, int]) -> tuple[tuple[int, int], ...]:
        if counts in completion_cache:
            return completion_cache[counts]
        possible = {(0, 0)}
        for pair_index, count in enumerate(counts):
            for _ in range(count):
                possible = {
                    (lower + option_lower, upper + option_upper)
                    for lower, upper in possible
                    for option_lower, option_upper in slot_options[pair_index]
                }
        answer = tuple(sorted(possible))
        completion_cache[counts] = answer
        return answer

    feasibility_cache: dict[tuple[int, int, int, int, int], bool] = {}
    assignments: list[int | None] = [None] * len(base)
    covered_configurations = 0
    search_nodes = 0

    def constraint_has_avoiding_completion(
        constraint: tuple[tuple[int, int, int], ...]
    ) -> bool:
        assigned_lower = 0
        assigned_upper = 0
        unassigned_counts = [0, 0, 0]
        for vertex, first_slot, second_slot in constraint:
            pair_index = slot_pair_index(first_slot, second_slot)
            domain_index = assignments[vertex]
            if domain_index is None:
                unassigned_counts[pair_index] += 1
            else:
                lower, upper = domain_pair_bounds[domain_index][pair_index]
                assigned_lower += lower
                assigned_upper += upper
        key = (
            assigned_lower,
            assigned_upper,
            unassigned_counts[0],
            unassigned_counts[1],
            unassigned_counts[2],
        )
        if key not in feasibility_cache:
            feasibility_cache[key] = any(
                not interval_contains_power(
                    assigned_lower + additional_lower,
                    assigned_upper + additional_upper,
                )
                for additional_lower, additional_upper in completion_bounds(
                    tuple(unassigned_counts)
                )
            )
        return feasibility_cache[key]

    def search(depth: int) -> tuple[int, ...] | None:
        nonlocal covered_configurations, search_nodes
        search_nodes += 1
        if depth == len(variable_order):
            return tuple(
                assignment for assignment in assignments if assignment is not None
            )
        vertex = variable_order[depth]
        for domain_index in range(domain_size):
            assignments[vertex] = domain_index
            failed = any(
                not constraint_has_avoiding_completion(constraint)
                for constraint in constraints_by_vertex[vertex]
            )
            if failed:
                covered_configurations += domain_size ** (
                    len(variable_order) - depth - 1
                )
            else:
                answer = search(depth + 1)
                if answer is not None:
                    return answer
        assignments[vertex] = None
        return None

    answer = search(0)
    return (
        answer,
        covered_configurations,
        search_nodes,
        len(constraints),
        domains,
        len(feasibility_cache) + len(completion_cache),
    )

def self_test() -> None:
    from spectrum_wiring_search import (
        delete_vertex,
        parse_graph6,
        terminal_path_spectra,
    )

    _, source = parse_graph6(b"C~")
    gadget, terminals = delete_vertex(source, 0)
    spectra = terminal_path_spectra(gadget, terminals)
    catalog = [
        {
            "source_graph6": "C~",
            "source_order": 4,
            "deleted_vertex": 0,
            "gadget_order": 3,
            "terminals": list(terminals),
            "path_spectra": [list(spectrum) for spectrum in spectra],
        }
    ]
    for raw_base in (b"C~", b"EFz_", b"EUxo"):
        _, base = parse_graph6(raw_base)
        answer, covered, _, _, _, _ = solve_exact(catalog, base)
        if answer is not None or covered != 6 ** len(base):
            raise AssertionError((raw_base, answer, covered, 6 ** len(base)))
    print("HETEROGENEOUS_CSP_SELFTEST=PASS", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog")
    parser.add_argument("--base-file")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--witness-out")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.catalog or not args.base_file:
        parser.error("--catalog and --base-file are required outside --self-test")

    catalog_payload = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    raw_entries = (
        catalog_payload["candidates"]
        if isinstance(catalog_payload, dict) and "candidates" in catalog_payload
        else catalog_payload
    )
    catalog = deduplicate_catalog(raw_entries)

    bases = []
    with open(args.base_file, "rb") as handle:
        for raw in handle:
            if raw.strip():
                bases.append((raw.strip().decode("ascii"), parse_graph6(raw)[1]))

    domain_size = len(catalog) * 6
    stats = {
        "raw_catalog_entries": len(raw_entries),
        "distinct_spectrum_types": len(catalog),
        "domain_size": domain_size,
        "base_graphs": len(bases),
        "configurations_covered": 0,
        "search_nodes": 0,
        "constraints": 0,
        "spectrum_cache_entries": 0,
    }
    witness = None
    for base_graph6, base in bases:
        answer, covered, nodes, constraint_count, domains, cache_entries = solve_exact(
            catalog, base
        )
        stats["configurations_covered"] += covered
        stats["search_nodes"] += nodes
        stats["constraints"] += constraint_count
        stats["spectrum_cache_entries"] += cache_entries
        if answer is None:
            expected = domain_size ** len(base)
            if covered != expected:
                raise AssertionError(("incomplete accounting", base_graph6, covered, expected))
            continue

        choices = []
        for domain_index in answer:
            gadget_index, permutation = domains[domain_index]
            choices.append(
                {
                    "catalog_index": gadget_index,
                    "permutation": list(permutation),
                    "gadget": catalog[gadget_index],
                }
            )
        witness = {
            "kind": "heterogeneous_spectrum_wiring",
            "base_graph6": base_graph6,
            "choices": choices,
            "assembled_order": sum(
                int(choice["gadget"]["gadget_order"]) for choice in choices
            ),
        }
        break

    result = {"catalog": catalog, "stats": stats, "witness": witness}
    if witness is not None and args.witness_out:
        Path(args.witness_out).write_text(
            json.dumps(witness, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, sort_keys=True))
    return 10 if witness is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
