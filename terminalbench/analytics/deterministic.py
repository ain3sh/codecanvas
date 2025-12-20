"""
Deterministic Metrics - Layer 1 of the analytics framework.

All metrics computed directly from ATIF trajectory data without LLM calls.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .parser import ParsedTrajectory, Step


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
    # CodeCanvas (future)
    "render_codemap", "get_clusters", "highlight_path", "annotate_map",
}

# Native Claude Code tools
NATIVE_TOOL_NAMES = {
    "Read", "Grep", "Glob", "LS", "Edit", "MultiEdit", "Create",
    "Execute", "Bash", "TodoRead", "TodoWrite", "WebFetch", "Task",
}


def is_mcp_tool(tool_name: str) -> bool:
    """Check if a tool name is an MCP tool (handles prefixed names like mcp__codegraph__*)."""
    # Direct match
    if tool_name in MCP_TOOL_BASE_NAMES:
        return True
    # Prefixed match (mcp__servername__toolname)
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__")
        if len(parts) >= 3:
            base_name = parts[-1]
            return base_name in MCP_TOOL_BASE_NAMES
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
    
    # If no final_metrics cost, estimate from steps
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
    )


def _estimate_cost_from_steps(steps: List[Step]) -> float:
    """Estimate cost from step-level metrics if final_metrics missing."""
    total = 0.0
    for step in steps:
        if step.metrics and step.metrics.cost_usd:
            total += step.metrics.cost_usd
    return total


def _extract_tool_names(steps: List[Step]) -> List[str]:
    """Extract all tool names from trajectory."""
    names = []
    for step in steps:
        for tc in step.tool_calls:
            names.append(tc.function_name)
    return names


def _count_tool_errors(steps: List[Step]) -> int:
    """Count tool calls that resulted in errors."""
    errors = 0
    for step in steps:
        for obs in step.observation_results:
            if obs.error:
                errors += 1
            elif "error" in obs.content.lower()[:200]:
                errors += 1
    return errors


def _detect_loops(steps: List[Step]) -> int:
    """Detect repeated identical tool calls (potential infinite loops)."""
    loop_count = 0
    recent_calls = []
    
    for step in steps:
        for tc in step.tool_calls:
            call_sig = (tc.function_name, str(tc.arguments))
            if call_sig in recent_calls[-5:]:  # Look at last 5 calls
                loop_count += 1
            recent_calls.append(call_sig)
    
    return loop_count


def _detect_backtracks(steps: List[Step]) -> int:
    """Detect edit-then-revert patterns."""
    backtrack_count = 0
    edit_history = []
    
    for step in steps:
        for tc in step.tool_calls:
            if tc.function_name in ("Edit", "MultiEdit", "Create"):
                file_path = tc.arguments.get("file_path") or tc.arguments.get("path")
                if file_path:
                    # Check if we're editing the same file again soon
                    if file_path in edit_history[-3:]:
                        backtrack_count += 1
                    edit_history.append(file_path)
    
    return backtrack_count


def _extract_file_operations(steps: List[Step]) -> tuple[Set[str], Set[str]]:
    """Extract files read and edited."""
    files_read = set()
    files_edited = set()
    
    for step in steps:
        for tc in step.tool_calls:
            if tc.function_name == "Read":
                path = tc.arguments.get("file_path")
                if path:
                    files_read.add(path)
            elif tc.function_name in ("Grep", "Glob"):
                path = tc.arguments.get("path")
                if path:
                    files_read.add(path)
            elif tc.function_name in ("Edit", "MultiEdit", "Create"):
                path = tc.arguments.get("file_path") or tc.arguments.get("path")
                if path:
                    files_edited.add(path)
    
    return files_read, files_edited


def _check_grep_before_edit(steps: List[Step]) -> bool:
    """Check if agent used grep/search before editing."""
    seen_search = False
    seen_edit = False
    
    for step in steps:
        for tc in step.tool_calls:
            if tc.function_name in ("Grep", "Glob", "search_code"):
                seen_search = True
            elif tc.function_name in ("Edit", "MultiEdit"):
                if seen_search:
                    return True
                seen_edit = True
    
    return False


def _detect_failure_indicators(steps: List[Step], success: bool) -> Dict[str, int]:
    """Detect potential failure indicators in trajectory."""
    indicators = {
        "context_omission": 0,
        "tool_misuse": 0,
        "infinite_loop": 0,
        "budget_exhaustion": 0,
        "premature_stop": 0,
    }
    
    # Tool misuse: high error rate in tool calls
    tool_calls = sum(len(s.tool_calls) for s in steps)
    tool_errors = _count_tool_errors(steps)
    if tool_calls > 0 and tool_errors / tool_calls > 0.3:
        indicators["tool_misuse"] = tool_errors
    
    # Infinite loop: many repeated calls
    loop_count = _detect_loops(steps)
    if loop_count > 5:
        indicators["infinite_loop"] = loop_count
    
    # Budget exhaustion: trajectory ended abruptly with many tokens
    total_tokens = sum(
        (s.metrics.prompt_tokens + s.metrics.completion_tokens) 
        for s in steps if s.metrics
    )
    if not success and total_tokens > 80000:
        indicators["budget_exhaustion"] = 1
    
    # Premature stop: few steps but failed
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
        
        # Averages
        "avg_tokens": sum(m.total_tokens for m in metrics_list) / n,
        "avg_cost": sum(m.total_cost_usd for m in metrics_list) / n,
        "avg_steps": sum(m.total_steps for m in metrics_list) / n,
        "avg_tool_calls": sum(m.tool_calls_count for m in metrics_list) / n,
        "avg_unique_tools": sum(m.unique_tools for m in metrics_list) / n,
        "avg_elapsed_sec": sum(m.elapsed_sec for m in metrics_list) / n,
        
        # Success-only averages
        "avg_cost_success": (
            sum(m.total_cost_usd for m in successes) / len(successes) 
            if successes else None
        ),
        "avg_tokens_success": (
            sum(m.total_tokens for m in successes) / len(successes)
            if successes else None
        ),
        
        # MCP usage
        "mcp_usage_rate": sum(1 for m in metrics_list if m.mcp_tool_calls > 0) / n * 100,
        "avg_mcp_calls": sum(m.mcp_tool_calls for m in metrics_list) / n,
        
        # Behavioral
        "avg_loop_count": sum(m.loop_count for m in metrics_list) / n,
        "avg_backtrack_count": sum(m.backtrack_count for m in metrics_list) / n,
        "grep_before_edit_rate": sum(1 for m in metrics_list if m.grep_before_edit) / n * 100,
        
        # Tool distribution (aggregated)
        "tool_distribution": _aggregate_tool_distribution(metrics_list),
    }


def _aggregate_tool_distribution(metrics_list: List[DeterministicMetrics]) -> Dict[str, int]:
    """Aggregate tool distributions across trajectories."""
    total = Counter()
    for m in metrics_list:
        total.update(m.tool_distribution)
    return dict(total)
