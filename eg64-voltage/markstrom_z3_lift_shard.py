#!/usr/bin/env python3
"""Exhaust one shard of normalized Z3 lifts of a public order-24 extremal graph."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from cyclic_lift_census import (
    connected,
    cyclic_lift,
    edge_list,
    first_power_cycle,
    lift_edges,
    spanning_tree_and_cotree,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eg64-surgery"))
from markstrom_gadget_surgery import (  # noqa: E402
    canonical_fingerprint,
    first_cycle,
    parse_matrix,
)


def load_bases(directory: Path) -> list[tuple[str, tuple[int, ...]]]:
    bases=[]
    seen=set()
    for path in sorted(directory.rglob("*.txt")):
        try:
            graph=parse_matrix(path)
        except Exception:
            continue
        if len(graph)!=24 or any(mask.bit_count()!=3 for mask in graph):
            continue
        if not connected(graph):
            continue
        if first_cycle(graph,4) is not None or first_cycle(graph,8) is not None:
            continue
        fingerprint=canonical_fingerprint(graph)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        bases.append((path.name,graph))
    if len(bases)!=4:
        raise AssertionError(f"expected four extremal bases, found {len(bases)}")
    return bases


def decode_base3(number: int, width: int) -> tuple[int,...]:
    digits=[]
    for _ in range(width):
        digits.append(number%3)
        number//=3
    if number:
        raise AssertionError("assignment integer exceeded width")
    return tuple(digits)


@dataclass
class Stats:
    base_index: int
    base_file: str
    shard: int
    modulus_shards: int
    assignment_space: int
    assignments_visited: int=0
    connected_lifts: int=0
    rejected_by_length: dict[str,int]|None=None
    elapsed_seconds: float=0.0


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--special-dir",required=True)
    parser.add_argument("--base-index",type=int,required=True)
    parser.add_argument("--shard",type=int,required=True)
    parser.add_argument("--shards",type=int,required=True)
    parser.add_argument("--result",required=True)
    parser.add_argument("--witness-out",required=True)
    args=parser.parse_args()

    if not (0<=args.shard<args.shards):
        raise ValueError("invalid shard")
    bases=load_bases(Path(args.special_dir))
    if not (0<=args.base_index<len(bases)):
        raise ValueError("invalid base index")
    base_file,base=bases[args.base_index]
    tree,cotree=spanning_tree_and_cotree(base)
    if len(cotree)!=13:
        raise AssertionError(f"expected cycle rank 13, found {len(cotree)}")
    assignment_space=3**len(cotree)
    stats=Stats(
        base_index=args.base_index,
        base_file=base_file,
        shard=args.shard,
        modulus_shards=args.shards,
        assignment_space=assignment_space,
        rejected_by_length={},
    )
    start=time.monotonic()
    witness=None
    for encoded in range(args.shard,assignment_space,args.shards):
        stats.assignments_visited+=1
        if encoded==0:
            continue
        assignment=decode_base3(encoded,len(cotree))
        lift=cyclic_lift(base,3,cotree,assignment)
        if not connected(lift):
            raise AssertionError("nonzero Z3 assignment produced disconnected lift")
        if any(mask.bit_count()!=3 for mask in lift):
            raise AssertionError("lift is not cubic")
        stats.connected_lifts+=1
        forbidden=first_power_cycle(lift)
        if forbidden is None:
            witness={
                "kind":"markstrom_z3_voltage_lift",
                "base_file":base_file,
                "base_index":args.base_index,
                "tree_edges":[list(edge) for edge in tree],
                "cotree_edges":[list(edge) for edge in cotree],
                "cotree_voltages":list(assignment),
                "encoded_assignment":encoded,
                "order":len(lift),
                "edges":lift_edges(lift),
            }
            Path(args.witness_out).write_text(json.dumps(witness,indent=2,sort_keys=True)+"\n")
            break
        key=str(forbidden[0])
        stats.rejected_by_length[key]=stats.rejected_by_length.get(key,0)+1
    stats.elapsed_seconds=time.monotonic()-start
    payload={
        "status":"witness" if witness else "exhausted",
        "stats":asdict(stats),
        "witness":witness,
    }
    Path(args.result).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps(payload,sort_keys=True))
    return 10 if witness else 0


if __name__=="__main__":
    raise SystemExit(main())
