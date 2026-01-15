from __future__ import annotations

from codecanvas.core.analysis import Analyzer
from codecanvas.core.models import EdgeType, Graph, GraphEdge, GraphNode, NodeKind


def test_find_target_prefers_symbol_with_edges() -> None:
    g = Graph()

    mod = GraphNode(id="mod_a", kind=NodeKind.MODULE, label="a", fsPath="/tmp/a.h")
    decl = GraphNode(id="fn_decl", kind=NodeKind.FUNC, label="foo", fsPath="/tmp/a.h", start_line=0, end_line=0)
    defin = GraphNode(id="fn_def", kind=NodeKind.FUNC, label="foo", fsPath="/tmp/a.cpp", start_line=0, end_line=0)
    caller = GraphNode(
        id="fn_caller",
        kind=NodeKind.FUNC,
        label="caller",
        fsPath="/tmp/a.cpp",
        start_line=1,
        end_line=1,
    )

    g.add_node(mod)
    g.add_node(decl)
    g.add_node(defin)
    g.add_node(caller)
    g.add_edge(GraphEdge(from_id=mod.id, to_id=decl.id, type=EdgeType.CONTAINS))
    g.add_edge(GraphEdge(from_id=mod.id, to_id=defin.id, type=EdgeType.CONTAINS))
    g.add_edge(GraphEdge(from_id=mod.id, to_id=caller.id, type=EdgeType.CONTAINS))
    g.add_edge(GraphEdge(from_id=caller.id, to_id=defin.id, type=EdgeType.CALL))

    a = Analyzer(g)
    target = a.find_target("foo")
    assert target is not None
    assert target.id == defin.id


def test_impact_call_counts_aggregates_class_methods() -> None:
    g = Graph()

    mod = GraphNode(id="mod_a", kind=NodeKind.MODULE, label="a", fsPath="/tmp/a.cpp")
    cls = GraphNode(id="cls_c", kind=NodeKind.CLASS, label="C", fsPath="/tmp/a.cpp")
    method = GraphNode(id="fn_m", kind=NodeKind.FUNC, label="C.m", fsPath="/tmp/a.cpp", start_line=0, end_line=0)
    other_cls = GraphNode(id="cls_d", kind=NodeKind.CLASS, label="D", fsPath="/tmp/a.cpp")
    other_method = GraphNode(
        id="fn_d",
        kind=NodeKind.FUNC,
        label="D.d",
        fsPath="/tmp/a.cpp",
        start_line=5,
        end_line=5,
    )

    g.add_node(mod)
    g.add_node(cls)
    g.add_node(method)
    g.add_node(other_cls)
    g.add_node(other_method)

    g.add_edge(GraphEdge(from_id=mod.id, to_id=cls.id, type=EdgeType.CONTAINS))
    g.add_edge(GraphEdge(from_id=cls.id, to_id=method.id, type=EdgeType.CONTAINS))
    g.add_edge(GraphEdge(from_id=mod.id, to_id=other_cls.id, type=EdgeType.CONTAINS))
    g.add_edge(GraphEdge(from_id=other_cls.id, to_id=other_method.id, type=EdgeType.CONTAINS))

    g.add_edge(GraphEdge(from_id=other_method.id, to_id=method.id, type=EdgeType.CALL))

    a = Analyzer(g)
    callers, callees = a.impact_call_counts(cls.id)
    assert callers.get(other_cls.id) == 1
    assert callees == {}
