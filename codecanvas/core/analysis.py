"""CodeCanvas analysis.

Focus: impact analysis on an already-built `Graph`.

- Slice: blast radius via import/call edges
- Neighborhood: bounded k-hop subgraph for the impact view
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple

from .models import EdgeType, Graph, GraphEdge, GraphNode, NodeKind


@dataclass
class Slice:
    """
    Result of impact slice computation.

    Contains:
    - nodes: set of affected node IDs
    - edges: set of affected edge keys
    - target: the starting node ID
    - direction: 'in' (callers) or 'out' (callees)
    """

    nodes: Set[str]
    edges: Set[str]
    target: str
    direction: str  # 'in' or 'out'

    @property
    def affected_count(self) -> int:
        return len(self.nodes)


class Analyzer:
    """
    Code graph analyzer.

    Parser owns parsing and edge inference; Analyzer owns traversal.
    """

    def __init__(self, graph: Graph):
        self.graph = graph

    def compute_slice(
        self, start_id: str, direction: str = "out", include_imports: bool = True, include_calls: bool = True
    ) -> Slice:
        """
        Compute impact slice (blast radius) from a starting node.

        Ported from DepViz computeSlice + includeAncestors.

        Args:
            start_id: Node ID to start from
            direction: 'out' (what does this call?) or 'in' (what calls this?)
            include_imports: Include import edges
            include_calls: Include call edges

        Returns:
            Slice with affected nodes and edges
        """
        start_node = self.graph.get_node(start_id)
        if not start_node:
            return Slice(nodes=set(), edges=set(), target=start_id, direction=direction)

        # Seed: classes have no edges, start from their methods
        seed = {start_id}
        if start_node.kind == NodeKind.CLASS:
            for child in self.graph.get_children(start_id):
                if child.kind == NodeKind.FUNC:
                    seed.add(child.id)

        seen = set(seed)
        edge_set: Set[str] = set()
        queue: deque[str] = deque(seed)

        while queue:
            node_id = queue.popleft()

            edges = self.graph.get_edges_from(node_id) if direction == "out" else self.graph.get_edges_to(node_id)

            for edge in edges:
                # Filter by edge type
                if edge.type == EdgeType.IMPORT and not include_imports:
                    continue
                if edge.type == EdgeType.CALL and not include_calls:
                    continue

                # Get neighbor
                neighbor = edge.to_id if direction == "out" else edge.from_id

                # Check neighbor exists
                if not self.graph.get_node(neighbor):
                    continue

                edge_set.add(edge.key())

                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)

        # Include ancestors (func → class → module)
        self._include_ancestors(seen)

        return Slice(nodes=seen, edges=edge_set, target=start_id, direction=direction)

    def _include_ancestors(self, node_set: Set[str]):
        """
        Include ancestor nodes (DepViz includeAncestors).

        func → class → module
        class → module
        """
        to_add = []

        for node_id in list(node_set):
            node = self.graph.get_node(node_id)
            if not node:
                continue

            if node.kind == NodeKind.FUNC:
                if node.parent is None:
                    continue

                parent = self.graph.get_node(node.parent)
                if parent:
                    if parent.kind == NodeKind.CLASS:
                        to_add.append(parent.id)
                        if parent.parent is None:
                            continue
                        grandparent = self.graph.get_node(parent.parent)
                        if grandparent and grandparent.kind == NodeKind.MODULE:
                            to_add.append(grandparent.id)
                    elif parent.kind == NodeKind.MODULE:
                        to_add.append(parent.id)

            elif node.kind == NodeKind.CLASS:
                if node.parent is None:
                    continue

                parent = self.graph.get_node(node.parent)
                if parent and parent.kind == NodeKind.MODULE:
                    to_add.append(parent.id)

        node_set.update(to_add)

    def neighborhood(self, node_id: str, hops: int = 1, max_nodes: int = 20) -> Tuple[List[GraphNode], List[GraphEdge]]:
        """
        Extract k-hop neighborhood subgraph around a node.

        Used for focused impact visualization (max 20 nodes).

        Args:
            node_id: Center node ID
            hops: Number of hops to include (default 1)
            max_nodes: Maximum nodes to return (default 20)

        Returns:
            Tuple of (nodes, edges) for the neighborhood
        """
        center = self.graph.get_node(node_id)
        if not center:
            return [], []

        # BFS to collect nodes within k hops
        visited = {node_id}
        frontier = {node_id}

        for _ in range(hops):
            next_frontier = set()
            for nid in frontier:
                # Outgoing edges (what this calls)
                for edge in self.graph.get_edges_from(nid):
                    if edge.to_id not in visited:
                        visited.add(edge.to_id)
                        next_frontier.add(edge.to_id)

                # Incoming edges (what calls this)
                for edge in self.graph.get_edges_to(nid):
                    if edge.from_id not in visited:
                        visited.add(edge.from_id)
                        next_frontier.add(edge.from_id)

            frontier = next_frontier

            # Stop if we've hit max_nodes
            if len(visited) >= max_nodes:
                break

        # Include ancestors (class, module) for context
        to_add = set()
        for nid in visited:
            node = self.graph.get_node(nid)
            if node and node.parent:
                parent = self.graph.get_node(node.parent)
                if parent:
                    to_add.add(parent.id)
                    if parent.parent:
                        grandparent = self.graph.get_node(parent.parent)
                        if grandparent:
                            to_add.add(grandparent.id)

        visited.update(to_add)

        # Cap at max_nodes, prioritizing center node
        if len(visited) > max_nodes:
            # Keep center, then closest nodes
            visited_list = [node_id] + [v for v in visited if v != node_id]
            visited = set(visited_list[:max_nodes])

        # Collect nodes and edges
        nodes: List[GraphNode] = []
        for nid in visited:
            node = self.graph.get_node(nid)
            if node is not None:
                nodes.append(node)
        edges = [e for e in self.graph.edges if e.from_id in visited and e.to_id in visited]

        return nodes, edges

    def find_target(self, query: str) -> Optional[GraphNode]:
        """
        Find a node by name or ID.

        Tries:
        1. Exact ID match
        2. Exact label match
        3. Partial label match (contains)
        """
        # Exact ID
        node = self.graph.get_node(query)
        if node:
            return node

        # Exact label
        for n in self.graph.nodes:
            if n.label == query:
                return n

        # Partial match
        query_lower = query.lower()
        for n in self.graph.nodes:
            if query_lower in n.label.lower():
                return n

        return None

    def analyze(self, target: str, depth: int = 2) -> Optional[Tuple[Slice, Slice]]:
        """
        Full impact analysis for a target.

        Returns:
            Tuple of (inbound_slice, outbound_slice) or None if target not found
        """
        node = self.find_target(target)
        if not node:
            return None

        inbound = self.compute_slice(node.id, "in")
        outbound = self.compute_slice(node.id, "out")

        return inbound, outbound

    def find_similar_symbols(self, query: str, limit: int = 5) -> List[GraphNode]:
        """
        Fuzzy symbol search for error recovery.

        Scoring: exact substring > prefix > character overlap.
        Filters: skip MODULE nodes, return funcs/classes only.

        Args:
            query: Symbol name to search for
            limit: Max results to return

        Returns:
            List of GraphNode matches sorted by relevance
        """
        if not query:
            return []

        query_lower = query.lower()
        candidates: List[Tuple[int, GraphNode]] = []

        for node in self.graph.nodes:
            if node.kind == NodeKind.MODULE:
                continue

            label_lower = node.label.lower()
            score = 0

            if query_lower == label_lower:
                score = 100
            elif query_lower in label_lower:
                score = 80
            elif label_lower.startswith(query_lower):
                score = 70
            elif query_lower.startswith(label_lower):
                score = 60
            else:
                overlap = sum(1 for c in query_lower if c in label_lower)
                if overlap > len(query_lower) // 2:
                    score = 30 + overlap

            if score > 0:
                candidates.append((score, node))

        candidates.sort(key=lambda x: (-x[0], x[1].label))
        return [node for _, node in candidates[:limit]]
