"""
ATIF Trajectory Parser - Parse Harbor's trajectory.json and related outputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ToolCall:
    """Represents a single tool invocation."""

    tool_call_id: str
    function_name: str
    arguments: Dict[str, Any]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolCall:
        return cls(
            tool_call_id=data.get("tool_call_id", ""),
            function_name=data.get("function_name", ""),
            arguments=data.get("arguments", {}),
        )


@dataclass
class ObservationResult:
    """Result from a tool call."""

    source_call_id: str
    content: str
    error: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ObservationResult:
        return cls(
            source_call_id=data.get("source_call_id", ""),
            content=data.get("content", ""),
            error=data.get("error"),
        )


@dataclass
class StepMetrics:
    """Token/cost metrics for a single step."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StepMetrics:
        if not data:
            return cls()
        return cls(
            prompt_tokens=data.get("prompt_tokens", 0),
            completion_tokens=data.get("completion_tokens", 0),
            cached_tokens=data.get("cached_tokens", 0),
            cost_usd=data.get("cost_usd", 0.0),
        )


@dataclass
class Step:
    """A single step in the trajectory."""

    step_id: int
    timestamp: str
    source: str  # 'user', 'agent', 'system'
    message: str
    model_name: Optional[str] = None
    reasoning_content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    observation_results: List[ObservationResult] = field(default_factory=list)
    metrics: Optional[StepMetrics] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Step:
        tool_calls = []
        if data.get("tool_calls"):
            tool_calls = [ToolCall.from_dict(tc) for tc in data["tool_calls"]]

        obs_results = []
        if data.get("observation", {}).get("results"):
            obs_results = [ObservationResult.from_dict(r) for r in data["observation"]["results"]]

        metrics = None
        if data.get("metrics"):
            metrics = StepMetrics.from_dict(data["metrics"])

        return cls(
            step_id=data.get("step_id", 0),
            timestamp=data.get("timestamp", ""),
            source=data.get("source", ""),
            message=data.get("message", ""),
            model_name=data.get("model_name"),
            reasoning_content=data.get("reasoning_content"),
            tool_calls=tool_calls,
            observation_results=obs_results,
            metrics=metrics,
            extra=data.get("extra", {}),
        )

    @property
    def is_agent_step(self) -> bool:
        return self.source == "agent"

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class AgentInfo:
    """Agent metadata from trajectory."""

    name: str
    version: str
    model_name: str
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentInfo:
        return cls(
            name=data.get("name", ""),
            version=data.get("version", ""),
            model_name=data.get("model_name", ""),
            extra=data.get("extra", {}),
        )


@dataclass
class FinalMetrics:
    """Aggregate metrics for the trajectory."""

    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cached_tokens: int = 0
    total_cost_usd: float = 0.0
    total_steps: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FinalMetrics:
        if not data:
            return cls()
        return cls(
            total_prompt_tokens=data.get("total_prompt_tokens", 0),
            total_completion_tokens=data.get("total_completion_tokens", 0),
            total_cached_tokens=data.get("total_cached_tokens", 0),
            total_cost_usd=data.get("total_cost_usd", 0.0),
            total_steps=data.get("total_steps", 0),
        )


@dataclass
class TestResult:
    """Single test result from CTRF."""

    name: str
    status: str  # 'passed', 'failed', 'skipped'
    duration: float
    message: Optional[str] = None
    trace: Optional[str] = None


@dataclass
class VerifierResults:
    """Results from the verifier (ctrf.json + reward.txt)."""

    reward: float
    tests_passed: int
    tests_failed: int
    tests_total: int
    test_results: List[TestResult] = field(default_factory=list)


@dataclass
class ParsedTrajectory:
    """Complete parsed trajectory with all associated data."""

    # Identity
    task_id: str
    profile_key: str
    run_timestamp: str
    trial_dir: Path

    # ATIF data
    schema_version: str
    session_id: str
    agent: AgentInfo
    steps: List[Step]
    final_metrics: FinalMetrics

    # Verifier results
    verifier: Optional[VerifierResults] = None

    # Run metadata
    elapsed_sec: float = 0.0
    command: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        if self.verifier:
            return self.verifier.reward == 1.0
        return False

    @property
    def agent_steps(self) -> List[Step]:
        return [s for s in self.steps if s.is_agent_step]

    @property
    def total_tool_calls(self) -> int:
        return sum(len(s.tool_calls) for s in self.steps)

    @property
    def total_tokens(self) -> int:
        if self.final_metrics:
            return self.final_metrics.total_prompt_tokens + self.final_metrics.total_completion_tokens
        return sum((s.metrics.prompt_tokens + s.metrics.completion_tokens) for s in self.steps if s.metrics)


