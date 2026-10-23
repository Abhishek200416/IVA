"""Starter implementation of topo_sorter.py."""
import heapq
from typing import List, Tuple


def lexicographical_topological_sort(nodes: List[str], edges: List[Tuple[str, str]]) -> List[str]:
    in_deg = {n: 0 for n in nodes}
    adj = {n: [] for n in nodes}
    seen_edges = set()

    for u, v in edges:
        if u not in in_deg or v not in in_deg:
            raise ValueError(f"Unknown node in edge: ({u}, {v})")
        if (u, v) not in seen_edges:
            seen_edges.add((u, v))
            adj[u].append(v)
            in_deg[v] += 1

    ready = [n for n in in_deg if in_deg[n] == 0]
    heapq.heapify(ready)

    order: List[str] = []
    while ready:
        cur = heapq.heappop(ready)
        order.append(cur)
        for nxt in adj[cur]:
            in_deg[nxt] -= 1
            if in_deg[nxt] == 0:
                heapq.heappush(ready, nxt)

    if len(order) != len(in_deg):
        raise ValueError("Graph contains a cycle")

    return order
