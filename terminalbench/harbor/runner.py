from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from terminalbench.core.config import CONFIG_DIR
from terminalbench.core.profiles import AgentProfile
from terminalbench.core.tasks import Task

logger = logging.getLogger(__name__)


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
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
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
        registry_path: Path | None = None,
        artifact_targets: Optional[Sequence[str]] = None,
        run_timeout_sec: int | None = None,
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
        self.registry_path = Path(registry_path) if registry_path else None
        self.artifact_targets = list(artifact_targets) if artifact_targets else []
        self._index_lock = threading.Lock()
        env_timeout = os.environ.get("TERMINALBENCH_RUN_TIMEOUT_SEC")

        resolved_timeout: int | None
        if run_timeout_sec is None:
            if env_timeout:
                try:
                    resolved_timeout = int(env_timeout)
                except ValueError:
                    resolved_timeout = 585
            else:
                resolved_timeout = 585
        else:
            resolved_timeout = run_timeout_sec

        if resolved_timeout <= 0:
            resolved_timeout = None

        self.run_timeout_sec = resolved_timeout

    # ------------------------------------------------------------------
    # Build fingerprint helpers
    # ------------------------------------------------------------------

    def _compute_profile_fingerprint(self, profile: AgentProfile) -> str:
        """Fingerprint a profile's install-affecting attributes for build caching."""

        template_path = Path(__file__).parent / "install-claude-code-utils.sh.j2"
        template_bytes = template_path.read_bytes() if template_path.exists() else b""

        github_token_present = bool(
            self.env_from_file.get("GITHUB_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
            or ("GITHUB_TOKEN" in profile.extra_env)
        )

        h = hashlib.sha256()
        h.update(template_bytes)
        h.update((profile.mcp_git_source or "").encode())
        h.update((profile.claude_version or "").encode())
        h.update((profile.mcp_extras or "").encode())
        h.update(b"r1" if profile.install_r_languageserver else b"r0")
        h.update(b"gh" if github_token_present else b"nogh")
        return h.hexdigest()

    def _load_cached_fingerprints(self) -> dict[str, str]:
        if not self.build_cache_path.exists():
            return {}
        try:
            data = json.loads(self.build_cache_path.read_text())
            # Backward compatibility: old format was either a raw string or {"fingerprint": "..."}
            if isinstance(data, str):
                return {"__legacy__": data}
            if isinstance(data, dict):
                if "fingerprints" in data and isinstance(data["fingerprints"], dict):
                    return data["fingerprints"]
                if "fingerprint" in data and isinstance(data["fingerprint"], str):
                    return {"__legacy__": data["fingerprint"]}
            return {}
        except Exception:
            return {}

    def _store_fingerprints(self, fingerprints: dict[str, str]) -> None:
        try:
            self.build_cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.build_cache_path.write_text(json.dumps({"fingerprints": fingerprints}, indent=2))
        except Exception:
            # Cache failures should not block execution
            pass

    def _build_job_command(self, config_path: Path) -> List[str]:
        if self.harbor_bin:
            cmd = [self.harbor_bin, "run"]
        else:
            # --python 3.13: modal has hardcoded runtime check blocking 3.14+
            cmd = ["uvx", "--python", "3.13", "harbor", "run"]
        cmd.extend(["-c", str(config_path)])
        if self.extra_flags:
            cmd.extend(self.extra_flags)
        return cmd

    def _env(self, profiles: Iterable[AgentProfile]) -> Dict[str, str]:
        env = os.environ.copy()
        env.update(self.env_from_file)
        for profile in profiles:
            env.update(profile.env())
        return env

    def _parse_elapsed(self, start: Optional[str], finish: Optional[str]) -> Optional[float]:
        if not start or not finish:
            return None
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            finish_dt = datetime.fromisoformat(finish.replace("Z", "+00:00"))
            return (finish_dt - start_dt).total_seconds()
        except ValueError:
            return None

    def _collect_job_results(self, *, job_dir: Path, command: List[str]) -> List[RunResult]:
        results: List[RunResult] = []
        if not job_dir.exists():
            return results

        for trial_dir in sorted(job_dir.iterdir()):
            if not trial_dir.is_dir():
                continue
            result_path = trial_dir / "result.json"
            if not result_path.exists():
                continue
            try:
                data = json.loads(result_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            task_id = str(data.get("task_name") or "").strip() or trial_dir.name.split("__")[0]
            agent_key = "unknown"
            config = data.get("config") if isinstance(data, dict) else None
            if isinstance(config, dict):
                agent_cfg = config.get("agent")
                if isinstance(agent_cfg, dict) and agent_cfg.get("name"):
                    agent_key = str(agent_cfg.get("name"))
            trajectory = trial_dir / "agent" / "trajectory.json"
            trajectory_json = trajectory if trajectory.exists() else None
            reward = None
            verifier = data.get("verifier_result") or {}
            rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
            if isinstance(rewards, dict):
                reward = rewards.get("reward")
            elapsed = self._parse_elapsed(data.get("started_at"), data.get("finished_at"))

            results.append(
                RunResult(
                    task_id=task_id,
                    agent_key=agent_key,
                    exit_code=0 if result_path.exists() else 1,
                    success=reward == 1.0 if reward is not None else False,
                    command=command,
                    elapsed_sec=elapsed or 0.0,
                    job_dir=job_dir,
                    results_json=result_path,
                    trajectory_json=trajectory_json,
                    accuracy=reward,
                    resolved=reward == 1.0 if reward is not None else None,
                )
            )

        return results

    def _index_key(self, entry: Dict) -> str:
        for key in ("results_json", "trajectory_json"):
            value = entry.get(key)
            if value:
                return f"{key}:{value}"
        command = " ".join(entry.get("command") or [])
        return f"fallback:{entry.get('task_id')}:{entry.get('agent_key')}:{command}"

    def _update_index(self, result: RunResult) -> None:
        """Update index.json with the run result."""
        if not self.output_root:
            return
        index_file = self.output_root / "index.json"
        with self._index_lock:
            runs = []
            if index_file.exists():
                try:
                    runs = json.loads(index_file.read_text()).get("runs", [])
                except (json.JSONDecodeError, OSError):
                    runs = []
            existing_keys = {self._index_key(entry) for entry in runs}
            entry = result.to_dict()
            key = self._index_key(entry)
            if key in existing_keys:
                return
            runs.append(entry)
            index_file.write_text(json.dumps({"runs": runs}, indent=2))

    def _start_index_watcher(self, job_dir: Path, command: List[str]) -> tuple[threading.Event, threading.Thread]:
        stop_event = threading.Event()

        def _poll() -> None:
            while not stop_event.is_set():
                try:
                    results = self._collect_job_results(job_dir=job_dir, command=command)
                    for result in results:
                        self._update_index(result)
                except Exception:
                    logger.exception(
                        "Index watcher failed (job_dir=%s, command=%s)",
                        job_dir,
                        " ".join(command),
                    )
                stop_event.wait(5)

        thread = threading.Thread(target=_poll, name="harbor-index-watcher", daemon=True)
        thread.start()
        return stop_event, thread

    def _group_tasks_by_dataset(self, tasks: Iterable[Task]) -> Dict[str, List[str]]:
        grouped: Dict[str, List[str]] = {}
        for task in tasks:
            grouped.setdefault(task.dataset, []).append(task.id)
        return grouped

    def _split_dataset(self, dataset: str) -> tuple[str, Optional[str]]:
        if "@" in dataset:
            name, version = dataset.rsplit("@", 1)
            return name, version
        return dataset, None

    def _build_job_config(
        self,
        *,
        job_name: str,
        tasks: Iterable[Task],
        profiles: Iterable[AgentProfile],
        force_build: bool,
    ) -> dict:
        datasets = []
        grouped = self._group_tasks_by_dataset(tasks)
        for dataset_spec, task_ids in grouped.items():
            name, version = self._split_dataset(dataset_spec)
            registry: dict
            if self.registry_path:
                registry = {"path": str(self.registry_path)}
            else:
                registry = {"url": "https://raw.githubusercontent.com/laude-institute/harbor/main/registry.json"}
            datasets.append(
                {
                    "registry": registry,
                    "name": name,
                    "version": version,
                    "task_names": task_ids,
                }
            )

        agents = []
        for profile in profiles:
            agent_kwargs: dict[str, object] = {}
            if profile.mcp_config_json:
                try:
                    agent_kwargs["mcp_config"] = json.loads(profile.mcp_config_json)
                except json.JSONDecodeError:
                    agent_kwargs["mcp_config"] = profile.mcp_config_json
            if profile.hooks_config_json:
                try:
                    agent_kwargs["hooks_config"] = json.loads(profile.hooks_config_json)
                except json.JSONDecodeError:
                    agent_kwargs["hooks_config"] = profile.hooks_config_json
            if profile.reasoning:
                agent_kwargs["reasoning"] = profile.reasoning
            if profile.claude_version:
                agent_kwargs["claude_version"] = profile.claude_version
            if profile.mcp_git_source:
                agent_kwargs["mcp_git_source"] = profile.mcp_git_source
            if profile.mcp_extras:
                agent_kwargs["mcp_extras"] = profile.mcp_extras
            agent_kwargs["install_r_languageserver"] = profile.install_r_languageserver
            if profile.system_prompt:
                agent_kwargs["system_prompt"] = profile.system_prompt

            agents.append(
                {
                    "name": profile.key,
                    "import_path": "terminalbench.harbor.agent:ClaudeCodeMCP",
                    "model_name": profile.model,
                    "kwargs": agent_kwargs,
                }
            )

        config: dict[str, object] = {
            "job_name": job_name,
            "jobs_dir": str(self.output_root) if self.output_root else "jobs",
            "n_attempts": self.attempts,
            "timeout_multiplier": 1.0,
            "debug": False,
            "orchestrator": {
                "type": "local",
                "n_concurrent_trials": self.parallel if self.parallel > 0 else 4,
                "quiet": False,
                "retry": {"max_retries": self.retries},
            },
            "environment": {
                "type": self.container_env,
                "force_build": force_build,
                "delete": False,
            },
            "verifier": {"disable": False},
            "metrics": [],
            "agents": agents,
            "datasets": datasets,
            "tasks": [],
        }
        return config

    def _run_job(
        self,
        *,
        tasks: Iterable[Task],
        profiles: Iterable[AgentProfile],
        force_build: bool,
        job_name: str,
    ) -> List[RunResult]:
        if self.output_root:
            self.output_root.mkdir(parents=True, exist_ok=True)

        profiles_list = list(profiles)
        env = self._env(profiles_list)
        if "ANTHROPIC_API_KEY" not in env:
            raise RuntimeError("ANTHROPIC_API_KEY is required for Harbor runs.")

        config = self._build_job_config(job_name=job_name, tasks=tasks, profiles=profiles_list, force_build=force_build)
        config_path = (self.output_root or Path.cwd()) / f"{job_name}.job.json"
        config_path.write_text(json.dumps(config, indent=2))

        if self.output_root and self.artifact_targets:
            try:
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "terminalbench.harbor.mirror_artifacts",
                        "--runs-dir",
                        str(self.output_root),
                        "--job-name",
                        job_name,
                        "--targets",
                        *self.artifact_targets,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except Exception:
                pass

        cmd = self._build_job_command(config_path)
        if self.dry_run:
            print(f"[DRY-RUN] {' '.join(cmd)}")
            return [
                RunResult(
                    task_id="",
                    agent_key="",
                    exit_code=0,
                    success=True,
                    command=cmd,
                    elapsed_sec=0.0,
                )
            ]

        start = time.time()
        job_dir = (self.output_root / job_name) if self.output_root else Path(job_name)
        job_dir.mkdir(parents=True, exist_ok=True)
        stop_event, watcher = self._start_index_watcher(job_dir, cmd)

        returncode = 0
        try:
            proc = subprocess.run(cmd, env=env, timeout=self.run_timeout_sec)
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            returncode = 124
        except (FileNotFoundError, PermissionError, OSError) as exc:
            returncode = 127
            print(f"[harbor] Failed to run command: {exc}", file=sys.stderr)
        except Exception as exc:
            returncode = 1
            print(f"[harbor] Unexpected error during run: {exc}", file=sys.stderr)
        finally:
            stop_event.set()
            watcher.join(timeout=5)

        elapsed = time.time() - start

        results = self._collect_job_results(job_dir=job_dir, command=cmd)
        if not results:
            results = [
                RunResult(
                    task_id="",
                    agent_key="",
                    exit_code=returncode,
                    success=False,
                    command=cmd,
                    elapsed_sec=elapsed,
                    job_dir=job_dir if job_dir.exists() else None,
                )
            ]

        for result in results:
            if result.elapsed_sec == 0.0:
                result.elapsed_sec = elapsed
            self._update_index(result)
        return results

    def run_profiles(
        self,
        tasks: Iterable[Task],
        profiles: List[AgentProfile],
        profiles_parallel: int = 0,
    ) -> List[RunResult]:
        """Run a single Harbor job containing all requested profiles."""
        if not profiles:
            return []

        cached_map = self._load_cached_fingerprints()
        env_force_rebuild = os.environ.get("TERMINALBENCH_FORCE_REBUILD")

        profile_fingerprints = {p.key: self._compute_profile_fingerprint(p) for p in profiles}

        def profile_needs_rebuild(profile: AgentProfile) -> bool:
            if env_force_rebuild:
                return True
            cached = cached_map.get(profile.key)
            return cached != profile_fingerprints[profile.key]

        force_build = any(profile_needs_rebuild(p) for p in profiles)
        if env_force_rebuild:
            force_build = True

        run_timestamp = datetime.now().strftime("%Y-%m-%d__%H-%M-%S")
        job_name = f"{run_timestamp}__profiles"

        results = self._run_job(
            tasks=tasks,
            profiles=profiles,
            force_build=force_build,
            job_name=job_name,
        )

        for profile in profiles:
            cached_map[profile.key] = profile_fingerprints[profile.key]
        self._store_fingerprints(cached_map)

        return results
