"""API tests - Evidence Board and canvas_action."""

from __future__ import annotations

from pathlib import Path

from codecanvas.core.state import load_state
from codecanvas.server import canvas_action


def test_impact_creates_evidence_and_board_png(tmp_path: Path):
    (tmp_path / "a.py").write_text(
        "def foo():\n    return 1\n\ndef bar():\n    return foo()\n",
        encoding="utf-8",
    )

    canvas_action(action="init", repo_path=str(tmp_path))
    res = canvas_action(action="impact", symbol="foo", depth=1, max_nodes=20)

    assert [img.name for img in res.images] == ["impact", "board"]
    assert Path(res.images[0].png_path).exists()
    assert Path(res.images[1].png_path).exists()

    state = load_state()
    assert state.initialized
    assert state.evidence
    assert state.evidence[-1].kind == "impact"
    assert state.focus


def test_claim_auto_links_recent_evidence(tmp_path: Path):
    (tmp_path / "a.py").write_text(
        "def foo():\n    return 1\n\ndef bar():\n    return foo()\n",
        encoding="utf-8",
    )

    canvas_action(action="init", repo_path=str(tmp_path))
    canvas_action(action="impact", symbol="foo", depth=1, max_nodes=20)
    canvas_action(action="claim", text="Hypothesis: foo change breaks bar", kind="hypothesis")

    state = load_state()
    assert state.claims
    assert state.claims[-1].evidence_ids
    assert state.claims[-1].evidence_ids[0] == state.evidence[-1].id


def test_task_select_persists_active_task(tmp_path: Path):
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tasks.yaml").write_text(
        "tasks:\n  - id: t1\n    order: 1\n    dataset: demo\n    tb_url: https://example.com/t1\n",
        encoding="utf-8",
    )

    canvas_action(action="init", repo_path=str(tmp_path))
    canvas_action(action="task_select", task_id="t1")

    state = load_state()
    assert state.active_task_id == "t1"


def test_canvas_result_init_generates_png(tmp_path: Path):
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")

    result = canvas_action(action="init", repo_path=str(tmp_path))
    assert result.images
    assert result.images[0].name == "architecture"
    assert Path(result.images[0].png_path).exists()
    assert result.images[0].png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    assert Path(result.images[0].png_path) == tmp_path / ".codecanvas" / "architecture.png"

    assert result.images[1].name == "board"
    assert Path(result.images[1].png_path).exists()
    assert result.images[1].png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
