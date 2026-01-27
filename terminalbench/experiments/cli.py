from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from terminalbench.core.config import get_batch_dir
from terminalbench.core.profiles import (
    MCP_USAGE_ALIASES,
    build_profile,
    discover_mcp_usage_prompts,
    load_mcp_config,
    merge_mcp_configs,
)
from terminalbench.core.tasks import Task
from terminalbench.harbor.runner import HarborRunner, load_env_file

from .config import ExperimentConfig, load_experiment


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_mcp_config(project_root: Path, servers: List[str]) -> dict:
    configs = []
    for server in servers:
        source_dir = MCP_USAGE_ALIASES.get(server, server)
        cfg_path = project_root / source_dir / ".mcp.json"
        if not cfg_path.exists():
            raise ValueError(f"missing MCP config for server '{server}': {cfg_path}")
        configs.append(load_mcp_config(cfg_path))
    return merge_mcp_configs(configs)


def _filter_list(values: List[str], selected: Optional[List[str]], label: str) -> List[str]:
    if not selected:
        return values
    missing = [v for v in selected if v not in values]
    if missing:
        raise ValueError(f"unknown {label}: {', '.join(missing)}")
    return [v for v in values if v in selected]


def _build_tasks(cfg: ExperimentConfig, selected_tasks: Optional[List[str]]) -> List[Task]:
    ordered_ids = [item.id for item in cfg.tasks.items]
    wanted = set(_filter_list(ordered_ids, selected_tasks, "tasks"))
    tasks: List[Task] = []
    for idx, item in enumerate(cfg.tasks.items, start=1):
        if item.id not in wanted:
            continue
        tasks.append(Task(id=item.id, dataset=item.dataset, order=idx))
    return tasks


def _build_profiles(
    cfg: ExperimentConfig,
    project_root: Path,
    selected_profiles: Optional[List[str]],
    github_token: Optional[str],
) -> List:
    profile_keys = [p.key for p in cfg.profiles]
    allowed = _filter_list(profile_keys, selected_profiles, "profiles")
    seen = set()
    profiles = []
    for profile in cfg.profiles:
        if profile.key not in allowed:
            continue
        if profile.key in seen:
            raise ValueError(f"duplicate profile key: {profile.key}")
        seen.add(profile.key)

        model = profile.model or cfg.defaults.model
        reasoning = profile.reasoning or cfg.defaults.reasoning
        claude_version = profile.claude_version or cfg.defaults.claude_version

        install_r_languageserver = (
            profile.install_r_languageserver
            if profile.install_r_languageserver is not None
            else cfg.defaults.install_r_languageserver
        )

        no_mcp = bool(profile.no_mcp)
        default_servers = cfg.defaults.mcp_servers or []
        mcp_servers = profile.mcp_servers if profile.mcp_servers is not None else default_servers

        if no_mcp:
            mcp_servers = []
        if not no_mcp and not mcp_servers:
            raise ValueError(f"profile '{profile.key}' must specify mcp_servers or set no_mcp")

        hooks_path = profile.hooks or cfg.defaults.hooks
        if no_mcp and profile.hooks is None:
            hooks_path = None

        mcp_config = None
        if mcp_servers:
            mcp_config = _resolve_mcp_config(project_root, mcp_servers)

        system_prompt = None
        if mcp_servers:
            system_prompt = discover_mcp_usage_prompts(mcp_servers, search_dir=project_root)

        profiles.append(
            build_profile(
                key=profile.key,
                model=model,
                reasoning=reasoning,
                claude_version=claude_version,
                mcp_config=mcp_config,
                enabled_mcp_servers=None,
                hooks_path=hooks_path,
                mcp_git_source=profile.mcp_git_source or cfg.defaults.mcp_git_source,
                github_token=github_token,
                system_prompt=system_prompt,
                install_r_languageserver=install_r_languageserver,
            )
        )
    return profiles


