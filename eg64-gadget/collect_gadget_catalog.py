#!/usr/bin/env python3
"""Collect every cubic vertex-deletion gadget surviving the internal-cycle test."""
from __future__ import annotations

import argparse
import json
import sys

from spectrum_wiring_search import (
    delete_vertex,
    first_forbidden_power,
    iter_bits,
    parse_graph6,
    power_cycle_vertex_intersection,
    terminal_path_spectra,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order", type=int, required=True)
    parser.add_argument("--expected-sources", type=int, required=True)
    parser.add_argument("--expected-candidates", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source_count = 0
    candidates = []
    for raw in sys.stdin.buffer:
        if not raw.strip():
            continue
        order, source = parse_graph6(raw)
        if order != args.order:
            raise ValueError(f"expected source order {args.order}, received {order}")
        source_count += 1
        saw_cycle, intersection = power_cycle_vertex_intersection(source)
        if not saw_cycle:
            raise AssertionError("a source graph is already a counterexample")
        for deleted_vertex in iter_bits(intersection):
            gadget, terminals = delete_vertex(source, deleted_vertex)
            if first_forbidden_power(gadget) is not None:
                raise AssertionError("candidate gadget retained a forbidden internal cycle")
            spectra = terminal_path_spectra(gadget, terminals)
            candidates.append(
                {
                    "source_graph6": raw.strip().decode("ascii"),
                    "source_order": order,
                    "deleted_vertex": deleted_vertex,
                    "gadget_order": len(gadget),
                    "terminals": list(terminals),
                    "path_spectra": [list(spectrum) for spectrum in spectra],
                }
            )

    if source_count != args.expected_sources:
        raise AssertionError(("source count", source_count, args.expected_sources))
    if len(candidates) != args.expected_candidates:
        raise AssertionError(("candidate count", len(candidates), args.expected_candidates))
    result = {
        "source_order": args.order,
        "source_graphs": source_count,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({
        "source_order": args.order,
        "source_graphs": source_count,
        "candidate_count": len(candidates),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
