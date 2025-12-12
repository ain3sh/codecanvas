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
    timestamp_dir: Optional[Path] = None
    results_json: Optional[Path] = None
    agent_log: Optional[Path] = None
    accuracy: Optional[float] = None
    resolved: Optional[bool] = None

    def to_dict(self) -> Dict:
        data = asdict(self)
        for key in ["timestamp_dir", "results_json", "agent_log"]:
            if data.get(key):
                data[key] = str(data[key])
        return data


class TBRunner:
    """Lightweight orchestrator for running Terminal-Bench via tb CLI."""

    def __init__(
        self,
        tb_bin: str = "tb",
        output_root: Path | str | None = None,
        attempts: int = 1,
        retries: int = 0,
        dry_run: bool = False,
        extra_flags: Optional[Sequence[str]] = None,
        env_file: Path | str | None = None,
    ) -> None:
        self.tb_bin = tb_bin
        self.output_root = Path(output_root).resolve() if output_root else None
        self.attempts = attempts
        self.retries = retries
        self.dry_run = dry_run
        self.extra_flags = list(extra_flags) if extra_flags else []
        self.env_from_file = load_env_file(env_file)

    def _build_command(self, task: Task, profile: AgentProfile, output_dir: Optional[Path]) -> List[str]:
        cmd = [self.tb_bin, "run", "--dataset", task.dataset, "--task-id", task.id]
        cmd.extend(profile.tb_args())
        if self.attempts and self.attempts > 1:
            cmd.extend(["-k", str(self.attempts)])
        if output_dir:
            cmd.extend(["--output-path", str(output_dir)])
        if self.extra_flags:
            cmd.extend(self.extra_flags)
        return cmd

    def _env(self, profile: AgentProfile) -> Dict[str, str]:
        env = os.environ.copy()
        env.update(self.env_from_file)
        env.update(profile.env())
        return env

    def _find_latest_timestamp_dir(self, output_dir: Optional[Path]) -> Optional[Path]:
        """Find the most recent timestamp directory created by tb."""
        if not output_dir or not output_dir.exists():
            return None
        for timestamp_dir in sorted(output_dir.iterdir(), reverse=True):
            if timestamp_dir.is_dir() and "__" in timestamp_dir.name:
                return timestamp_dir
        return None

    def _find_results_json(self, output_dir: Optional[Path]) -> Optional[Path]:
        """Find results.json in tb's nested output structure."""
        timestamp_dir = self._find_latest_timestamp_dir(output_dir)
        if timestamp_dir:
            results_file = timestamp_dir / "results.json"
            if results_file.exists():
                return results_file
        return None

    def _find_agent_log(self, output_dir: Optional[Path], task_id: str) -> Optional[Path]:
        """Find agent.log in tb's nested output structure."""
        timestamp_dir = self._find_latest_timestamp_dir(output_dir)
        if not timestamp_dir:
            return None
        for task_dir in timestamp_dir.iterdir():
            if task_dir.is_dir() and task_dir.name == task_id:
                for trial_dir in task_dir.iterdir():
                    if trial_dir.is_dir():
                        agent_log = trial_dir / "sessions" / "agent.log"
                        if agent_log.exists():
                            return agent_log
        return None

    def _parse_results(self, output_dir: Optional[Path]) -> dict:
        """Parse results.json from tb's nested output structure."""
        results_file = self._find_results_json(output_dir)
        if not results_file:
            return {}
        try:
            return json.loads(results_file.read_text())
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
            raise RuntimeError("ANTHROPIC_API_KEY is required for tb runs.")

        last_result = None
        for attempt in range(1, self.retries + 2):
            start = time.time()
            proc = subprocess.run(cmd, env=env)
            elapsed = time.time() - start

            timestamp_dir = self._find_latest_timestamp_dir(self.output_root)
            results_json = self._find_results_json(self.output_root)
            agent_log = self._find_agent_log(self.output_root, task.id)

            parsed = self._parse_results(self.output_root)
            accuracy = parsed.get("accuracy")
            resolved = parsed.get("n_resolved", 0) > 0

            last_result = RunResult(
                task_id=task.id,
                agent_key=profile.key,
                exit_code=proc.returncode,
                success=proc.returncode == 0,
                command=cmd,
                elapsed_sec=elapsed,
                timestamp_dir=timestamp_dir,
                results_json=results_json,
                agent_log=agent_log,
                accuracy=accuracy,
                resolved=resolved if parsed else None,
            )

            if last_result.success:
                self._update_index(last_result)
                return last_result

            if attempt <= self.retries:
                print(f"[RETRY] {task.id} attempt {attempt + 1}/{self.retries + 1}")

        self._update_index(last_result)
        return last_result

    def run_tasks(self, tasks: Iterable[Task], profile: AgentProfile) -> List[RunResult]:
        """Run tasks sequentially."""
        results: List[RunResult] = []
        for task in tasks:
            result = self._run_single(task, profile)
            results.append(result)
        return results

    def run_tasks_parallel(
        self, tasks: Iterable[Task], profile: AgentProfile, max_workers: int = 4
    ) -> List[RunResult]:
        """Run tasks in parallel using ThreadPoolExecutor."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        task_list = list(tasks)
        results: List[RunResult] = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {
                executor.submit(self._run_single, task, profile): task
                for task in task_list
            }

            for future in as_completed(future_to_task):
                result = future.result()
                results.append(result)

        # Sort results to match original task order
        task_order = {t.id: i for i, t in enumerate(task_list)}
        results.sort(key=lambda r: task_order.get(r.task_id, 0))
        return results
