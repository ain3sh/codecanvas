from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from .agents import AgentProfile
from .tasks import Task


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

    def _build_command(self, task: Task, profile: AgentProfile, output_dir: Optional[Path]) -> List[str]:
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

    def _run_single(self, task: Task, profile: AgentProfile) -> RunResult:
        """Run a single task with retry logic."""
        if self.output_root:
            self.output_root.mkdir(parents=True, exist_ok=True)

        cmd = self._build_command(task, profile, self.output_root)
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

    def run_tasks(self, tasks: Iterable[Task], profile: AgentProfile) -> List[RunResult]:
        """Run tasks sequentially (Harbor handles parallelization internally via -n flag)."""
        results: List[RunResult] = []
        for task in tasks:
            result = self._run_single(task, profile)
            results.append(result)
        return results
