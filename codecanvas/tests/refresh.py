from __future__ import annotations

from pathlib import Path

from codecanvas.core.refresh import ack_dirty, claim_dirty, mark_dirty, read_dirty, reap_dirty


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("def foo():\n    return 1\n", encoding="utf-8")
    b.write_text("def bar():\n    return 2\n", encoding="utf-8")
    return a, b


def test_claim_ack_ok_removes_entry(tmp_path: Path) -> None:
    a, b = _paths(tmp_path)
    mark_dirty(tmp_path, [a, b], reason="test")

    claimed = claim_dirty(tmp_path, max_items=1)
    assert len(claimed) == 1
    item = claimed[0]
    assert item["status"] == "in_progress"
    assert item.get("claim_id")

    ok = ack_dirty(tmp_path, claim_id=item["claim_id"], path=item["path"], outcome="ok")
    assert ok

    remaining = read_dirty(tmp_path)
    assert item["path"] not in remaining
    assert str(b) in remaining


def test_reap_stale_claim_requeues(tmp_path: Path) -> None:
    a, _ = _paths(tmp_path)
    mark_dirty(tmp_path, [a], reason="test")

    claimed = claim_dirty(tmp_path, max_items=1)
    assert len(claimed) == 1

    reaped = reap_dirty(tmp_path, ttl_s=0.0)
    assert reaped == 1

    items = read_dirty(tmp_path)
    entry = items[str(a)]
    assert entry["status"] == "pending"
    assert "claim_id" not in entry


def test_ack_deferred_returns_to_pending(tmp_path: Path) -> None:
    a, _ = _paths(tmp_path)
    mark_dirty(tmp_path, [a], reason="test")

    claimed = claim_dirty(tmp_path, max_items=1)
    assert len(claimed) == 1
    item = claimed[0]

    ok = ack_dirty(tmp_path, claim_id=item["claim_id"], path=item["path"], outcome="deferred")
    assert ok

    items = read_dirty(tmp_path)
    entry = items[str(a)]
    assert entry["status"] == "pending"
    assert entry.get("reason") == "refresh_deferred"