def _git_sha(project_root: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


def _write_run_metadata(batch_dir: Path, experiment_path: Path, payload: dict) -> None:
    try:
        shutil.copy2(experiment_path, batch_dir / "experiment.toml")
    except Exception:
        pass
    try:
        (batch_dir / "resolved.json").write_text(json.dumps(payload, indent=2))
    except Exception:
        pass


def run_experiment(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TerminalBench experiments runner")
    parser.add_argument("experiment", type=Path, help="Path to experiment TOML")
    parser.add_argument("--tasks", nargs="+", help="Override task ids to run")
    parser.add_argument("--profiles", nargs="+", help="Override profile keys to run")
    parser.add_argument("--batch", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    project_root = _project_root()
    experiment_path = args.experiment.resolve()
    cfg = load_experiment(experiment_path, project_root)

    env_file = cfg.defaults.env_file or (project_root / "experiments" / ".env")
    env_from_file = load_env_file(env_file)
    github_token = env_from_file.get("GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")

    tasks = _build_tasks(cfg, args.tasks)
    profiles = _build_profiles(cfg, project_root, args.profiles, github_token)

    output_root = (project_root / cfg.run.results_root / cfg.slug).resolve()
    batch_dir = get_batch_dir(output_root, args.batch)
    runs_dir = batch_dir / "runs"

    if cfg.run.force_rebuild:
        os.environ.setdefault("TERMINALBENCH_FORCE_REBUILD", "1")

    runner = HarborRunner(
        harbor_bin=cfg.run.harbor_bin,
        output_root=runs_dir,
        attempts=cfg.run.attempts,
        retries=cfg.run.retries,
        parallel=cfg.run.parallel,
        container_env=cfg.run.container_env,
        dry_run=args.dry_run,
        extra_flags=cfg.run.extra_flags,
        env_file=env_file,
        registry_path=cfg.run.registry_path,
        artifact_targets=cfg.artifacts.targets,
        run_timeout_sec=cfg.run.run_timeout_sec,
    )

    metadata = {
        "schema_version": cfg.schema_version,
        "name": cfg.name,
        "slug": cfg.slug,
        "experiment": str(experiment_path),
        "git_sha": _git_sha(project_root),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run": {
            "results_root": str(cfg.run.results_root),
            "profiles_parallel": cfg.run.profiles_parallel,
            "attempts": cfg.run.attempts,
            "retries": cfg.run.retries,
            "parallel": cfg.run.parallel,
            "container_env": cfg.run.container_env,
            "harbor_bin": cfg.run.harbor_bin,
            "registry_path": str(cfg.run.registry_path) if cfg.run.registry_path else None,
            "extra_flags": cfg.run.extra_flags,
            "force_rebuild": cfg.run.force_rebuild,
            "run_timeout_sec": cfg.run.run_timeout_sec,
            "dry_run": args.dry_run,
        },
        "tasks": [t.id for t in tasks],
        "profiles": [p.key for p in profiles],
        "artifacts": cfg.artifacts.targets,
    }
    _write_run_metadata(batch_dir, experiment_path, metadata)

    runner.run_profiles(tasks, profiles, profiles_parallel=cfg.run.profiles_parallel)
    return 0


def _latest_batch_dir(base: Path) -> Path:
    if not base.exists():
        raise FileNotFoundError(f"results directory not found: {base}")
    batch_ids = [int(d.name) for d in base.iterdir() if d.is_dir() and d.name.isdigit()]
    if not batch_ids:
        raise FileNotFoundError(f"no batch directories found in {base}")
    return base / str(max(batch_ids))


def analyze_experiment(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TerminalBench experiments analyze")
    parser.add_argument("experiment", type=Path, help="Path to experiment TOML")
    parser.add_argument("--batch", type=int, default=None)
    parser.add_argument("--output", "-o", type=Path, default=None)
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--llm-only", action="store_true")
    parser.add_argument("--compare", nargs=2)
    parser.add_argument("--tasks", nargs="+")
    parser.add_argument("--profiles", nargs="+")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--succeeded", action="store_true")
    parser.add_argument("--failed", action="store_true")
    parser.add_argument("--estimate-cost", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--quiet", "-q", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    project_root = _project_root()
    cfg = load_experiment(args.experiment.resolve(), project_root)

    base = (project_root / cfg.run.results_root / cfg.slug).resolve()
    batch_dir = base / str(args.batch) if args.batch is not None else _latest_batch_dir(base)
    runs_dir = batch_dir / "runs"

    from terminalbench.analytics.io import cli as analytics_cli

    argv_list: List[str] = ["terminalbench.analytics", str(runs_dir)]
    if args.output:
        argv_list.extend(["--output", str(args.output)])
    if args.no_llm:
        argv_list.append("--no-llm")
    if args.llm_only:
        argv_list.append("--llm-only")
    if args.compare:
        argv_list.extend(["--compare", *args.compare])
    if args.tasks:
        argv_list.extend(["--tasks", *args.tasks])
    if args.profiles:
        argv_list.extend(["--profiles", *args.profiles])
    if args.limit is not None:
        argv_list.extend(["--limit", str(args.limit)])
    if args.list:
        argv_list.append("--list")
    if args.succeeded:
        argv_list.append("--succeeded")
    if args.failed:
        argv_list.append("--failed")
    if args.estimate_cost:
        argv_list.append("--estimate-cost")
    if args.model:
        argv_list.extend(["--model", args.model])
    if args.quiet:
        argv_list.append("--quiet")

    prev_argv = sys.argv
    try:
        sys.argv = argv_list
        analytics_cli.main()
    finally:
        sys.argv = prev_argv
    return 0


def _collect_processes() -> List[tuple[int, str]]:
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,command="],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except Exception:
        return []
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    out = []
    for line in lines:
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        out.append((pid, parts[1]))
    return out


def _kill_processes(pids: List[int]) -> None:
    for pid in pids:
        try:
            os.kill(pid, 9)
        except Exception:
            continue


def _list_containers() -> List[tuple[str, str, str]]:
    if not shutil.which("docker"):
        return []
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.ID}} {{.Image}} {{.Names}}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except Exception:
        return []
    out = []
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) == 3:
            out.append((parts[0], parts[1], parts[2]))
    return out


def _kill_containers(container_ids: List[str]) -> None:
    if not container_ids or not shutil.which("docker"):
        return
    subprocess.run(["docker", "kill", *container_ids], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kill_experiments(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kill TerminalBench experiment processes")
    parser.add_argument("--all", action="store_true", help="Kill all running Docker containers")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.yes:
        print("Refusing to kill processes without --yes")
        return 1

    procs = _collect_processes()
    current_pid = os.getpid()
    to_kill = []
    for pid, cmd in procs:
        if pid == current_pid:
            continue
        if "terminalbench.experiments kill" in cmd:
            continue
        if any(key in cmd for key in ("terminalbench", "harbor", "run-experiment")):
            to_kill.append(pid)
    _kill_processes(to_kill)

    containers = _list_containers()
    if args.all:
        _kill_containers([cid for cid, _, _ in containers])
    else:
        filtered = [
            cid
            for cid, image, name in containers
            if any(key in image for key in ("harbor", "terminalbench", "terminal-bench"))
            or any(key in name for key in ("harbor", "terminalbench", "terminal-bench"))
        ]
        _kill_containers(filtered)

    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TerminalBench experiments")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run an experiment TOML")
    run_parser.add_argument("experiment", type=Path)
    run_parser.add_argument("--tasks", nargs="+")
    run_parser.add_argument("--profiles", nargs="+")
    run_parser.add_argument("--batch", type=int, default=None)
    run_parser.add_argument("--dry-run", action="store_true")

    kill_parser = sub.add_parser("kill", help="Kill experiment processes")
    kill_parser.add_argument("--all", action="store_true")
    kill_parser.add_argument("--yes", action="store_true")

    analyze_parser = sub.add_parser("analyze", help="Analyze an experiment run")
    analyze_parser.add_argument("experiment", type=Path)
    analyze_parser.add_argument("--batch", type=int, default=None)
    analyze_parser.add_argument("--output", "-o", type=Path, default=None)
    analyze_parser.add_argument("--no-llm", action="store_true")
    analyze_parser.add_argument("--llm-only", action="store_true")
    analyze_parser.add_argument("--compare", nargs=2)
    analyze_parser.add_argument("--tasks", nargs="+")
    analyze_parser.add_argument("--profiles", nargs="+")
    analyze_parser.add_argument("--limit", type=int)
    analyze_parser.add_argument("--list", action="store_true")
    analyze_parser.add_argument("--succeeded", action="store_true")
    analyze_parser.add_argument("--failed", action="store_true")
    analyze_parser.add_argument("--estimate-cost", action="store_true")
    analyze_parser.add_argument("--model")
    analyze_parser.add_argument("--quiet", "-q", action="store_true")

    argv_list = list(argv) if argv is not None else None
    args = parser.parse_args(argv_list)
    sub_argv = argv_list if argv_list is not None else sys.argv[1:]
    if args.command == "run":
        return run_experiment(sub_argv[1:])
    if args.command == "kill":
        return kill_experiments(sub_argv[1:])
    if args.command == "analyze":
        return analyze_experiment(sub_argv[1:])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
