from __future__ import annotations

import argparse
import csv
import json
import sys

from pathlib import Path
from typing import Iterable, List

from .agents import build_profile, get_available_servers
from .runner import HarborRunner, RunResult
from .tasks import load_manifest, Task, DEFAULT_ENV_FILE
from .display import print_summary


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    from .config import load_config
    cfg = load_config()

    parser = argparse.ArgumentParser(description="Terminal-Bench harness")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("setup", help="Interactive configuration wizard")

    # Task selection
    parser.add_argument("--tasks", nargs="*", help="task ids to run; default=all from manifest")
    parser.add_argument("--manifest", type=Path, help="path to tasks manifest (yaml)")

    # Output and execution
    parser.add_argument("--output-dir", type=Path, default=Path(cfg.output_dir))
    parser.add_argument("--attempts", type=int, default=1, help="number of attempts per task (-k)")
    parser.add_argument("--retries", type=int, default=0, help="number of retries on failure")
    parser.add_argument("--dry-run", action="store_true", help="do not execute harbor, just emit commands")
    parser.add_argument("--quiet", action="store_true", help="suppress live output (for CI)")
    parser.add_argument("--parallel", "-n", type=int, default=0, help="parallel workers (passed to harbor -n)")

    # Harbor configuration
    parser.add_argument("--harbor-bin", default=cfg.harbor_bin, help="harbor executable (default: use uvx)")
    parser.add_argument("--container-env", default=cfg.container_env, help="container runtime (docker|daytona|modal|e2b)")
    parser.add_argument("--extra-flag", action="append", default=[], help="extra flag to pass to harbor run")
    parser.add_argument("--env-file", type=Path, default=Path(cfg.env_file) if cfg.env_file else None)

    # Model configuration
    parser.add_argument("--model", "-m", default=cfg.model, help="model to use for evaluation")
    parser.add_argument("--reasoning", default=cfg.reasoning, help="reasoning level (low/medium/high)")

    # MCP configuration
    parser.add_argument(
        "--mcp-config",
        type=Path,
        default=Path(cfg.mcp_config) if cfg.mcp_config else None,
        help="MCP config file path (default: from manifest or config)"
    )
    parser.add_argument(
        "--mcp-server",
        action="append",
        dest="mcp_servers",
        help="Enable specific MCP server(s) by name (can be repeated). "
             "If not specified, all servers in config are enabled."
    )
    parser.add_argument(
        "--no-mcp",
        action="store_true",
        help="Disable all MCP servers for this run"
    )
    parser.add_argument(
        "--list-mcp-servers",
        action="store_true",
        help="List available MCP servers from config and exit"
    )

    # Hooks configuration
    parser.add_argument(
        "--hooks",
        type=Path,
        default=Path(cfg.hooks) if cfg.hooks else None,
        help="Hooks settings file path (.claude/settings.json format)"
    )

    # Locagent installation (for Harbor container)
    parser.add_argument(
        "--locagent-git-url",
        help="Git URL to install locagent from (e.g., https://github.com/user/codecanvas)"
    )
    parser.add_argument(
        "--locagent-git-ref",
        help="Git ref to checkout (branch, tag, or commit hash)"
    )
    parser.add_argument(
        "--locagent-pip",
        dest="locagent_pip_package",
        help="Pip package spec for locagent (e.g., 'locagent==1.0.0')"
    )
    parser.add_argument(
        "--github-token",
        help="GitHub token for cloning private repos (or set GITHUB_TOKEN env var)"
    )

    # Output format
    parser.add_argument("--json", action="store_true", help="emit results as JSON")
    parser.add_argument("--csv", type=Path, help="export results to CSV file")

    return parser.parse_args(list(argv) if argv is not None else None)


def select_tasks(all_tasks: List[Task], ids: List[str] | None) -> List[Task]:
    if not ids:
        return all_tasks
    wanted = set(ids)
    return [t for t in all_tasks if t.id in wanted]


