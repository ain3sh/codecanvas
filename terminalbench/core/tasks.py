from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import yaml
except ImportError as exc:
    raise RuntimeError(
        "pyyaml is required to load TerminalBench task manifests; install with `pip install pyyaml`."
    ) from exc


DEFAULT_MANIFEST = Path(__file__).resolve().parent.parent / "tasks.yaml"
DEFAULT_ENV_FILE = Path(__file__).resolve().parent / ".env"


@dataclass(frozen=True)
class Task:
    """Represents a single Terminal-Bench task entry."""

    id: str
    dataset: str = "terminal-bench@2.0"
    order: int | None = None


@dataclass
class ManifestConfig:
    """Top-level configuration from the manifest."""

    env_file: Optional[Path] = None
    mcp_config: Optional[str] = None  # Path to .mcp.json
    hooks: Optional[str] = None  # Path to hooks settings


def load_manifest(path: Path | str | None = None) -> Tuple[List[Task], ManifestConfig]:
    """Load tasks and config from a YAML manifest."""
    manifest_path = Path(path) if path else DEFAULT_MANIFEST
    data = yaml.safe_load(manifest_path.read_text())

    if not isinstance(data, dict):
        return [], ManifestConfig()

    # Parse tasks
    raw_tasks: list[dict] = data.get("tasks", [])
    tasks = [Task(**{k: v for k, v in item.items() if k in Task.__dataclass_fields__}) for item in raw_tasks]
    tasks.sort(key=lambda t: (t.order if t.order is not None else 10_000, t.id))

    # Parse config
    env_file_str = data.get("env_file")
    env_file = Path(env_file_str) if env_file_str else None
    config = ManifestConfig(
        env_file=env_file,
        mcp_config=data.get("mcp_config"),
        hooks=data.get("hooks"),
    )

    return tasks, config
