"""
Deterministic Metrics - Layer 1 of the analytics framework.

All metrics computed directly from ATIF trajectory data without LLM calls.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from ..io.parser import ParsedTrajectory, Step
from ..extensions.codecanvas import (
    load_codecanvas_state,
    compute_codecanvas_metrics,
)


@dataclass
class DeterministicMetrics:
    """All deterministic metrics for a single trajectory."""
    
    # Identity
    task_id: str
    profile_key: str
    run_timestamp: str
    
    # Outcome metrics
    success: bool
    reward: float
    tests_passed: int
    tests_failed: int
    tests_total: int
    tests_passed_ratio: float
    
    # Economic metrics
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: float
    cost_per_success: float  # inf if failed
    token_efficiency: float  # success/1M tokens
    
    # Process metrics
    total_steps: int
    agent_steps: int
    tool_calls_count: int
    unique_tools: int
    tools_per_step: float
    steps_per_minute: float
    elapsed_sec: float
    
    # Tool usage metrics
    tool_distribution: Dict[str, int]
    tool_success_rate: float
    tool_error_count: int
    mcp_tools_used: List[str]
    mcp_tool_calls: int
    native_tool_calls: int
    
    # Behavioral metrics
    loop_count: int
    backtrack_count: int
    exploration_breadth: int  # unique files touched
    files_read: Set[str]
    files_edited: Set[str]
    grep_before_edit: bool
    
    # Failure taxonomy (heuristic detection)
    failure_indicators: Dict[str, int]
    
    # CodeCanvas-specific (None if not a codecanvas run or no state.json)
    codecanvas_evidence_count: Optional[int] = None
    codecanvas_claims_count: Optional[int] = None
    codecanvas_decisions_count: Optional[int] = None
    codecanvas_impact_analyses: Optional[int] = None
    codecanvas_blast_radius_edit_rate: Optional[float] = None
    codecanvas_anticipated_failure_rate: Optional[float] = None
    codecanvas_deliberation_depth: Optional[int] = None
    codecanvas_reasoning_density: Optional[float] = None
    codecanvas_systematic_progress: Optional[float] = None
    codecanvas_informed_editing_score: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        d = {}
        for k, v in self.__dict__.items():
            if isinstance(v, set):
                d[k] = list(v)
            elif isinstance(v, float) and v == float('inf'):
                d[k] = None
            else:
                d[k] = v
        return d


# Known MCP tools (codegraph, codecanvas) - base names
MCP_TOOL_BASE_NAMES = {
    # CodeGraph (locagent backend)
    "init_repository", "get_code", "get_dependencies", "search_code",
    "get_symbol_info", "find_references", "get_file_tree",
    # CodeCanvas
    "canvas",
}

# Native Claude Code tools
NATIVE_TOOL_NAMES = {
    "Read", "Grep", "Glob", "LS", "Edit", "MultiEdit", "Create",
    "Execute", "Bash", "TodoRead", "TodoWrite", "WebFetch", "Task",
}


def is_mcp_tool(tool_name: str) -> bool:
    """Check if a tool name is an MCP tool (handles prefixed names)."""
    if tool_name in MCP_TOOL_BASE_NAMES:
        return True
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__")
        if len(parts) >= 3:
            return parts[-1] in MCP_TOOL_BASE_NAMES
    return False


def is_native_tool(tool_name: str) -> bool:
    """Check if a tool name is a native Claude Code tool."""
    return tool_name in NATIVE_TOOL_NAMES


def compute_metrics(trajectory: ParsedTrajectory) -> DeterministicMetrics:
    """Compute all deterministic metrics for a trajectory."""
    
    # Outcome metrics
    success = trajectory.success
    reward = trajectory.verifier.reward if trajectory.verifier else 0.0
    tests_passed = trajectory.verifier.tests_passed if trajectory.verifier else 0
    tests_failed = trajectory.verifier.tests_failed if trajectory.verifier else 0
    tests_total = trajectory.verifier.tests_total if trajectory.verifier else 0
    tests_passed_ratio = tests_passed / tests_total if tests_total > 0 else 0.0
    
    # Economic metrics
    total_input = trajectory.final_metrics.total_prompt_tokens
    total_output = trajectory.final_metrics.total_completion_tokens
    total_tokens = total_input + total_output
    total_cost = trajectory.final_metrics.total_cost_usd
    
    if total_cost == 0:
        total_cost = _estimate_cost_from_steps(trajectory.steps)
    
    cost_per_success = total_cost if success else float('inf')
    token_efficiency = (1.0 / total_tokens * 1_000_000) if success and total_tokens > 0 else 0.0
    
    # Process metrics
    total_steps = len(trajectory.steps)
    agent_steps = len(trajectory.agent_steps)
    tool_calls_count = trajectory.total_tool_calls
    
    tool_names = _extract_tool_names(trajectory.steps)
    unique_tools = len(set(tool_names))
    tools_per_step = tool_calls_count / agent_steps if agent_steps > 0 else 0.0
    
    elapsed = trajectory.elapsed_sec
    steps_per_minute = (total_steps / elapsed * 60) if elapsed > 0 else 0.0
    
    # Tool usage
    tool_dist = Counter(tool_names)
    tool_errors = _count_tool_errors(trajectory.steps)
    tool_success_rate = 1.0 - (tool_errors / tool_calls_count) if tool_calls_count > 0 else 1.0
    
    mcp_tools = [t for t in tool_names if is_mcp_tool(t)]
    native_tools = [t for t in tool_names if is_native_tool(t)]
    
    # Behavioral patterns
    loop_count = _detect_loops(trajectory.steps)
    backtrack_count = _detect_backtracks(trajectory.steps)
    files_read, files_edited = _extract_file_operations(trajectory.steps)
    exploration_breadth = len(files_read | files_edited)
    grep_before_edit = _check_grep_before_edit(trajectory.steps)
    
    # Failure indicators
    failure_indicators = _detect_failure_indicators(trajectory.steps, success)
    
    # CodeCanvas-specific metrics
    cc_state = load_codecanvas_state(trajectory.trial_dir)
    cc_metrics = compute_codecanvas_metrics(trajectory, cc_state) if cc_state else None
    
    return DeterministicMetrics(
        task_id=trajectory.task_id,
        profile_key=trajectory.profile_key,
        run_timestamp=trajectory.run_timestamp,
        success=success,
        reward=reward,
        tests_passed=tests_passed,
        tests_failed=tests_failed,
        tests_total=tests_total,
        tests_passed_ratio=tests_passed_ratio,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_tokens=total_tokens,
        total_cost_usd=total_cost,
        cost_per_success=cost_per_success,
        token_efficiency=token_efficiency,
        total_steps=total_steps,
        agent_steps=agent_steps,
        tool_calls_count=tool_calls_count,
        unique_tools=unique_tools,
        tools_per_step=tools_per_step,
        steps_per_minute=steps_per_minute,
        elapsed_sec=elapsed,
        tool_distribution=dict(tool_dist),
        tool_success_rate=tool_success_rate,
        tool_error_count=tool_errors,
        mcp_tools_used=list(set(mcp_tools)),
        mcp_tool_calls=len(mcp_tools),
        native_tool_calls=len(native_tools),
        loop_count=loop_count,
        backtrack_count=backtrack_count,
        exploration_breadth=exploration_breadth,
        files_read=files_read,
        files_edited=files_edited,
        grep_before_edit=grep_before_edit,
        failure_indicators=failure_indicators,
        codecanvas_evidence_count=cc_metrics.evidence_count if cc_metrics else None,
        codecanvas_claims_count=cc_metrics.claims_count if cc_metrics else None,
        codecanvas_decisions_count=cc_metrics.decisions_count if cc_metrics else None,
        codecanvas_impact_analyses=cc_metrics.impact_analyses_count if cc_metrics else None,
        codecanvas_blast_radius_edit_rate=cc_metrics.blast_radius_edit_rate if cc_metrics else None,
        codecanvas_anticipated_failure_rate=cc_metrics.anticipated_failure_rate if cc_metrics else None,
        codecanvas_deliberation_depth=cc_metrics.deliberation_depth if cc_metrics else None,
        codecanvas_reasoning_density=cc_metrics.reasoning_density if cc_metrics else None,
        codecanvas_systematic_progress=cc_metrics.systematic_progress if cc_metrics else None,
        codecanvas_informed_editing_score=cc_metrics.informed_editing_score if cc_metrics else None,
    )


def _estimate_cost_from_steps(steps: List[Step]) -> float:
    return sum(s.metrics.cost_usd for s in steps if s.metrics and s.metrics.cost_usd)


def _extract_tool_names(steps: List[Step]) -> List[str]:
    return [tc.function_name for step in steps for tc in step.tool_calls]


def _count_tool_errors(steps: List[Step]) -> int:
    errors = 0
    for step in steps:
        for obs in step.observation_results:
            if obs.error or "error" in obs.content.lower()[:200]:
                errors += 1
    return errors


def _detect_loops(steps: List[Step]) -> int:
    loop_count = 0
    recent_calls = []
    for step in steps:
        for tc in step.tool_calls:
            call_sig = (tc.function_name, str(tc.arguments))
            if call_sig in recent_calls[-5:]:
                loop_count += 1
            recent_calls.append(call_sig)
    return loop_count


def _detect_backtracks(steps: List[Step]) -> int:
    backtrack_count = 0
    edit_history = []
    for step in steps:
        for tc in step.tool_calls:
            if tc.function_name in ("Edit", "MultiEdit", "Create"):
                file_path = tc.arguments.get("file_path") or tc.arguments.get("path")
                if file_path:
                    if file_path in edit_history[-3:]:
                        backtrack_count += 1
                    edit_history.append(file_path)
    return backtrack_count


def _extract_file_operations(steps: List[Step]) -> tuple[Set[str], Set[str]]:
    files_read, files_edited = set(), set()
    for step in steps:
        for tc in step.tool_calls:
            if tc.function_name == "Read":
                if path := tc.arguments.get("file_path"):
                    files_read.add(path)
            elif tc.function_name in ("Grep", "Glob"):
                if path := tc.arguments.get("path"):
                    files_read.add(path)
            elif tc.function_name in ("Edit", "MultiEdit", "Create"):
                if path := (tc.arguments.get("file_path") or tc.arguments.get("path")):
                    files_edited.add(path)
    return files_read, files_edited


def _check_grep_before_edit(steps: List[Step]) -> bool:
    seen_search = False
    for step in steps:
        for tc in step.tool_calls:
            if tc.function_name in ("Grep", "Glob", "search_code"):
                seen_search = True
            elif tc.function_name in ("Edit", "MultiEdit"):
                if seen_search:
                    return True
    return False


def _detect_failure_indicators(steps: List[Step], success: bool) -> Dict[str, int]:
    indicators = {"context_omission": 0, "tool_misuse": 0, "infinite_loop": 0, "budget_exhaustion": 0, "premature_stop": 0}
    
    tool_calls = sum(len(s.tool_calls) for s in steps)
    tool_errors = _count_tool_errors(steps)
    if tool_calls > 0 and tool_errors / tool_calls > 0.3:
        indicators["tool_misuse"] = tool_errors
    
    loop_count = _detect_loops(steps)
    if loop_count > 5:
        indicators["infinite_loop"] = loop_count
    
    total_tokens = sum((s.metrics.prompt_tokens + s.metrics.completion_tokens) for s in steps if s.metrics)
    if not success and total_tokens > 80000:
        indicators["budget_exhaustion"] = 1
    
    if not success and len(steps) < 10:
        indicators["premature_stop"] = 1
    
    return indicators


def compute_aggregate_metrics(metrics_list: List[DeterministicMetrics]) -> Dict[str, Any]:
    """Compute aggregate metrics across multiple trajectories."""
    if not metrics_list:
        return {}
    
    n = len(metrics_list)
    successes = [m for m in metrics_list if m.success]
    
    return {
        "count": n,
        "success_rate": len(successes) / n * 100,
        "success_count": len(successes),
        "failure_count": n - len(successes),
        "avg_tokens": sum(m.total_tokens for m in metrics_list) / n,
        "avg_cost": sum(m.total_cost_usd for m in metrics_list) / n,
        "avg_steps": sum(m.total_steps for m in metrics_list) / n,
        "avg_tool_calls": sum(m.tool_calls_count for m in metrics_list) / n,
        "avg_unique_tools": sum(m.unique_tools for m in metrics_list) / n,
        "avg_elapsed_sec": sum(m.elapsed_sec for m in metrics_list) / n,
        "avg_cost_success": sum(m.total_cost_usd for m in successes) / len(successes) if successes else None,
        "avg_tokens_success": sum(m.total_tokens for m in successes) / len(successes) if successes else None,
        "mcp_usage_rate": sum(1 for m in metrics_list if m.mcp_tool_calls > 0) / n * 100,
        "avg_mcp_calls": sum(m.mcp_tool_calls for m in metrics_list) / n,
        "avg_loop_count": sum(m.loop_count for m in metrics_list) / n,
        "avg_backtrack_count": sum(m.backtrack_count for m in metrics_list) / n,
        "grep_before_edit_rate": sum(1 for m in metrics_list if m.grep_before_edit) / n * 100,
        "tool_distribution": dict(Counter().update(m.tool_distribution) or Counter() for m in metrics_list),
    }
