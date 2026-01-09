from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

from terminalbench.core.config import get_batch_dir
from terminalbench.core.profiles import AgentProfile, build_profile, discover_mcp_usage_prompts, get_available_servers
from terminalbench.core.tasks import DEFAULT_ENV_FILE, Task, load_manifest
from terminalbench.harbor.runner import HarborRunner, RunResult
from terminalbench.ui.display import print_summary


def _split_config_sets(argv: List[str]) -> Tuple[List[str], List[List[str]]]:
    """Extract repeated --config-set/-C groups from argv for separate parsing."""
    base: List[str] = []
    sets: List[List[str]] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in {"--config-set", "-C"}:
            current: List[str] = []
            i += 1
            while i < len(argv) and argv[i] not in {"--config-set", "-C"}:
                current.append(argv[i])
                i += 1
            sets.append(current)
        else:
            base.append(tok)
            i += 1
    return base, sets


def _config_set_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--key")
    parser.add_argument("--model")
    parser.add_argument("--reasoning")
    parser.add_argument("--claude-version")
    parser.add_argument("--mcp-server", action="append", dest="mcp_servers")
    parser.add_argument("--no-mcp", action="store_true")
    parser.add_argument("--hooks", type=Path)
    parser.add_argument("--mcp-config", type=Path)
    parser.add_argument("--mcp-git-source")
    parser.add_argument("--github-token")
    return parser


def parse_args(argv: Iterable[str] | None = None) -> Tuple[argparse.Namespace, List[argparse.Namespace]]:
    from terminalbench.core.config import load_config

    cfg = load_config()

    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    base_argv, config_sets_tokens = _split_config_sets(raw_argv or [])

    parser = argparse.ArgumentParser(description="Terminal-Bench harness")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("setup", help="Interactive configuration wizard")

    # Task selection
    parser.add_argument("--tasks", nargs="*", help="task ids to run; default=all from manifest")
    parser.add_argument("--manifest", type=Path, help="path to tasks manifest (yaml)")

    # Output and execution
    parser.add_argument("--output-dir", type=Path, default=cfg.output_dir, help="base results directory")
    parser.add_argument("--batch", type=int, default=None, help="batch ID (default: auto-increment to next available)")
    parser.add_argument("--attempts", type=int, default=1, help="number of attempts per task (-k)")
    parser.add_argument("--retries", type=int, default=0, help="number of retries on failure")
    parser.add_argument("--dry-run", action="store_true", help="do not execute harbor, just emit commands")
    parser.add_argument("--quiet", action="store_true", help="suppress live output (for CI)")
    parser.add_argument("--parallel", "-n", type=int, default=0, help="parallel workers (passed to harbor -n)")

    # Harbor configuration
    parser.add_argument("--harbor-bin", default=cfg.harbor_bin, help="harbor executable (default: use uvx)")
    parser.add_argument(
        "--container-env",
        default=cfg.container_env,
        help="container runtime (docker|daytona|modal|e2b)",
    )
    parser.add_argument(
        "--extra-flag",
        action="append",
        default=[],
        help="extra flag to pass to harbor run (use = for flags with values)",
    )
    parser.add_argument(
        "--registry-path",
        type=Path,
        help="local registry.json path (workaround for broken remote registry)",
    )
    parser.add_argument("--profiles-parallel", type=int, default=0, help="parallel profile runs (0=sequential)")
    parser.add_argument("--env-file", type=Path, default=Path(cfg.env_file) if cfg.env_file else None)

    # Model configuration
    parser.add_argument("--model", "-m", default=cfg.model, help="model to use for evaluation")
    parser.add_argument("--reasoning", default=cfg.reasoning, help="reasoning level (low/medium/high)")
    parser.add_argument("--claude-version", help="Claude Code version to install (optional)")

    # MCP configuration
    parser.add_argument(
        "--mcp-config",
        type=Path,
        default=Path(cfg.mcp_config) if cfg.mcp_config else None,
        help="MCP config file path (default: from manifest or config)",
    )
    parser.add_argument(
        "--mcp-server",
        action="append",
        dest="mcp_servers",
        help="Enable specific MCP server(s) by name (can be repeated). "
        "If not specified, all servers in config are enabled.",
    )
    parser.add_argument("--no-mcp", action="store_true", help="Disable all MCP servers for this run")
    parser.add_argument(
        "--list-mcp-servers", action="store_true", help="List available MCP servers from config and exit"
    )

    # Hooks configuration
    parser.add_argument(
        "--hooks",
        type=Path,
        default=Path(cfg.hooks) if cfg.hooks else None,
        help="Hooks settings file path (.claude/settings.json format)",
    )

    # MCP installation from git (for Harbor container)
    parser.add_argument(
        "--mcp-git-source",
        help="Git URL to install MCP servers from (assumes 'main' branch). E.g., https://github.com/user/codecanvas",
    )
    parser.add_argument("--github-token", help="GitHub token for cloning private repos (or set GITHUB_TOKEN env var)")

    # Output format
    parser.add_argument("--json", action="store_true", help="emit results as JSON")
    parser.add_argument("--csv", type=Path, help="export results to CSV file")

    args = parser.parse_args(base_argv)

    config_sets: List[argparse.Namespace] = []
    if config_sets_tokens:
        cs_parser = _config_set_parser()
        for tokens in config_sets_tokens:
            config_sets.append(cs_parser.parse_args(tokens))

    return args, config_sets


