#!/usr/bin/env python3
"""Exhaust the zero-size vertex surgery on the four order-24 extremal graphs.

Delete a cubic vertex v, join one pair of its former neighbors, and leave the
third neighbor as the unique degree-2 terminal. This produces an order-23 cap.
All 24*3 choices on each public extremal graph are checked exactly.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eg64-surgery"))
from markstrom_gadget_surgery import (  # noqa: E402
    add_edge,
    canonical_fingerprint,
    connected,
    edges,
    first_cycle,
    first_power_cycle,
    graph6,
    iter_bits,
    parse_matrix,
    validate_cap,
)


@dataclass
class Stats:
    base_files_seen: int = 0
    base_graphs: int = 0
    surgeries: int = 0
    skipped_existing_edge: int = 0
    rejected_c4: int = 0
    rejected_c8: int = 0
    rejected_c16: int = 0


def load_bases(directory: Path, stats: Stats) -> list[tuple[str, tuple[int, ...]]]:
    bases=[]
    seen=set()
    for path in sorted(directory.rglob("*.txt")):
        stats.base_files_seen += 1
        try:
            graph=parse_matrix(path)
        except Exception:
            continue
        if len(graph)!=24 or any(mask.bit_count()!=3 for mask in graph) or not connected(graph):
            continue
        if first_cycle(graph,4) is not None or first_cycle(graph,8) is not None:
            continue
        fingerprint=canonical_fingerprint(graph)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        bases.append((path.name,graph))
    stats.base_graphs=len(bases)
    if len(bases)!=4:
        raise AssertionError(f"expected four public extremal graphs, found {len(bases)}")
    return bases


def surgery(base: tuple[int, ...], removed: int, joined: tuple[int,int]) -> tuple[int,...]:
    retained=[v for v in range(len(base)) if v!=removed]
    mapping={old:new for new,old in enumerate(retained)}
    output=[0]*(len(base)-1)
    for u in retained:
        for v in iter_bits(base[u]):
            if v==removed or u>=v:
                continue
            add_edge(output,mapping[u],mapping[v])
    add_edge(output,mapping[joined[0]],mapping[joined[1]])
    return tuple(output)


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--special-dir",required=True)
    parser.add_argument("--result",required=True)
    parser.add_argument("--witness-out",required=True)
    args=parser.parse_args()
    stats=Stats()
    bases=load_bases(Path(args.special_dir),stats)
    witness=None
    for base_name,base in bases:
        for removed in range(24):
            neighbors=sorted(iter_bits(base[removed]))
            for joined in itertools.combinations(neighbors,2):
                if (base[joined[0]]>>joined[1])&1:
                    stats.skipped_existing_edge += 1
                    continue
                stats.surgeries += 1
                cap=surgery(base,removed,joined)
                terminal=validate_cap(cap)
                forbidden=first_power_cycle(cap)
                if forbidden is None:
                    witness={
                        "kind":"delete_vertex_join_neighbor_pair",
                        "operation":"zero_vertex_replacement",
                        "base_file":base_name,
                        "removed_vertex":removed,
                        "joined_neighbors":list(joined),
                        "terminal":terminal,
                        "cap_order":len(cap),
                        "cap_graph6":graph6(cap),
                        "cap_edges":[list(edge) for edge in edges(cap)],
                        "doubled_counterexample_order":2*len(cap),
                        "stats":asdict(stats),
                    }
                    Path(args.witness_out).write_text(json.dumps(witness,indent=2,sort_keys=True)+"\n")
                    break
                length=forbidden[0]
                if length==4: stats.rejected_c4 += 1
                elif length==8: stats.rejected_c8 += 1
                elif length==16: stats.rejected_c16 += 1
                else: raise AssertionError(length)
            if witness: break
        if witness: break
    payload={
        "status":"witness" if witness else "exhausted",
        "base_graphs":[name for name,_ in bases],
        "stats":asdict(stats),
        "witness":witness,
    }
    Path(args.result).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps(payload,sort_keys=True))
    return 10 if witness else 0


if __name__=="__main__":
    raise SystemExit(main())
