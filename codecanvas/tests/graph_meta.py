from __future__ import annotations

import json
from pathlib import Path

from codecanvas.core.graph_meta import compute_graph_meta, load_graph_meta
from codecanvas.core.models import NodeKind
from codecanvas.core.refresh import mark_dirty
from codecanvas.core.state import load_state
from codecanvas.parser import Parser
from codecanvas.server import _CALL_EDGE_CACHE_VERSION, _call_edge_cache_path, _merge_cached_call_edges, canvas_action


def _parse_summary_from(parser: Parser) -> dict:
    summary = parser.last_summary
    return {
        "parsed_files": summary.parsed_files,
        "skipped_files": summary.skipped_files,
        "lsp_files": summary.lsp_files,
        "tree_sitter_files": summary.tree_sitter_files,
        "lsp_failures": dict(summary.lsp_failures or {}),
    }


def test_merkle_digest_deterministic(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def bar():\n    return 2\n", encoding="utf-8")

    parser = Parser(use_lsp=False)
    graph = parser.parse_directory(str(tmp_path))
    parse_summary = _parse_summary_from(parser)

    meta1 = compute_graph_meta(
        graph=graph,
        project_dir=tmp_path,
        parse_summary=parse_summary,
        use_lsp=False,
        lsp_langs=None,
        label_strip_prefix=None,
    )
    meta2 = compute_graph_meta(
        graph=graph,
        project_dir=tmp_path,
        parse_summary=parse_summary,
        use_lsp=False,
        lsp_langs=None,
        label_strip_prefix=None,
        existing_meta=meta1,
    )

    assert meta1["graph"]["digest"] == meta2["graph"]["digest"]


def test_architecture_per_digest_on_refresh(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")

    canvas_action(action="init", repo_path=str(tmp_path), use_lsp=False)
    meta1 = load_graph_meta(tmp_path)
    assert meta1 is not None
    digest1 = meta1["graph"]["digest"]
    arch1 = tmp_path / ".codecanvas" / f"architecture.{digest1}.png"
    assert arch1.exists()

    (tmp_path / "b.py").write_text("def bar():\n    return 2\n", encoding="utf-8")
    mark_dirty(tmp_path, [tmp_path / "b.py"], reason="test")
    canvas_action(action="status")

    meta2 = load_graph_meta(tmp_path)
    assert meta2 is not None
    digest2 = meta2["graph"]["digest"]
    assert digest1 != digest2
    arch2 = tmp_path / ".codecanvas" / f"architecture.{digest2}.png"
    assert arch2.exists()

    state = load_state()
    arch_ev = next(ev for ev in state.evidence if ev.kind == "architecture")
    assert arch_ev.metrics.get("modules", 0) >= 2


def test_call_edge_cache_digest_gating(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def bar():\n    return 2\n", encoding="utf-8")

    parser = Parser(use_lsp=False)
    graph = parser.parse_directory(str(tmp_path))
    parse_summary = _parse_summary_from(parser)
    meta = compute_graph_meta(
        graph=graph,
        project_dir=tmp_path,
        parse_summary=parse_summary,
        use_lsp=False,
        lsp_langs=None,
        label_strip_prefix=None,
    )
    digest = meta["graph"]["digest"]

    func_ids = [n.id for n in graph.nodes if n.kind == NodeKind.FUNC]
    assert len(func_ids) >= 2

    cache_path = _call_edge_cache_path(tmp_path)
    payload = {
        "version": _CALL_EDGE_CACHE_VERSION,
        "project_path": str(tmp_path),
        "generated_at": 0.0,
        "generation": 1,
        "source": "test",
        "instance_id": "test",
        "graph_digest": "deadbeef",
        "edges": [{"from_id": func_ids[0], "to_id": func_ids[1]}],
        "stats": {"edges_total": 1},
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    cache_info = _merge_cached_call_edges(graph, tmp_path, expected_digest=digest)
    assert cache_info is None
    assert graph.stats().get("call_edges", 0) == 0