def select_tasks(all_tasks: List[Task], ids: List[str] | None) -> List[Task]:
    if not ids:
        return all_tasks
    wanted = set(ids)
    return [t for t in all_tasks if t.id in wanted]


def export_csv(results: List[RunResult], path: Path) -> None:
    """Export results to a CSV file."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "task_id",
                "agent",
                "success",
                "exit_code",
                "elapsed_sec",
                "accuracy",
                "resolved",
                "job_dir",
                "trajectory_json",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r.task_id,
                    r.agent_key,
                    r.success,
                    r.exit_code,
                    f"{r.elapsed_sec:.2f}",
                    r.accuracy if r.accuracy is not None else "",
                    r.resolved if r.resolved is not None else "",
                    str(r.job_dir) if r.job_dir else "",
                    str(r.trajectory_json) if r.trajectory_json else "",
                ]
            )
    print(f"Results exported to {path}")


def run_cli(argv: Iterable[str] | None = None) -> int:
    args, config_sets = parse_args(argv)

    # Handle setup subcommand
    if args.command == "setup":
        from terminalbench.core.config import run_setup

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
    from terminalbench.harbor.runner import load_env_file

    env_from_file = load_env_file(env_file)

    # Resolve hooks path: CLI > manifest
    hooks_path = args.hooks
    if hooks_path is None and manifest_config.hooks:
        hooks_path = Path(manifest_config.hooks)

    # Resolve GitHub token: CLI > env file > env var
    import os

    github_token = (
        getattr(args, "github_token", None) or env_from_file.get("GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    )

    def build_profile_from_set(set_ns: argparse.Namespace | None, default_key: str) -> AgentProfile:
        model = set_ns.model if set_ns and getattr(set_ns, "model", None) else args.model
        reasoning = set_ns.reasoning if set_ns and getattr(set_ns, "reasoning", None) else args.reasoning
        claude_version = (
            set_ns.claude_version
            if set_ns and getattr(set_ns, "claude_version", None)
            else getattr(args, "claude_version", None)
        )

        # Resolve MCP specifics
        no_mcp_flag = bool(set_ns.no_mcp) if set_ns and hasattr(set_ns, "no_mcp") else args.no_mcp
        set_mcp_servers = getattr(set_ns, "mcp_servers", None) if set_ns else args.mcp_servers
        local_enabled_servers = None if no_mcp_flag else set_mcp_servers

        set_mcp_config = getattr(set_ns, "mcp_config", None) if set_ns else None
        local_mcp_path = None if no_mcp_flag else (set_mcp_config or mcp_config_path)

        set_hooks = getattr(set_ns, "hooks", None) if set_ns else None
        local_hooks_path = set_hooks or hooks_path

        set_git_source = getattr(set_ns, "mcp_git_source", None) if set_ns else None
        local_git_source = set_git_source or getattr(args, "mcp_git_source", None)

        set_github_token = getattr(set_ns, "github_token", None) if set_ns else None
        local_github_token = set_github_token or github_token

        # Auto-discover system prompt per config
        system_prompt = None
        if local_enabled_servers:
            system_prompt = discover_mcp_usage_prompts(local_enabled_servers)

        key = (getattr(set_ns, "key", None) if set_ns else None) or default_key

        return build_profile(
            key=key,
            model=model,
            reasoning=reasoning,
            claude_version=claude_version,
            mcp_config_path=local_mcp_path,
            enabled_mcp_servers=local_enabled_servers,
            hooks_path=local_hooks_path,
            mcp_git_source=local_git_source,
            github_token=local_github_token,
            system_prompt=system_prompt,
        )

    profiles: List[AgentProfile] = []
    if config_sets:
        for idx, cs in enumerate(config_sets):
            default_key = cs.key or (
                "nomcp"
                if getattr(cs, "no_mcp", False)
                else ("-".join(cs.mcp_servers) if cs.mcp_servers else f"profile{idx + 1}")
            )
            profiles.append(build_profile_from_set(cs, default_key))
    else:
        default_key = "nomcp" if args.no_mcp else ("-".join(args.mcp_servers) if args.mcp_servers else "claude-code")
        profiles.append(build_profile_from_set(None, default_key))

    # Resolve batch directory
    batch_dir = get_batch_dir(args.output_dir, args.batch)
    runs_dir = batch_dir / "runs"

    runner = HarborRunner(
        harbor_bin=args.harbor_bin,
        output_root=runs_dir,
        attempts=args.attempts,
        retries=args.retries,
        parallel=args.parallel,
        container_env=args.container_env,
        dry_run=args.dry_run,
        extra_flags=args.extra_flag,
        env_file=env_file,
        registry_path=args.registry_path,
    )

    all_results = runner.run_profiles(tasks, profiles, profiles_parallel=args.profiles_parallel)

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
