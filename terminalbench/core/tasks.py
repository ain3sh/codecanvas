from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    """Represents a single Terminal-Bench task entry."""

    id: str
    dataset: str = "terminal-bench@2.0"
    order: int | None = None
