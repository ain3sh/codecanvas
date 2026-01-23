"""Core configuration helpers for terminalbench."""

from __future__ import annotations

from pathlib import Path

CONFIG_DIR = Path.home() / ".terminalbench"


def get_batch_dir(base: Path, batch_id: int | None = None) -> Path:
    """Get or create a batch directory within the results base.

    Args:
        base: Base results directory (e.g., ./results)
        batch_id: Explicit batch ID, or None to auto-detect next available

    Returns:
        Path to batch directory (e.g., ./results/3/)
    """
    base = Path(base).resolve()
    base.mkdir(parents=True, exist_ok=True)

    if batch_id is None:
        # Auto-detect: find max existing batch ID + 1
        existing = [int(d.name) for d in base.iterdir() if d.is_dir() and d.name.isdigit()]
        batch_id = max(existing, default=-1) + 1

    batch_dir = base / str(batch_id)

    # Create subdirectory structure
    (batch_dir / "runs").mkdir(parents=True, exist_ok=True)
    (batch_dir / "analytics").mkdir(parents=True, exist_ok=True)
    (batch_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    return batch_dir
