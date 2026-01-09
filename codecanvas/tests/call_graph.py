from __future__ import annotations

import asyncio
from pathlib import Path

from codecanvas.core.models import EdgeType, make_func_id
from codecanvas.parser import Parser
from codecanvas.parser import call_graph as cg


def test_call_graph_builds_edges_from_definition(monkeypatch, tmp_path: Path):
    (tmp_path / "a.py").write_text(
        "def callee():\n    return 1\n\ndef caller():\n    callee()\n",
        encoding="utf-8",
    )

    g = Parser(use_lsp=False).parse_directory(str(tmp_path))

    caller_id = make_func_id("a.py", "caller", 3)
    callee_id = make_func_id("a.py", "callee", 0)

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
