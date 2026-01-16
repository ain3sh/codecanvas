from __future__ import annotations

import asyncio
from pathlib import Path

from codecanvas import server
from codecanvas.core.models import EdgeType, Graph, GraphEdge, GraphNode, NodeKind, make_func_id
from codecanvas.parser import Parser
from codecanvas.parser import call_graph as cg


def test_call_graph_builds_edges_from_definition(monkeypatch, tmp_path: Path):
    (tmp_path / "a.py").write_text(
        "def callee():\n    return 1\n\ndef caller():\n    callee()\n",
        encoding="utf-8",
    )

    g = Parser(use_lsp=False).parse_directory(str(tmp_path))

    caller_id = make_func_id("a.py", "caller")
    callee_id = make_func_id("a.py", "callee")

    monkeypatch.setattr(cg, "has_lsp_support", lambda _lang: True)

    class _StubRuntime:
        def run(self, coro, timeout=None):
            return asyncio.run(coro)

    monkeypatch.setattr(cg, "get_lsp_runtime", lambda: _StubRuntime())

    async def _fake_resolve_definitions_for_callsites(*, lang: str, file_path: Path, text: str, callsites):
        uri = cg.path_to_uri(str(file_path))
        loc = {
            "uri": uri,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
        }
        return [[loc] for _ in callsites]

    monkeypatch.setattr(cg, "_resolve_definitions_for_callsites", _fake_resolve_definitions_for_callsites)
    monkeypatch.setattr(
        cg,
        "extract_call_sites",
        lambda _text, *, file_path, lang_key: [cg.TsCallSite(line=4, char=4)],
    )

    result = cg.build_call_graph_edges(g.nodes, time_budget_s=1.0, max_callsites_total=10, max_callsites_per_file=10)

    assert any(e.from_id == caller_id and e.to_id == callee_id and e.type == EdgeType.CALL for e in result.edges)


def _make_graph(tmp_path: Path) -> tuple[Graph, GraphNode, GraphNode]:
    graph = Graph()
    node_a = GraphNode(
        id="fn_a",
        kind=NodeKind.FUNC,
        label="fn_a",
        fsPath=str(tmp_path / "a.py"),
        start_line=1,
        end_line=1,
    )
    node_b = GraphNode(
        id="fn_b",
        kind=NodeKind.FUNC,
        label="fn_b",
        fsPath=str(tmp_path / "a.py"),
        start_line=2,
        end_line=2,
    )
    graph.add_node(node_a)
    graph.add_node(node_b)
    return graph, node_a, node_b


def test_call_edge_cache_round_trip(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CANVAS_ARTIFACT_DIR", raising=False)
    graph, node_a, node_b = _make_graph(tmp_path)
    graph.add_edge(GraphEdge(from_id=node_a.id, to_id=node_b.id, type=EdgeType.CALL))

    server._persist_call_edge_cache(graph, tmp_path, generation=1, source="test")

    cache_path = tmp_path / ".codecanvas" / "call_edges.json"
    assert cache_path.exists()

    new_graph, node_a2, _node_b2 = _make_graph(tmp_path)
    meta = server._merge_cached_call_edges(new_graph, tmp_path)
    assert meta is not None
    assert meta["cache_edges_added"] == 1
    assert new_graph.stats()["call_edges"] == 1

    missing_graph = Graph()
    missing_graph.add_node(node_a2)
    meta_missing = server._merge_cached_call_edges(missing_graph, tmp_path)
    assert meta_missing is not None
    assert meta_missing["cache_edges_added"] == 0
    assert meta_missing["cache_edges_missing_nodes"] == 1
