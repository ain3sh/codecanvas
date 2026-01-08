"""CodeCanvas analysis.

Focus: impact analysis on an already-built `Graph`.

- Slice: blast radius via import/call edges
- Neighborhood: bounded k-hop subgraph for the impact view
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

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

        allowed: Set[EdgeType] = set()
        if include_calls:
            allowed.add(EdgeType.CALL)
        if include_imports:
            allowed.add(EdgeType.IMPORT)

        seed = {start_id}
        if start_node.kind in {NodeKind.CLASS, NodeKind.MODULE}:
            seed.update(self.descendant_funcs(start_id))

        seen = set(seed)
        edge_set: Set[str] = set()
        queue: deque[str] = deque(seed)

        while queue:
            node_id = queue.popleft()

            edges = self.graph.get_edges_from(node_id) if direction == "out" else self.graph.get_edges_to(node_id)

            for edge in edges:
                if edge.type not in allowed:
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

        self._include_ancestors(seen)

        return Slice(nodes=seen, edges=edge_set, target=start_id, direction=direction)

    def _include_ancestors(self, node_set: Set[str]):
        to_add: Set[str] = set()

        for node_id in list(node_set):
            parent_id = self.graph.get_parent_id(node_id)
            while parent_id is not None:
                if parent_id in node_set:
                    break
                to_add.add(parent_id)
                parent_id = self.graph.get_parent_id(parent_id)

        node_set.update(to_add)

    def descendant_funcs(self, node_id: str) -> Set[str]:
        """Return all descendant FUNC nodes via CONTAINS edges."""
        out: Set[str] = set()
        queue: deque[str] = deque([node_id])
        seen: Set[str] = {node_id}

        while queue:
            cur = queue.popleft()
            for child_id in self.graph.get_children_ids(cur):
                if child_id in seen:
                    continue
                seen.add(child_id)
                child = self.graph.get_node(child_id)
                if child is None:
                    continue
                if child.kind == NodeKind.FUNC:
                    out.add(child.id)
                elif child.kind in {NodeKind.CLASS, NodeKind.MODULE}:
                    queue.append(child.id)

        return out

    def impact_call_counts(self, target_id: str) -> Tuple[Dict[str, int], Dict[str, int]]:
        """Compute aggregated callers/callees for impact rendering."""
        target = self.graph.get_node(target_id)
        if target is None:
            return {}, {}

        if target.kind == NodeKind.FUNC:
            target_funcs = {target_id}
        elif target.kind in {NodeKind.CLASS, NodeKind.MODULE}:
            target_funcs = self.descendant_funcs(target_id)
        else:
            target_funcs = set()

        if not target_funcs:
            return {}, {}

        callers: Dict[str, int] = {}
        callees: Dict[str, int] = {}

        for fid in target_funcs:
            for e in self.graph.get_edges_to(fid):
                if e.type != EdgeType.CALL:
                    continue
                did = self._impact_display_id(e.from_id, center=target)
                if did != target_id:
                    callers[did] = callers.get(did, 0) + 1

            for e in self.graph.get_edges_from(fid):
                if e.type != EdgeType.CALL:
                    continue
                did = self._impact_display_id(e.to_id, center=target)
                if did != target_id:
                    callees[did] = callees.get(did, 0) + 1

        return callers, callees

    def _impact_display_id(self, node_id: str, *, center: GraphNode) -> str:
        if center.kind == NodeKind.FUNC:
            return node_id
        if center.kind == NodeKind.MODULE:
            return self._nearest_ancestor_id(node_id, kind=NodeKind.MODULE) or node_id

        # center.kind == CLASS
        cid = self._nearest_ancestor_id(node_id, kind=NodeKind.CLASS)
        if cid is not None:
            return cid
        mid = self._nearest_ancestor_id(node_id, kind=NodeKind.MODULE)
        return mid or node_id

    def _nearest_ancestor_id(self, node_id: str, *, kind: NodeKind) -> str | None:
        cur = node_id
        while True:
            pid = self.graph.get_parent_id(cur)
            if pid is None:
                return None
            pnode = self.graph.get_node(pid)
            if pnode is not None and pnode.kind == kind:
                return pid
            cur = pid

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

        seed: Set[str] = {node_id}
        if center.kind in {NodeKind.CLASS, NodeKind.MODULE}:
            seed.update(self.descendant_funcs(node_id))

        visited = set(seed)
        frontier = set(seed)

        for _ in range(hops):
            next_frontier = set()
            for nid in frontier:
                for edge in self.graph.get_edges_from(nid):
                    if edge.type != EdgeType.CALL:
                        continue
                    if edge.to_id not in visited:
                        visited.add(edge.to_id)
                        next_frontier.add(edge.to_id)

                for edge in self.graph.get_edges_to(nid):
                    if edge.type != EdgeType.CALL:
                        continue
                    if edge.from_id not in visited:
                        visited.add(edge.from_id)
                        next_frontier.add(edge.from_id)

            frontier = next_frontier

            # Stop if we've hit max_nodes
            if len(visited) >= max_nodes:
                break

        self._include_ancestors(visited)

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

        def _score(n: GraphNode) -> tuple[int, int, int, int, int]:
            kind_score = {
                NodeKind.FUNC: 300,
                NodeKind.CLASS: 200,
                NodeKind.MODULE: 100,
            }.get(n.kind, 0)

            degree = len(self.graph.get_edges_from(n.id)) + len(self.graph.get_edges_to(n.id))
            child_count = len(self.graph.get_children(n.id))

            suffix = Path(n.fsPath).suffix.lower()
            header_suffixes = {".h", ".hh", ".hpp", ".hxx"}
            ext_score = 0 if suffix in header_suffixes else 1

            has_range = 1 if (n.start_line is not None and n.end_line is not None) else 0
            return (kind_score, degree, child_count, ext_score, has_range)

        # Exact label
        exact = [n for n in self.graph.nodes if n.label == query]
        if exact:
            return max(exact, key=_score)

        # Partial match
        query_lower = query.lower()
        partial = [n for n in self.graph.nodes if query_lower in n.label.lower()]
        if partial:
            return max(partial, key=_score)

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
