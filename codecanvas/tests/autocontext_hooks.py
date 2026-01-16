from __future__ import annotations

import json
from pathlib import Path

import pytest

from codecanvas.core.models import EdgeType, GraphEdge
from codecanvas.hooks.autocontext import handle_post_tool_use, handle_pre_tool_use
from codecanvas.parser.utils import find_workspace_root
from codecanvas.server import canvas_action


def test_find_workspace_root_prefer_env_false_ignores_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    f = repo / "a.py"
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")

    # Simulate a stale CANVAS_PROJECT_DIR that would wrongly swallow the file.
    monkeypatch.setenv("CANVAS_PROJECT_DIR", str(tmp_path))

    assert find_workspace_root(f, prefer_env=False) == repo


def test_autocontext_pre_tool_use_inits_marker_backed_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("CODECANVAS_DISABLE_LSP_WARMUP", "1")

    warmup_dir = tmp_path / "sessions" / "codecanvas"
    warmup_dir.mkdir(parents=True, exist_ok=True)
    (warmup_dir / "lsp_warmup.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "root": str(repo),
                "attempt": 5,
                "updated_at": 0.0,
                "ready_langs": [],
                "last_error": "forced_by_test",
            }
        ),
        encoding="utf-8",
    )

    ctx = handle_pre_tool_use(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Grep",
            "cwd": str(repo),
            "tool_input": {"path": str(repo)},
        }
    )
    assert ctx is None or "[CodeCanvas AUTO-INIT]" in ctx

    state_path = repo / ".codecanvas" / "state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert int(state.get("parse_summary", {}).get("parsed_files", 0) or 0) > 0


def test_autocontext_read_emits_context_when_call_edges_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "a.py").write_text(
        "def foo():\n    return 1\n\n\ndef bar():\n    return foo()\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("CANVAS_PROJECT_DIR", str(tmp_path))

    canvas_action(action="init", repo_path=str(tmp_path), use_lsp=False)

    import codecanvas.server as srv

    assert srv._graph is not None
    assert srv._analyzer is not None

    foo = srv._analyzer.find_target("foo")
    bar = srv._analyzer.find_target("bar")
    assert foo is not None
    assert bar is not None
    srv._graph.add_edge(GraphEdge(from_id=bar.id, to_id=foo.id, type=EdgeType.CALL))

    read_ctx = handle_post_tool_use(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Read",
            "cwd": str(tmp_path),
            "tool_input": {"file_path": str(tmp_path / "a.py")},
            "tool_response": {"filePath": str(tmp_path / "a.py"), "success": True},
        }
    )

    assert read_ctx is not None
    assert "[CodeCanvas IMPACT]" in read_ctx