def export_csv(results: List[RunResult], path: Path) -> None:
    """Export results to a CSV file."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["task_id", "agent", "success", "exit_code", "elapsed_sec", "accuracy", "resolved", "job_dir", "trajectory_json"])
        for r in results:
            writer.writerow([
                r.task_id,
                r.agent_key,
                r.success,
                r.exit_code,
                f"{r.elapsed_sec:.2f}",
                r.accuracy if r.accuracy is not None else "",
                r.resolved if r.resolved is not None else "",
                str(r.job_dir) if r.job_dir else "",
                str(r.trajectory_json) if r.trajectory_json else "",
            ])
    print(f"Results exported to {path}")


def run_cli(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)

    # Handle setup subcommand
    if args.command == "setup":
        from .config import run_setup
        run_setup()
        return 0

    tasks, manifest_config = load_manifest(args.manifest)

    # Resolve MCP config: CLI > manifest > config
    mcp_config_path = args.mcp_config
    if mcp_config_path is None and manifest_config.mcp_config:
        mcp_config_path = Path(manifest_config.mcp_config)

    # Handle --list-mcp-servers
    if args.list_mcp_servers:
        if mcp_config_path and mcp_config_path.exists():
            servers = get_available_servers(mcp_config_path)
            print("Available MCP servers:")
            for s in servers:
                print(f"  - {s}")
        else:
            print("No MCP config found")
        return 0

    tasks = select_tasks(tasks, args.tasks)

    # Resolve env_file: CLI flag > manifest > default
    env_file = args.env_file
    if env_file is None and manifest_config.env_file:
        env_file = manifest_config.env_file
    if env_file is None and DEFAULT_ENV_FILE.exists():
        env_file = DEFAULT_ENV_FILE

    # Load env file for reading config values (also used by HarborRunner)
    from .runner import load_env_file
    env_from_file = load_env_file(env_file)

    # Resolve hooks path: CLI > manifest
    hooks_path = args.hooks
    if hooks_path is None and manifest_config.hooks:
        hooks_path = Path(manifest_config.hooks)

    # Determine MCP settings
    enabled_servers = None if args.no_mcp else args.mcp_servers
    mcp_path = None if args.no_mcp else mcp_config_path

    # Resolve GitHub token: CLI > env file > env var
    import os
    github_token = (
        getattr(args, 'github_token', None) 
        or env_from_file.get('GITHUB_TOKEN') 
        or os.environ.get('GITHUB_TOKEN')
    )

    # Build agent profile
    profile = build_profile(
        key="claude-code",
        model=args.model,
        reasoning=args.reasoning,
        mcp_config_path=mcp_path,
        enabled_mcp_servers=enabled_servers,
        hooks_path=hooks_path,
        locagent_git_url=getattr(args, 'locagent_git_url', None),
        locagent_git_ref=getattr(args, 'locagent_git_ref', None),
        locagent_pip_package=getattr(args, 'locagent_pip_package', None),
        github_token=github_token,
    )

    runner = HarborRunner(
        harbor_bin=args.harbor_bin,
        output_root=args.output_dir,
        attempts=args.attempts,
        retries=args.retries,
        parallel=args.parallel,
        container_env=args.container_env,
        dry_run=args.dry_run,
        extra_flags=args.extra_flag,
        env_file=env_file,
    )

    all_results = runner.run_tasks(tasks, profile)

    if args.json:
        print(json.dumps([r.to_dict() for r in all_results], indent=2))
    else:
        for r in all_results:
            status = "OK" if r.success else "FAIL"
            job_dir = f" dir={r.job_dir.name}" if r.job_dir else ""
            print(f"[{status}] {r.agent_key} {r.task_id} exit={r.exit_code} time={r.elapsed_sec:.1f}s{job_dir}")

        if not args.quiet:
            print_summary(all_results)

    if args.csv:
        export_csv(all_results, args.csv)

    return 0


if __name__ == "__main__":
    sys.exit(run_cli())
