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

    occurrences = [0] * len(base)
    for constraint in constraints:
        for vertex, _, _ in constraint:
            occurrences[vertex] += 1
    variable_order = tuple(
        sorted(range(len(base)), key=lambda vertex: (-occurrences[vertex], vertex))
    )
    position = {vertex: index for index, vertex in enumerate(variable_order)}
    triggered = [[] for _ in variable_order]
    for constraint in constraints:
        triggered[max(position[vertex] for vertex, _, _ in constraint)].append(
            constraint
        )

    maximum_order = max(int(gadget["gadget_order"]) for gadget in catalog) * len(base)
    powers = set()
    power = 4
    while power <= maximum_order:
        powers.add(power)
        power *= 2

    spectrum_cache: dict[tuple[int, ...], bool] = {}
    assignments: list[int | None] = [None] * len(base)
    covered_configurations = 0
    search_nodes = 0

    def constraint_is_forbidden(
        constraint: tuple[tuple[int, int, int], ...]
    ) -> bool:
        key = []
        for vertex, first_slot, second_slot in constraint:
            domain_index = assignments[vertex]
            if domain_index is None:
                raise AssertionError("constraint evaluated before all variables were assigned")
            pair_index = slot_pair_index(first_slot, second_slot)
            key.append(pair_spectrum_ids[domain_index][pair_index])
        cache_key = tuple(sorted(key))
        if cache_key not in spectrum_cache:
            possible_lengths = {0}
            for spectrum_index in cache_key:
                possible_lengths = {
                    partial + contribution
                    for partial in possible_lengths
                    for contribution in spectra[spectrum_index]
                }
            spectrum_cache[cache_key] = bool(possible_lengths & powers)
        return spectrum_cache[cache_key]

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
                constraint_is_forbidden(constraint)
                for constraint in triggered[depth]
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
        len(spectrum_cache),
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
