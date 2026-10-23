"""Implementation of lexicographical topological sort and topological generations."""
from typing import Dict, List, Sequence, Set, Tuple
import heapq


def _build_graph(
    nodes: Sequence[str], edges: Sequence[Tuple[str, str]]
) -> Tuple[Set[str], Dict[str, List[str]], Dict[str, int]]:
    """Validate inputs, deduplicate nodes/edges, and construct graph structures."""
    node_set = set(nodes)
    adj: Dict[str, List[str]] = {n: [] for n in node_set}
    in_deg: Dict[str, int] = {n: 0 for n in node_set}

    # Validate endpoints and deduplicate edges
    unique_edges = set()
    for edge in edges:
        u, v = edge
        if u not in node_set or v not in node_set:
            raise ValueError(f"Edge ({u!r}, {v!r}) references node not in nodes list")
        unique_edges.add((u, v))

    for u, v in unique_edges:
        adj[u].append(v)
        in_deg[v] += 1

    return node_set, adj, in_deg


def lexicographical_topological_sort(
    nodes: Sequence[str], edges: Sequence[Tuple[str, str]]
) -> List[str]:
    """Perform a lexicographical topological sort on a directed acyclic graph (DAG).

    Args:
        nodes: Sequence of node identifiers.
        edges: Sequence of directed edges represented as (source, destination) pairs.

    Returns:
        A list of node identifiers in lexicographical topological order.

    Raises:
        ValueError: If an edge references a node not present in `nodes`,
                    or if the graph contains a cycle (including self-loops).
    """
    node_set, adj, in_deg = _build_graph(nodes, edges)

    # Min-heap ensures deterministic lexicographical tie-breaking
    ready = [n for n in node_set if in_deg[n] == 0]
    heapq.heapify(ready)

    order: List[str] = []
    while ready:
        cur = heapq.heappop(ready)
        order.append(cur)
        for nxt in adj[cur]:
            in_deg[nxt] -= 1
            if in_deg[nxt] == 0:
                heapq.heappush(ready, nxt)

    if len(order) != len(node_set):
        raise ValueError("Graph contains a cycle")

    return order


def topological_generations(
    nodes: Sequence[str], edges: Sequence[Tuple[str, str]]
) -> List[List[str]]:
    """Compute topological generations (parallel waves) of a directed acyclic graph (DAG).

    Each generation is the sorted wave of zero-in-degree nodes available at that step.

    Args:
        nodes: Sequence of node identifiers.
        edges: Sequence of directed edges represented as (source, destination) pairs.

    Returns:
        A list of waves, where each wave is a sorted list of node identifiers.

    Raises:
        ValueError: If an edge references a node not present in `nodes`,
                    or if the graph contains a cycle (including self-loops).
    """
    node_set, adj, in_deg = _build_graph(nodes, edges)

    current_gen = sorted(n for n in node_set if in_deg[n] == 0)
    generations: List[List[str]] = []
    visited_count = 0

    while current_gen:
        generations.append(current_gen)
        visited_count += len(current_gen)
        next_gen: List[str] = []
        for cur in current_gen:
            for nxt in adj[cur]:
                in_deg[nxt] -= 1
                if in_deg[nxt] == 0:
                    next_gen.append(nxt)
        current_gen = sorted(next_gen)

    if visited_count != len(node_set):
        raise ValueError("Graph contains a cycle")

    return generations
