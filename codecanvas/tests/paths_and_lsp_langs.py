from __future__ import annotations

from pathlib import Path

import pytest

from codecanvas.core.models import NodeKind
from codecanvas.core.state import load_state
from codecanvas.parser import Parser
from codecanvas.server import canvas_action


def test_label_strips_single_top_level_project_prefix(tmp_path: Path) -> None:
    app = tmp_path / "app"
    repo = app / "repo"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")

    g = Parser(use_lsp=False).parse_directory(str(app))
    labels = {n.label for n in g.nodes if n.kind == NodeKind.MODULE}

    assert "a.py" in labels
    assert "repo/a.py" not in labels


def test_label_preserves_prefix_for_multiple_top_level_projects(tmp_path: Path) -> None:
    app = tmp_path / "app"
    r1 = app / "pyknotid"
    r2 = app / "bobscalob"
    r1.mkdir(parents=True)
    r2.mkdir(parents=True)
    (r1 / ".git").mkdir()
    (r2 / ".git").mkdir()
    (r1 / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (r2 / "b.py").write_text("def bar():\n    return 2\n", encoding="utf-8")

    g = Parser(use_lsp=False).parse_directory(str(app))
    labels = {n.label for n in g.nodes if n.kind == NodeKind.MODULE}

    assert "pyknotid/a.py" in labels
    assert "bobscalob/b.py" in labels


def test_canvas_artifact_dir_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")

    artifact_dir = tmp_path / "artifacts"
    monkeypatch.setenv("CANVAS_ARTIFACT_DIR", str(artifact_dir))

    res = canvas_action(action="init", repo_path=str(tmp_path), use_lsp=False)
    assert res.images

    assert (artifact_dir / "state.json").exists()
    state = load_state()
    assert (artifact_dir / f"architecture.{state.graph_digest}.png").exists()


def test_parser_lsp_langs_allows_only_subset(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")

    p = Parser(use_lsp=True, lsp_langs={"ts"})
    _ = p.parse_directory(str(tmp_path))

    assert p.last_summary.parsed_files == 1
    assert p.last_summary.lsp_files == 0
    assert p.last_summary.tree_sitter_files >= 1
