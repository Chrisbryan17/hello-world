#!/usr/bin/env python3
"""Independent verifier for a three-terminal odd-multiplier gadget witness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterator


def iter_bits(mask: int) -> Iterator[int]:
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def graph_from_edges(order: int, listed: list[list[int]]) -> tuple[int, ...]:
    graph = [0] * order
    seen: set[tuple[int, int]] = set()
    for raw_first, raw_second in listed:
        first, second = sorted((int(raw_first), int(raw_second)))
        assert 0 <= first < second < order
        assert (first, second) not in seen
        seen.add((first, second))
        graph[first] |= 1 << second
        graph[second] |= 1 << first
    return tuple(graph)


def connected(graph: tuple[int, ...]) -> bool:
    seen = 1
    frontier = 1
    while frontier:
        bit = frontier & -frontier
        frontier ^= bit
        vertex = bit.bit_length() - 1
        new = graph[vertex] & ~seen
        seen |= new
        frontier |= new
    return seen.bit_count() == len(graph)


def first_cycle(graph: tuple[int, ...], length: int) -> tuple[int, ...] | None:
    order = len(graph)
    path = [0] * length
    for start in range(order):
        path[0] = start
        for first in iter_bits(graph[start] & ~((1 << (start + 1)) - 1)):
            path[1] = first

            def dfs(depth: int, current: int, used: int) -> tuple[int, ...] | None:
                if depth == length:
                    if ((graph[current] >> start) & 1) and path[1] < path[-1]:
                        return tuple(path)
                    return None
                candidates = graph[current] & ~used & ~((1 << (start + 1)) - 1)
                if depth == length - 1:
                    candidates &= graph[start]
                for nxt in iter_bits(candidates):
                    path[depth] = nxt
                    answer = dfs(depth + 1, nxt, used | (1 << nxt))
                    if answer is not None:
                        return answer
                return None

            answer = dfs(2, first, (1 << start) | (1 << first))
            if answer is not None:
                return answer
    return None


def check_powers(graph: tuple[int, ...]) -> list[int]:
    checked=[]
    power=4
    while power<=len(graph):
        cycle=first_cycle(graph,power)
        checked.append(power)
        if cycle is not None:
            raise AssertionError(f"forbidden C_{power}: {cycle}")
        power*=2
    return checked


def all_terminal_paths_good(
    graph: tuple[int, ...], terminals: tuple[int,int,int], modulus: int
) -> tuple[bool,int]:
    count=0
    order=len(graph)
    path=[0]*order
    for start,target in ((terminals[0],terminals[1]),
                         (terminals[0],terminals[2]),
                         (terminals[1],terminals[2])):
        path[0]=start
        def dfs(depth:int,current:int,used:int)->bool:
            nonlocal count
            if current==target:
                count+=1
                length=depth-1
                if (length+1)%modulus!=0:
                    raise AssertionError(
                        f"bad terminal path length {length}: {tuple(path[:depth])}"
                    )
                return True
            for neighbor in iter_bits(graph[current]&~used):
                path[depth]=neighbor
                dfs(depth+1,neighbor,used|(1<<neighbor))
            return True
        dfs(1,start,1<<start)
    return True,count


def add_edge(graph:list[int],first:int,second:int)->None:
    assert first!=second and not ((graph[first]>>second)&1)
    graph[first]|=1<<second
    graph[second]|=1<<first


def replace_k4(gadget:tuple[int,...],terminals:tuple[int,int,int])->tuple[int,...]:
    size=len(gadget)
    graph=[0]*(4*size)
    for copy in range(4):
        offset=copy*size
        for vertex,neighbors in enumerate(gadget):
            for neighbor in iter_bits(neighbors):
                if vertex<neighbor:
                    add_edge(graph,offset+vertex,offset+neighbor)
    neighbor_lists={vertex:[other for other in range(4) if other!=vertex] for vertex in range(4)}
    terminal_for={
        (vertex,other):terminals[neighbor_lists[vertex].index(other)]
        for vertex in range(4) for other in neighbor_lists[vertex]
    }
    for first in range(4):
        for second in range(first+1,4):
            add_edge(
                graph,
                first*size+terminal_for[(first,second)],
                second*size+terminal_for[(second,first)],
            )
    return tuple(graph)


def verify(witness:dict)->dict:
    order=int(witness['order'])
    terminals=tuple(int(value) for value in witness['terminals'])
    modulus=int(witness['modulus'])
    assert len(terminals)==3 and len(set(terminals))==3
    assert modulus>1 and modulus%2==1
    gadget=graph_from_edges(order,witness['edges'])
    degrees=[neighbors.bit_count() for neighbors in gadget]
    assert connected(gadget)
    assert all(degrees[vertex]==2 for vertex in terminals)
    assert all(degree==3 for vertex,degree in enumerate(degrees) if vertex not in terminals)
    gadget_checked=check_powers(gadget)
    _,path_count=all_terminal_paths_good(gadget,terminals,modulus)
    assert path_count>0

    counterexample=replace_k4(gadget,terminals)
    assert connected(counterexample)
    assert all(neighbors.bit_count()==3 for neighbors in counterexample)
    counterexample_checked=check_powers(counterexample)
    return {
        'verified':True,
        'gadget_order':order,
        'modulus':modulus,
        'terminal_paths_checked':path_count,
        'gadget_power_lengths_checked':gadget_checked,
        'counterexample_order':len(counterexample),
        'counterexample_regular_degree':3,
        'counterexample_power_lengths_checked':counterexample_checked,
    }


def main()->int:
    parser=argparse.ArgumentParser()
    parser.add_argument('witness')
    parser.add_argument('--output')
    args=parser.parse_args()
    result=verify(json.loads(Path(args.witness).read_text(encoding='utf-8')))
    text=json.dumps(result,indent=2,sort_keys=True)+'\n'
    if args.output:
        Path(args.output).write_text(text,encoding='utf-8')
    print(text,end='')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