class TrajectoryParser:
    """Parser for Harbor run outputs."""

    def __init__(self, runs_dir: Path):
        self.runs_dir = Path(runs_dir)
        self.index = self._load_index()

    def _load_index(self) -> Dict[str, Any]:
        """Load runs/index.json."""
        index_path = self.runs_dir / "index.json"
        if index_path.exists():
            return json.loads(index_path.read_text())
        return {"runs": []}

    def list_runs(self) -> List[Dict[str, Any]]:
        """List all runs from index."""
        return self.index.get("runs", [])

    def parse_trajectory(self, run_entry: Dict[str, Any]) -> Optional[ParsedTrajectory]:
        """Parse a single run entry into a ParsedTrajectory."""
        traj_path = run_entry.get("trajectory_json")
        if not traj_path:
            return None

        traj_path = Path(traj_path)
        if not traj_path.exists():
            return None

        # Parse trajectory.json
        traj_data = json.loads(traj_path.read_text())

        # Get trial directory
        trial_dir = traj_path.parent.parent

        # Parse verifier results
        verifier = self._parse_verifier(trial_dir / "verifier")

        # Get elapsed time from result.json or compute from trajectory timestamps
        elapsed_sec = self._get_elapsed_sec(run_entry, traj_data)

        # Build ParsedTrajectory
        return ParsedTrajectory(
            task_id=run_entry.get("task_id", ""),
            profile_key=run_entry.get("agent_key", ""),
            run_timestamp=trial_dir.parent.name,
            trial_dir=trial_dir,
            schema_version=traj_data.get("schema_version", ""),
            session_id=traj_data.get("session_id", ""),
            agent=AgentInfo.from_dict(traj_data.get("agent", {})),
            steps=[Step.from_dict(s) for s in traj_data.get("steps", [])],
            final_metrics=FinalMetrics.from_dict(traj_data.get("final_metrics")),
            verifier=verifier,
            elapsed_sec=elapsed_sec,
            command=run_entry.get("command", []),
        )

    def _get_elapsed_sec(self, run_entry: Dict[str, Any], traj_data: Dict[str, Any]) -> float:
        """Get agent working time from trajectory timestamps (excludes warmup/sidechain steps)."""
        from datetime import datetime

        # Filter to only main task steps (exclude warmup/sidechain)
        steps = traj_data.get("steps", [])
        main_steps = [s for s in steps if not s.get("extra", {}).get("is_sidechain", False)]

        if len(main_steps) >= 2:
            try:
                first_ts = main_steps[0].get("timestamp", "")
                last_ts = main_steps[-1].get("timestamp", "")
                if first_ts and last_ts:
                    start_dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
                    end_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                    return (end_dt - start_dt).total_seconds()
            except (ValueError, KeyError):
                pass

        return 0.0

    def _parse_verifier(self, verifier_dir: Path) -> Optional[VerifierResults]:
        """Parse verifier outputs (ctrf.json + reward.txt)."""
        if not verifier_dir.exists():
            return None

        # Parse reward
        reward_path = verifier_dir / "reward.txt"
        reward = 0.0
        if reward_path.exists():
            try:
                reward = float(reward_path.read_text().strip())
            except ValueError:
                pass

        # Parse CTRF
        ctrf_path = verifier_dir / "ctrf.json"
        tests_passed = 0
        tests_failed = 0
        tests_total = 0
        test_results = []

        if ctrf_path.exists():
            ctrf_data = json.loads(ctrf_path.read_text())
            summary = ctrf_data.get("results", {}).get("summary", {})
            tests_passed = summary.get("passed", 0)
            tests_failed = summary.get("failed", 0)
            tests_total = summary.get("tests", 0)

            for test in ctrf_data.get("results", {}).get("tests", []):
                test_results.append(
                    TestResult(
                        name=test.get("name", ""),
                        status=test.get("status", ""),
                        duration=test.get("duration", 0.0),
                        message=test.get("message"),
                        trace=test.get("trace"),
                    )
                )

        return VerifierResults(
            reward=reward,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            tests_total=tests_total,
            test_results=test_results,
        )

    def parse_all(self) -> List[ParsedTrajectory]:
        """Parse all trajectories from index."""
        trajectories = []
        for run_entry in self.list_runs():
            traj = self.parse_trajectory(run_entry)
            if traj:
                trajectories.append(traj)
        return trajectories

    def get_trajectories_by_task(self, task_id: str) -> List[ParsedTrajectory]:
        """Get all trajectories for a specific task."""
        return [t for t in self.parse_all() if t.task_id == task_id]

    def get_trajectories_by_profile(self, profile_key: str) -> List[ParsedTrajectory]:
        """Get all trajectories for a specific profile."""
        return [t for t in self.parse_all() if t.profile_key == profile_key]

    def get_unique_tasks(self) -> List[str]:
        """Get list of unique task IDs."""
        return list(set(tid for r in self.list_runs() if (tid := r.get("task_id")) is not None))

    def get_unique_profiles(self) -> List[str]:
        """Get list of unique profile keys."""
        return list(set(key for r in self.list_runs() if (key := r.get("agent_key")) is not None))
