from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from .agents import AgentProfile
from .tasks import Task
from .config import CONFIG_DIR


def load_env_file(env_file: Path | str | None) -> Dict[str, str]:
    """Load environment variables from a .env file."""
    if not env_file:
        return {}
    path = Path(env_file)
    if not path.exists():
        return {}
    
    env_vars = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            env_vars[key] = value
    return env_vars


@dataclass
class RunResult:
    task_id: str
    agent_key: str
    exit_code: int
    success: bool
    command: List[str]
    elapsed_sec: float
    job_dir: Optional[Path] = None
    results_json: Optional[Path] = None
    trajectory_json: Optional[Path] = None
    accuracy: Optional[float] = None
    resolved: Optional[bool] = None

    def to_dict(self) -> Dict:
        data = asdict(self)
        for key in ["job_dir", "results_json", "trajectory_json"]:
            if data.get(key):
                data[key] = str(data[key])
        return data


class HarborRunner:
    """Lightweight orchestrator for running Terminal-Bench via Harbor CLI."""

    def __init__(
        self,
        harbor_bin: str | None = None,
        output_root: Path | str | None = None,
        attempts: int = 1,
        retries: int = 0,
        parallel: int = 0,
        container_env: str = "docker",
        dry_run: bool = False,
        extra_flags: Optional[Sequence[str]] = None,
        env_file: Path | str | None = None,
        build_cache_path: Path | None = None,
    ) -> None:
        self.harbor_bin = harbor_bin  # None = use uvx (default)
        self.output_root = Path(output_root).resolve() if output_root else None
        self.attempts = attempts
        self.retries = retries
        self.parallel = parallel
        self.container_env = container_env
        self.dry_run = dry_run
        self.extra_flags = list(extra_flags) if extra_flags else []
        self.env_from_file = load_env_file(env_file)
        self.build_cache_path = build_cache_path or CONFIG_DIR / "build-hash.json"

    # ------------------------------------------------------------------
    # Build fingerprint helpers
    # ------------------------------------------------------------------

    def _compute_build_fingerprint(self, profiles: List[AgentProfile]) -> str:
        template_path = Path(__file__).parent / "install-claude-code-mcp.sh.j2"
        template_bytes = template_path.read_bytes() if template_path.exists() else b""

        # Combine unique relevant attributes across profiles to avoid stale builds.
        mcp_sources = sorted({p.mcp_git_source or "" for p in profiles})
        claude_versions = sorted({p.claude_version or "" for p in profiles})

        # GitHub token presence can affect git clone auth; hash only presence, not value.
        github_token_present = bool(
            self.env_from_file.get("GITHUB_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
            or any("GITHUB_TOKEN" in p.extra_env for p in profiles)
        )

        h = hashlib.sha256()
        h.update(template_bytes)
        for src in mcp_sources:
            h.update(src.encode())
        for cv in claude_versions:
            h.update(cv.encode())
        h.update(b"gh" if github_token_present else b"nogh")
        return h.hexdigest()

    def _load_cached_fingerprint(self) -> str | None:
        if not self.build_cache_path.exists():
            return None
        try:
            data = json.loads(self.build_cache_path.read_text())
            return data.get("fingerprint")
        except Exception:
            return None

    def _store_fingerprint(self, fingerprint: str) -> None:
        try:
            self.build_cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.build_cache_path.write_text(json.dumps({"fingerprint": fingerprint}, indent=2))
        except Exception:
            # Cache failures should not block execution
            pass

    def _build_command(
        self,
        task: Task,
        profile: AgentProfile,
        output_dir: Optional[Path],
        force_build: bool,
        keep_environment: bool,
    ) -> List[str]:
        if self.harbor_bin:
            cmd = [self.harbor_bin, "run"]
        else:
            # --python 3.13: modal has hardcoded runtime check blocking 3.14+
            cmd = ["uvx", "--python", "3.13", "harbor", "run"]
        cmd.extend(["-d", task.dataset, "-t", task.id])
        cmd.extend(profile.harbor_args())
        if self.attempts > 1:
            cmd.extend(["--n-attempts", str(self.attempts)])
        if output_dir:
            cmd.extend(["--jobs-dir", str(output_dir)])
        if self.parallel > 0:
            cmd.extend(["-n", str(self.parallel)])
        if self.container_env:
            cmd.extend(["--env", self.container_env])
        # Keep environments by default to avoid rebuild churn (unless user explicitly overrides)
        if keep_environment and not any(flag in {"--delete", "--no-delete"} for flag in self.extra_flags):
            cmd.append("--no-delete")
        if force_build:
            cmd.append("--force-build")
        if self.extra_flags:
            cmd.extend(self.extra_flags)
        return cmd

    def _env(self, profile: AgentProfile) -> Dict[str, str]:
        env = os.environ.copy()
        env.update(self.env_from_file)
        env.update(profile.env())
        return env

    def _find_latest_job_dir(self, output_dir: Optional[Path]) -> Optional[Path]:
        """Find the most recent job directory created by Harbor."""
        if not output_dir or not output_dir.exists():
            return None
        for job_dir in sorted(output_dir.iterdir(), reverse=True):
            if job_dir.is_dir():
                return job_dir
        return None

    def _find_result_json(self, job_dir: Optional[Path]) -> Optional[Path]:
        """Find result.json in Harbor's output structure."""
        if job_dir:
            result_file = job_dir / "result.json"
            if result_file.exists():
                return result_file
        return None

    def _find_trajectory(self, job_dir: Optional[Path], task_id: str) -> Optional[Path]:
        """Find trajectory.json in Harbor's output structure."""
        if not job_dir:
            return None
        # Harbor structure: {job_dir}/{task_id}__*/agent/trajectory.json
        for trial_dir in job_dir.iterdir():
            if trial_dir.is_dir() and trial_dir.name.startswith(f"{task_id}__"):
                trajectory = trial_dir / "agent" / "trajectory.json"
                if trajectory.exists():
                    return trajectory
        return None

    def _parse_results(self, job_dir: Optional[Path], task_id: str) -> dict:
        """Parse result.json and extract metrics for task."""
        result_file = self._find_result_json(job_dir)
        if not result_file:
            return {}
        try:
            data = json.loads(result_file.read_text())
            stats = data.get("stats", {}).get("evals", {})
            # Find mean reward from any eval that has this task
            for eval_name, eval_data in stats.items():
                metrics = eval_data.get("metrics", [])
                if metrics:
                    return {"mean_reward": metrics[0].get("mean")}
            return {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _update_index(self, result: RunResult) -> None:
        """Update index.json with the run result."""
        if not self.output_root:
            return
        index_file = self.output_root / "index.json"
        runs = []
        if index_file.exists():
            try:
                runs = json.loads(index_file.read_text()).get("runs", [])
            except (json.JSONDecodeError, OSError):
                runs = []
        runs.append(result.to_dict())
        index_file.write_text(json.dumps({"runs": runs}, indent=2))

    def _run_single(
        self,
        task: Task,
        profile: AgentProfile,
        force_build: bool,
        keep_environment: bool,
    ) -> RunResult:
        """Run a single task with retry logic."""
        if self.output_root:
            self.output_root.mkdir(parents=True, exist_ok=True)

        cmd = self._build_command(
            task,
            profile,
            self.output_root,
            force_build=force_build,
            keep_environment=keep_environment,
        )
        env = self._env(profile)

        if self.dry_run:
            print(f"[DRY-RUN] {' '.join(cmd)}")
            env_vars = profile.env()
            if env_vars:
                print(f"          env: {env_vars}")
            return RunResult(
                task_id=task.id,
                agent_key=profile.key,
                exit_code=0,
                success=True,
                command=cmd,
                elapsed_sec=0.0,
            )

        if "ANTHROPIC_API_KEY" not in env:
            raise RuntimeError("ANTHROPIC_API_KEY is required for Harbor runs.")

        last_result = None
        for attempt in range(1, self.retries + 2):
            start = time.time()
            proc = subprocess.run(cmd, env=env)
            elapsed = time.time() - start

            job_dir = self._find_latest_job_dir(self.output_root)
            result_json = self._find_result_json(job_dir)
            trajectory_json = self._find_trajectory(job_dir, task.id)

            parsed = self._parse_results(job_dir, task.id)
            mean_reward = parsed.get("mean_reward")

            last_result = RunResult(
                task_id=task.id,
                agent_key=profile.key,
                exit_code=proc.returncode,
                success=proc.returncode == 0,
                command=cmd,
                elapsed_sec=elapsed,
                job_dir=job_dir,
                results_json=result_json,
                trajectory_json=trajectory_json,
                accuracy=mean_reward,
                resolved=mean_reward == 1.0 if mean_reward is not None else None,
            )

            if last_result.success:
                self._update_index(last_result)
                return last_result

            if attempt <= self.retries:
                print(f"[RETRY] {task.id} attempt {attempt + 1}/{self.retries + 1}")

        self._update_index(last_result)
        return last_result

    def run_tasks(
        self,
        tasks: Iterable[Task],
        profile: AgentProfile,
        force_build: bool = False,
        keep_environment: bool = True,
    ) -> List[RunResult]:
        """Run tasks sequentially (Harbor handles parallelization internally via -n flag)."""
        results: List[RunResult] = []
        for task in tasks:
            result = self._run_single(task, profile, force_build, keep_environment)
            # Only force build on first run in a batch
            force_build = False
            results.append(result)
        return results

    def run_profiles(
        self,
        tasks: Iterable[Task],
        profiles: List[AgentProfile],
        profiles_parallel: int = 0,
    ) -> List[RunResult]:
        """Run a list of profiles over the tasks, reusing environment builds when possible.

        If profiles_parallel > 0, runs profiles concurrently after ensuring any required rebuild
        is completed by the first profile.
        """
        if not profiles:
            return []

        fingerprint = self._compute_build_fingerprint(profiles)
        cached = self._load_cached_fingerprint()
        env_force_rebuild = os.environ.get("TERMINALBENCH_FORCE_REBUILD")
        needs_rebuild = env_force_rebuild or (fingerprint != cached)

        all_results: List[RunResult] = []

        def run_profile(idx_profile: int, profile: AgentProfile, force_build_flag: bool) -> List[RunResult]:
            return self.run_tasks(
                tasks,
                profile,
                force_build=force_build_flag,
                keep_environment=True,
            )

        # Always run first profile synchronously to perform any needed rebuild safely.
        first_force = bool(needs_rebuild)
        all_results.extend(run_profile(0, profiles[0], first_force))

        remaining = profiles[1:]
        if remaining:
            if profiles_parallel and profiles_parallel > 0:
                from concurrent.futures import ThreadPoolExecutor, as_completed

                with ThreadPoolExecutor(max_workers=profiles_parallel) as pool:
                    futures = [pool.submit(run_profile, i + 1, p, False) for i, p in enumerate(remaining)]
                    for fut in as_completed(futures):
                        all_results.extend(fut.result())
            else:
                for i, profile in enumerate(remaining, start=1):
                    all_results.extend(run_profile(i, profile, False))

        # Cache new fingerprint after successful scheduling
        if fingerprint:
            self._store_fingerprint(fingerprint)

        return all_results
