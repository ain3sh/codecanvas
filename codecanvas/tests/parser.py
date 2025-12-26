"""Parser tests - imports, workspace detection, LSP fallback."""

from __future__ import annotations

from pathlib import Path

from codecanvas.core.models import EdgeType, make_module_id
from codecanvas.parser import Parser
from codecanvas.parser.utils import find_workspace_root


def test_python_relative_imports_create_module_edges(tmp_path: Path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "b.py").write_text("def b():\n    return 1\n", encoding="utf-8")
    (pkg / "a.py").write_text("from .b import b\n\nprint(b())\n", encoding="utf-8")

    g = Parser().parse_directory(str(tmp_path))

    a_id = make_module_id("pkg/a.py")
    b_id = make_module_id("pkg/b.py")
    assert g.get_node(a_id) is not None
    assert g.get_node(b_id) is not None
    assert any(e.from_id == a_id and e.to_id == b_id and e.type == EdgeType.IMPORT for e in g.edges)


def test_python_package_import_prefers_init(tmp_path: Path):
    (tmp_path / "mypkg").mkdir()
    (tmp_path / "mypkg" / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("import mypkg\n", encoding="utf-8")

    g = Parser().parse_directory(str(tmp_path))
    main_id = make_module_id("main.py")
    init_id = make_module_id("mypkg/__init__.py")
    assert any(e.from_id == main_id and e.to_id == init_id and e.type == EdgeType.IMPORT for e in g.edges)


def test_empty_lsp_symbols_does_not_force_fallback(monkeypatch, tmp_path: Path):
    (tmp_path / "a.py").write_text("import os\n", encoding="utf-8")

    import codecanvas.parser as parser_mod
    monkeypatch.setattr(parser_mod, "has_lsp_support", lambda _lang: True)

    def _fake_parse_with_lsp(self, file_path, file_label, text, lang, graph, *, module_id):
        self._process_lsp_symbols([], module_id, file_label, str(file_path), text.split("\n"), graph)

    monkeypatch.setattr(Parser, "_parse_with_lsp", _fake_parse_with_lsp)

    parser = Parser(use_lsp=True)
    parser.parse_directory(str(tmp_path))

    assert parser.last_summary.lsp_files == 1
    assert parser.last_summary.tree_sitter_files == 0
    assert parser.last_summary.lsp_failures == {}


def test_find_workspace_root_walks_up_to_git(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    nested = repo / "src" / "pkg"
    nested.mkdir(parents=True)
    f = nested / "a.py"
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")

    assert find_workspace_root(f) == repo


def test_parser_skips_node_modules_with_pruning(tmp_path: Path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("def bar():\n    return 1\n", encoding="utf-8")

    g = Parser().parse_directory(str(tmp_path))
    assert g.get_node(make_module_id("main.py")) is not None
    assert g.get_node(make_module_id("node_modules/a.py")) is None
