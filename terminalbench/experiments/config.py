from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import tomllib

from terminalbench.core.profiles import DEFAULT_MODEL, DEFAULT_REASONING


@dataclass
class RunConfig:
    results_root: Path = Path("results")
    profiles_parallel: int = 0
    attempts: int = 1
    retries: int = 0
    parallel: int = 0
    container_env: str = "docker"
    harbor_bin: Optional[str] = None
    registry_path: Optional[Path] = None
    extra_flags: List[str] = field(default_factory=list)
    force_rebuild: bool = False


@dataclass(frozen=True)
class TaskEntry:
    id: str
    dataset: str


@dataclass
class TasksConfig:
    default_dataset: str = "terminal-bench@2.0"
    items: List[TaskEntry] = field(default_factory=list)


@dataclass
class DefaultsConfig:
    model: str = DEFAULT_MODEL
    reasoning: str = DEFAULT_REASONING
    mcp_git_source: Optional[str] = None
    env_file: Optional[Path] = None
    hooks: Optional[Path] = None
    mcp_servers: Optional[List[str]] = None
    claude_version: Optional[str] = None


@dataclass
class ArtifactsConfig:
    targets: List[str] = field(default_factory=list)


@dataclass
class ProfileConfig:
    key: str
    model: Optional[str] = None
    reasoning: Optional[str] = None
    claude_version: Optional[str] = None
    no_mcp: bool = False
    mcp_servers: Optional[List[str]] = None
    hooks: Optional[Path] = None
    mcp_git_source: Optional[str] = None


@dataclass
class ExperimentConfig:
    schema_version: int
    name: str
    slug: str
    run: RunConfig
    tasks: TasksConfig
    defaults: DefaultsConfig
    artifacts: ArtifactsConfig
    profiles: List[ProfileConfig]


_SLUG_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def _resolve_path(base: Path, value: Optional[str]) -> Optional[Path]:
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def load_experiment(path: Path, project_root: Path) -> ExperimentConfig:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))

    schema_version = raw.get("schema_version")
    if schema_version != 2:
        raise ValueError("schema_version=2 is required")

    name = str(raw.get("name") or "").strip()
    slug = str(raw.get("slug") or "").strip()
    if not slug:
        raise ValueError("experiment slug is required")
    if not _SLUG_RE.match(slug):
        raise ValueError(f"invalid experiment slug: {slug}")

    run_data = raw.get("run") or {}
    run = RunConfig(
        results_root=Path(run_data.get("results_root") or "results"),
        profiles_parallel=int(run_data.get("profiles_parallel") or 0),
        attempts=int(run_data.get("attempts") or 1),
        retries=int(run_data.get("retries") or 0),
        parallel=int(run_data.get("parallel") or 0),
        container_env=str(run_data.get("container_env") or "docker"),
        harbor_bin=run_data.get("harbor_bin") or None,
        registry_path=(
            _resolve_path(project_root, run_data.get("registry_path"))
            if run_data.get("registry_path")
            else None
        ),
        extra_flags=list(run_data.get("extra_flags") or []),
        force_rebuild=bool(run_data.get("force_rebuild") or False),
    )

    tasks_data = raw.get("tasks") or {}
    default_dataset = str(tasks_data.get("default_dataset") or "terminal-bench@2.0")
    task_items: List[TaskEntry] = []
    for key, value in tasks_data.items():
        if key == "default_dataset":
            continue
        if not isinstance(value, dict):
            raise ValueError("tasks entries must be tables")
        dataset = str(value.get("dataset") or default_dataset)
        task_items.append(TaskEntry(id=str(key), dataset=dataset))
    if not task_items:
        raise ValueError("tasks must define at least one task")
    tasks = TasksConfig(default_dataset=default_dataset, items=task_items)

    defaults_data = raw.get("defaults") or {}
    defaults = DefaultsConfig(
        model=str(defaults_data.get("model") or DEFAULT_MODEL),
        reasoning=str(defaults_data.get("reasoning") or DEFAULT_REASONING),
        mcp_git_source=defaults_data.get("mcp_git_source") or None,
        env_file=_resolve_path(project_root, defaults_data.get("env_file") or None),
        hooks=_resolve_path(project_root, defaults_data.get("hooks") or None),
        mcp_servers=list(defaults_data.get("mcp_servers") or []) or None,
        claude_version=defaults_data.get("claude_version") or None,
    )

    artifacts_data = raw.get("artifacts") or {}
    artifacts = ArtifactsConfig(targets=list(artifacts_data.get("targets") or []))

    profiles_raw = raw.get("profiles") or {}
    if not profiles_raw:
        raise ValueError("profiles must be a non-empty mapping")

    profiles: List[ProfileConfig] = []
    for key, entry in profiles_raw.items():
        if not isinstance(entry, dict):
            raise ValueError("profile entries must be tables")
        key = str(key).strip()
        if not key:
            raise ValueError("profile key is required")
        profiles.append(
            ProfileConfig(
                key=key,
                model=entry.get("model"),
                reasoning=entry.get("reasoning"),
                claude_version=entry.get("claude_version"),
                no_mcp=bool(entry.get("no_mcp") or False),
                mcp_servers=list(entry.get("mcp_servers") or []) or None,
                hooks=_resolve_path(project_root, entry.get("hooks") or None),
                mcp_git_source=entry.get("mcp_git_source") or None,
            )
        )

    return ExperimentConfig(
        schema_version=2,
        name=name or slug,
        slug=slug,
        run=run,
        tasks=tasks,
        defaults=defaults,
        artifacts=artifacts,
        profiles=profiles,
    )
