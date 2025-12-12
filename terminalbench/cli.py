from __future__ import annotations

import argparse
import csv
import json
import sys

from pathlib import Path
from typing import Iterable, List

from .agents import make_profiles, resolve_mcp_env, resolve_hooks_path
from .runner import TBRunner, RunResult
from .tasks import load_manifest, Task, DEFAULT_ENV_FILE
from .display import print_summary


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    from .config import load_config
    cfg = load_config()

    parser = argparse.ArgumentParser(description="Terminal-Bench harness")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("setup", help="Interactive configuration wizard")

    parser.add_argument("--agent", choices=["text", "locagent", "codecanvas", "all"], default="all")
    parser.add_argument("--tasks", nargs="*", help="task ids to run; default=all from manifest")
    parser.add_argument("--manifest", type=Path, help="path to tasks manifest (yaml)")
    parser.add_argument("--output-dir", type=Path, default=Path(cfg.output_dir))
    parser.add_argument("--attempts", type=int, default=1, help="number of attempts per task (-k)")
    parser.add_argument("--retries", type=int, default=0, help="number of retries on failure")
    parser.add_argument("--tb-bin", default=cfg.tb_bin, help="tb executable name")
    parser.add_argument("--extra-flag", action="append", default=[], help="extra flag to pass to tb run")
    parser.add_argument("--locagent-mcp", default=cfg.locagent_mcp, help="MCP server URL for locagent")
    parser.add_argument("--canvas-mcp", default=cfg.canvas_mcp, help="MCP server URL for codecanvas")
    parser.add_argument("--hooks", default=cfg.hooks_path, help="Path to Claude Code hooks file")
    parser.add_argument("--env-file", type=Path, default=Path(cfg.env_file) if cfg.env_file else None)
    parser.add_argument("--dry-run", action="store_true", help="do not execute tb, just emit commands")
    parser.add_argument("--quiet", action="store_true", help="suppress live output (for CI)")
    parser.add_argument("--parallel", type=int, default=0, help="run N tasks in parallel (0=sequential)")
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
        writer.writerow(["task_id", "agent", "success", "exit_code", "elapsed_sec", "accuracy", "resolved", "timestamp_dir", "agent_log"])
        for r in results:
            writer.writerow([
                r.task_id,
                r.agent_key,
                r.success,
                r.exit_code,
                f"{r.elapsed_sec:.2f}",
                r.accuracy if r.accuracy is not None else "",
                r.resolved if r.resolved is not None else "",
                str(r.timestamp_dir) if r.timestamp_dir else "",
                str(r.agent_log) if r.agent_log else "",
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
    tasks = select_tasks(tasks, args.tasks)

    # Resolve env_file: CLI flag > manifest > default
    env_file = args.env_file
    if env_file is None and manifest_config.env_file:
        env_file = manifest_config.env_file
    if env_file is None and DEFAULT_ENV_FILE.exists():
        env_file = DEFAULT_ENV_FILE

    locagent_mcp = resolve_mcp_env(args.locagent_mcp, "LOCAGENT_MCP")
    canvas_mcp = resolve_mcp_env(args.canvas_mcp, "CODECANVAS_MCP")
    hooks_path = resolve_hooks_path(args.hooks)
    profiles = make_profiles(locagent_mcp, canvas_mcp, hooks_path, requested=args.agent)

    runner = TBRunner(
        tb_bin=args.tb_bin,
        output_root=args.output_dir,
        attempts=args.attempts,
        retries=args.retries,
        dry_run=args.dry_run,
        extra_flags=args.extra_flag,
        env_file=env_file,
    )

    all_results = []
    for profile in profiles.values():
        if args.parallel > 0:
            all_results.extend(runner.run_tasks_parallel(tasks, profile, max_workers=args.parallel))
        else:
            all_results.extend(runner.run_tasks(tasks, profile))

    if args.json:
        print(json.dumps([r.to_dict() for r in all_results], indent=2))
    else:
        for r in all_results:
            status = "OK" if r.success else "FAIL"
            ts_dir = f" dir={r.timestamp_dir.name}" if r.timestamp_dir else ""
            print(f"[{status}] {r.agent_key} {r.task_id} exit={r.exit_code} time={r.elapsed_sec:.1f}s{ts_dir}")

        if not args.quiet:
            print_summary(all_results)

    if args.csv:
        export_csv(all_results, args.csv)

    return 0


if __name__ == "__main__":
    sys.exit(run_cli())
