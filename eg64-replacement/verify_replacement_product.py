#!/usr/bin/env python3
"""Independent verifier for a cubic replacement-product witness."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def decode(text: str) -> list[set[int]]:
    data=text.strip(); values=[ord(char)-63 for char in data]
    if not values or values[0]>62: raise ValueError('unsupported graph6')
    n=values[0]; bits=[]
    for value in values[1:]: bits += [(value>>shift)&1 for shift in range(5,-1,-1)]
    graph=[set() for _ in range(n)]; index=0
    for high in range(1,n):
        for low in range(high):
            if bits[index]: graph[low].add(high); graph[high].add(low)
            index+=1
    return graph


def delete_vertex(base: list[set[int]], deleted: int) -> tuple[list[set[int]], list[int]]:
    retained=[v for v in range(len(base)) if v!=deleted]
    index={old:new for new,old in enumerate(retained)}
    gadget=[set() for _ in retained]
    for old in retained:
        for neighbor in base[old]:
            if neighbor!=deleted: gadget[index[old]].add(index[neighbor])
    terminals=[index[v] for v in sorted(base[deleted])]
    return gadget,terminals


def build(witness: dict) -> list[set[int]]:
    base=decode(witness['gadget_base_graph6'])
    host=decode(witness['host_graph6'])
    gadget,terminals=delete_vertex(base,int(witness['deleted_vertex']))
    if terminals!=list(map(int,witness['gadget_terminals'])):
        raise AssertionError('terminal labels do not match')
    assignments=[tuple(map(int,row)) for row in witness['port_assignments']]
    if len(assignments)!=len(host) or any(sorted(row)!=[0,1,2] for row in assignments):
        raise AssertionError('invalid port assignment')
    size=len(gadget); graph=[set() for _ in range(size*len(host))]
    for copy in range(len(host)):
        for u,neighbors in enumerate(gadget):
            for v in neighbors: graph[copy*size+u].add(copy*size+v)
    neighbor_rows=[sorted(row) for row in host]
    positions=[{neighbor:i for i,neighbor in enumerate(row)} for row in neighbor_rows]
    for left in range(len(host)):
        for right in host[left]:
            if left>=right: continue
            lp=assignments[left][positions[left][right]]
            rp=assignments[right][positions[right][left]]
            u=left*size+terminals[lp]; v=right*size+terminals[rp]
            if u==v or v in graph[u]: raise AssertionError('product is not simple')
            graph[u].add(v); graph[v].add(u)
    return graph


def connected(graph: list[set[int]]) -> bool:
    seen={0}; stack=[0]
    while stack:
        u=stack.pop()
        for v in graph[u]:
            if v not in seen: seen.add(v); stack.append(v)
    return len(seen)==len(graph)


def digest(graph: list[set[int]]) -> str:
    value=hashlib.sha256()
    for u,row in enumerate(graph):
        for v in sorted(row):
            if u<v: value.update(f'{u},{v}\n'.encode())
    return value.hexdigest()


def first_cycle(graph: list[set[int]], length: int) -> list[int] | None:
    path=[-1]*length
    for start in range(len(graph)):
        path[0]=start
        for first in sorted(v for v in graph[start] if v>start):
            path[1]=first; used={start,first}
            def dfs(depth,current):
                if depth==length:
                    return path.copy() if start in graph[current] and path[1]<path[-1] else None
                for nxt in sorted(graph[current]):
                    if nxt<=start or nxt in used: continue
                    if depth==length-1 and start not in graph[nxt]: continue
                    path[depth]=nxt; used.add(nxt)
                    answer=dfs(depth+1,nxt)
                    if answer is not None: return answer
                    used.remove(nxt)
                return None
            answer=dfs(2,first)
            if answer is not None: return answer
    return None


def verify(witness: dict) -> dict:
    graph=build(witness)
    if len(graph)!=int(witness['order']): raise AssertionError('order mismatch')
    if any(len(row)!=3 for row in graph): raise AssertionError('not cubic')
    if not connected(graph): raise AssertionError('not connected')
    actual=digest(graph)
    if actual!=witness['adjacency_sha256']: raise AssertionError('digest mismatch')
    checked=[]; power=4
    while power<=len(graph):
        cycle=first_cycle(graph,power); checked.append(power)
        if cycle is not None: raise AssertionError(f'C_{power} found: {cycle}')
        power*=2
    return {'verified':True,'order':len(graph),'minimum_degree':3,'power_lengths_checked':checked,'adjacency_sha256':actual}


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument('witness'); parser.add_argument('--output'); args=parser.parse_args()
    result=verify(json.loads(Path(args.witness).read_text()))
    text=json.dumps(result,indent=2,sort_keys=True)+'\n'
    if args.output: Path(args.output).write_text(text)
    print(text,end=''); return 0

if __name__=='__main__': raise SystemExit(main())
