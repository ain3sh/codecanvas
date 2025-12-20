from __future__ import annotations

from pathlib import Path

from codecanvas.core.models import make_module_id
from codecanvas.parser import Parser
from codecanvas.parser.workspace import find_workspace_root


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
