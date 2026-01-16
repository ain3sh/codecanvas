from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


class NodeKind(str, Enum):
    """Node types produced/consumed by CodeCanvas."""

    MODULE = "module"
    CLASS = "class"
    FUNC = "func"


class EdgeType(str, Enum):
    """Edge types used by the current views and analysis."""

    IMPORT = "import"  # module -> module
    CALL = "call"  # func -> func
    CONTAINS = "contains"  # container (module|class) -> member (class|func)


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: NodeKind
    label: str
    fsPath: str
    snippet: Optional[str] = None
    start_line: Optional[int] = None
    start_char: Optional[int] = None
    end_line: Optional[int] = None
    end_char: Optional[int] = None


@dataclass
class GraphEdge:
    """
    An edge in the code graph.
    """

    from_id: str
    to_id: str
    type: EdgeType

    def key(self) -> str:
        """Unique key for deduplication."""
        return f"{self.from_id}->{self.to_id}:{self.type.value}"


@dataclass
class Graph:
    """
    Complete code graph.
    """

    nodes: List[GraphNode] = field(default_factory=list)
    edges: List[GraphEdge] = field(default_factory=list)

    # Indexes (crabviz-style for O(1) lookup)
    _node_map: Dict[str, GraphNode] = field(default_factory=dict, repr=False)
    _edges_from: Dict[str, List[GraphEdge]] = field(default_factory=dict, repr=False)
    _edges_to: Dict[str, List[GraphEdge]] = field(default_factory=dict, repr=False)
    _edge_keys: Set[str] = field(default_factory=set, repr=False)
    _contains_children: Dict[str, List[str]] = field(default_factory=dict, repr=False)
    _contains_parent: Dict[str, str] = field(default_factory=dict, repr=False)

    def rebuild_indexes(self) -> None:
        """Rebuild all indexes after modification."""
        self._node_map = {n.id: n for n in self.nodes}
        self._edges_from = {}
        self._edges_to = {}
        self._edge_keys = set()
        self._contains_children = {}
        self._contains_parent = {}

        for e in self.edges:
            if e.from_id not in self._edges_from:
                self._edges_from[e.from_id] = []
            self._edges_from[e.from_id].append(e)

            if e.to_id not in self._edges_to:
                self._edges_to[e.to_id] = []
            self._edges_to[e.to_id].append(e)

            self._edge_keys.add(e.key())

            if e.type == EdgeType.CONTAINS:
                existing = self._contains_parent.get(e.to_id)
                # Some parsers (notably tree-sitter for generated/Cython code) can
                # emit ambiguous containment relationships. Keep the first parent
                # and ignore subsequent conflicting parents rather than crashing.
                if existing is None:
                    self._contains_parent[e.to_id] = e.from_id
                    self._contains_children.setdefault(e.from_id, []).append(e.to_id)
                elif existing == e.from_id:
                    self._contains_children.setdefault(e.from_id, []).append(e.to_id)
                else:
                    continue

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get node by ID (O(1))."""
        return self._node_map.get(node_id)

    def get_edges_from(self, node_id: str) -> List[GraphEdge]:
        """Get outgoing edges (O(1))."""
        return self._edges_from.get(node_id, [])

    def get_edges_to(self, node_id: str) -> List[GraphEdge]:
        """Get incoming edges (O(1))."""
        return self._edges_to.get(node_id, [])

    def add_node(self, node: GraphNode) -> bool:
        """Add node if not exists. Returns True if added."""
        if node.id in self._node_map:
            return False
        self.nodes.append(node)
        self._node_map[node.id] = node
        return True

    def add_edge(self, edge: GraphEdge) -> bool:
        """Add edge if not duplicate. Returns True if added."""
        key = edge.key()
        if key in self._edge_keys:
            return False

        self.edges.append(edge)
        self._edge_keys.add(key)

        if edge.from_id not in self._edges_from:
            self._edges_from[edge.from_id] = []
        self._edges_from[edge.from_id].append(edge)

        if edge.to_id not in self._edges_to:
            self._edges_to[edge.to_id] = []
        self._edges_to[edge.to_id].append(edge)

        if edge.type == EdgeType.CONTAINS:
            existing = self._contains_parent.get(edge.to_id)
            if existing is None:
                self._contains_parent[edge.to_id] = edge.from_id
                self._contains_children.setdefault(edge.from_id, []).append(edge.to_id)
            elif existing == edge.from_id:
                self._contains_children.setdefault(edge.from_id, []).append(edge.to_id)
            else:
                return False

        return True

    def get_parent_id(self, node_id: str) -> Optional[str]:
        return self._contains_parent.get(node_id)

    def get_parent(self, node_id: str) -> Optional[GraphNode]:
        pid = self.get_parent_id(node_id)
        return None if pid is None else self.get_node(pid)

    def get_children_ids(self, parent_id: str) -> List[str]:
        return list(self._contains_children.get(parent_id, []))

    def get_children(self, parent_id: str) -> List[GraphNode]:
        out: List[GraphNode] = []
        for cid in self.get_children_ids(parent_id):
            n = self.get_node(cid)
            if n is not None:
                out.append(n)
        return out

    def stats(self) -> Dict[str, int]:
        """Return graph statistics."""
        return {
            "modules": sum(1 for n in self.nodes if n.kind == NodeKind.MODULE),
            "classes": sum(1 for n in self.nodes if n.kind == NodeKind.CLASS),
            "funcs": sum(1 for n in self.nodes if n.kind == NodeKind.FUNC),
            "import_edges": sum(1 for e in self.edges if e.type == EdgeType.IMPORT),
            "call_edges": sum(1 for e in self.edges if e.type == EdgeType.CALL),
            "contains_edges": sum(1 for e in self.edges if e.type == EdgeType.CONTAINS),
        }


# ID generation utilities (DepViz style)
def _hash(s: str) -> str:
    """FNV-1a hash for IDs."""
    h = 2166136261
    for c in s:
        h ^= ord(c)
        h = (h * 16777619) & 0xFFFFFFFF
    return format(h, "x")


def make_module_id(path: str) -> str:
    """Generate module ID from path."""
    return f"mod_{_hash(path)}"


def make_class_id(file_label: str, class_name: str) -> str:
    """Generate class ID."""
    return f"cls_{_hash(file_label)}_{class_name}"


def make_func_id(file_label: str, func_name: str, line: int) -> str:
    """Generate function ID."""
    return f"fn_{_hash(file_label)}_{func_name}_{line}"
