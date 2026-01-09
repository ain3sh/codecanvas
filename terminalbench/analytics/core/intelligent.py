"""
LLM-Powered Analysis - Layer 2 of the analytics framework.

Uses GPT-5.2 for semantic analysis that can't be computed deterministically.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from litellm import completion

# Load environment variables
try:
    from dotenv import load_dotenv

    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

from ..extensions.prompts import (
    COMPARATIVE_NARRATIVE_PROMPT,
    FAILURE_ANALYSIS_PROMPT,
    INSIGHT_SYNTHESIS_PROMPT,
    MCP_UTILIZATION_PROMPT,
    STRATEGY_ANALYSIS_PROMPT,
    condense_trajectory,
    format_test_results,
)
from ..io.parser import ParsedTrajectory
from .deterministic import DeterministicMetrics

DEFAULT_MODEL = "openrouter/openai/gpt-5.2"
MAX_RETRIES = 3


@dataclass
class StrategyAnalysis:
    """Strategy classification result."""

    primary_strategy: str
    strategy_quality: float
    reasoning_coherence: float
    adaptation_events: List[str]
    strengths: List[str]
    weaknesses: List[str]
    key_decisions: List[Dict[str, Any]]
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FailureAnalysis:
    """Failure root cause analysis result."""

    root_cause: str
    confidence: float
    critical_step: Optional[int]
    critical_step_explanation: str
    missed_insight: str
    counterfactual: str
    contributing_factors: List[str]
    recovery_opportunity: str
    task_specific_difficulty: str
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPUtilizationAnalysis:
    """MCP tool utilization quality result."""

    utilization_quality: float
    init_timing: str
    init_quality: str
    dependency_leverage: float
    dependency_leverage_explanation: str
    search_effectiveness: float
    structural_understanding: float
    missed_opportunities: List[str]
    effective_uses: List[str]
    fallback_to_native: str
    recommendation: str
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComparativeNarrative:
    """Comparative analysis between two profiles."""

    winner: str
    winner_reason: str
    performance_delta: Dict[str, str]
    exploration_comparison: str
    tool_substitution: Dict[str, str]
    key_insight: str
    quote_worthy_moment: Dict[str, Any]
    narrative_paragraph: str
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InsightSynthesis:
    """Cross-run insight synthesis."""

    task_difficulty_ranking: List[Dict[str, str]]
    mcp_benefit_patterns: List[str]
    mcp_overhead_patterns: List[str]
    emergent_findings: List[str]
    recommended_improvements: List[Dict[str, str]]
    paper_claims: List[Dict[str, Any]]
    limitations: List[str]
    future_work: List[str]
    raw_response: Dict[str, Any] = field(default_factory=dict)


TASK_DESCRIPTIONS = {
    "sanitize-git-repo": (
        "Find and replace all API keys (AWS, GitHub, HuggingFace) in a repository with placeholder values."
    ),
    "build-cython-ext": "Build Cython extensions for pyknotid package with NumPy 2.x compatibility.",
    "custom-memory-heap-crash": (
        "Debug a C++ program that crashes in RELEASE but not DEBUG mode due to custom memory allocator."
    ),
    "db-wal-recovery": "Recover data from a corrupted SQLite WAL file and export to JSON.",
    "modernize-scientific-stack": "Port legacy Python 2.7 climate analysis code to Python 3.",
    "rstan-to-pystan": "Convert R Stan code to PyStan 3.10.0 for Gaussian process modeling.",
    "fix-code-vulnerability": "Identify and fix CWE vulnerabilities in the Bottle web framework.",
}


class LLMAnalyzer:
    """LLM-powered analyzer using GPT-5.2."""

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
        self._validate_api_key()

    def _validate_api_key(self):
        if self.model.startswith("openrouter/") and not os.getenv("OPENROUTER_API_KEY"):
            raise ValueError("OPENROUTER_API_KEY not found. Set it in terminalbench/.env or export it.")

    def _call_llm(self, prompt: str, max_retries: int = MAX_RETRIES) -> Dict[str, Any]:
        """Call LLM and parse JSON response."""
        for attempt in range(max_retries):
            try:
                response = completion(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are an expert AI research analyst. Always respond with valid JSON only, "
                                "no markdown code blocks."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                )
                raw = response.choices[0].message.content.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[-1]
                if raw.endswith("```"):
                    raw = raw.rsplit("\n", 1)[0]
                return json.loads(raw.strip())
            except json.JSONDecodeError as e:
                print(f"  [!] JSON parse error (attempt {attempt + 1}): {e}")
                time.sleep(1)
            except Exception as e:
                print(f"  [!] API error (attempt {attempt + 1}): {e}")
                time.sleep(2)
        return {}

    def _call_vision(self, prompt: str, image_path: Path, max_retries: int = MAX_RETRIES) -> Dict[str, Any]:
        """Call LLM with image and parse JSON response."""
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        for attempt in range(max_retries):
            try:
                response = completion(
                    model=self.model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                            ],
                        }
                    ],
                    response_format={"type": "json_object"},
                )
                raw = response.choices[0].message.content.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[-1]
                if raw.endswith("```"):
                    raw = raw.rsplit("\n", 1)[0]
                return json.loads(raw.strip())
            except json.JSONDecodeError as e:
                print(f"  [!] Vision JSON parse error (attempt {attempt + 1}): {e}")
                time.sleep(1)
            except Exception as e:
                print(f"  [!] Vision API error (attempt {attempt + 1}): {e}")
                time.sleep(2)
        return {}

    def analyze_strategy(self, trajectory: ParsedTrajectory, metrics: DeterministicMetrics) -> StrategyAnalysis:
        condensed = condense_trajectory(trajectory)
        task_desc = TASK_DESCRIPTIONS.get(trajectory.task_id, "Unknown task")
        profile_desc = "with MCP tools" if metrics.mcp_tool_calls > 0 else "text-only baseline"

        prompt = STRATEGY_ANALYSIS_PROMPT.format(
            task_id=trajectory.task_id,
            task_description=task_desc,
            profile_key=trajectory.profile_key,
            profile_desc=profile_desc,
            total_steps=metrics.total_steps,
            tool_calls_count=metrics.tool_calls_count,
            unique_tools=metrics.unique_tools,
            success=metrics.success,
            elapsed_sec=metrics.elapsed_sec,
            condensed_trajectory=condensed,
        )
        result = self._call_llm(prompt)

        return StrategyAnalysis(
            primary_strategy=result.get("primary_strategy", "unknown"),
            strategy_quality=result.get("strategy_quality", 0.0),
            reasoning_coherence=result.get("reasoning_coherence", 0.0),
            adaptation_events=result.get("adaptation_events", []),
            strengths=result.get("strengths", []),
            weaknesses=result.get("weaknesses", []),
            key_decisions=result.get("key_decisions", []),
            raw_response=result,
        )

    def analyze_failure(self, trajectory: ParsedTrajectory, metrics: DeterministicMetrics) -> FailureAnalysis:
        if metrics.success:
            return FailureAnalysis(
                root_cause="not_applicable",
                confidence=1.0,
                critical_step=None,
                critical_step_explanation="Task succeeded",
                missed_insight="N/A",
                counterfactual="N/A",
                contributing_factors=[],
                recovery_opportunity="N/A",
                task_specific_difficulty="N/A",
            )

        condensed = condense_trajectory(trajectory)
        task_desc = TASK_DESCRIPTIONS.get(trajectory.task_id, "Unknown task")
        test_results = format_test_results(trajectory.verifier)

        prompt = FAILURE_ANALYSIS_PROMPT.format(
            task_id=trajectory.task_id,
            task_description=task_desc,
            profile_key=trajectory.profile_key,
            test_results=test_results,
            total_steps=metrics.total_steps,
            tool_calls_count=metrics.tool_calls_count,
            files_read_count=len(metrics.files_read),
            files_edited_count=len(metrics.files_edited),
            loop_count=metrics.loop_count,
            backtrack_count=metrics.backtrack_count,
            condensed_trajectory=condensed,
        )
        result = self._call_llm(prompt)

        return FailureAnalysis(
            root_cause=result.get("root_cause", "unknown"),
            confidence=result.get("confidence", 0.0),
            critical_step=result.get("critical_step"),
            critical_step_explanation=result.get("critical_step_explanation", ""),
            missed_insight=result.get("missed_insight", ""),
            counterfactual=result.get("counterfactual", ""),
            contributing_factors=result.get("contributing_factors", []),
            recovery_opportunity=result.get("recovery_opportunity", ""),
            task_specific_difficulty=result.get("task_specific_difficulty", ""),
            raw_response=result,
        )

    def analyze_mcp_utilization(
        self, trajectory: ParsedTrajectory, metrics: DeterministicMetrics
    ) -> MCPUtilizationAnalysis:
        if metrics.mcp_tool_calls == 0:
            return MCPUtilizationAnalysis(
                utilization_quality=0.0,
                init_timing="never",
                init_quality="No MCP tools used",
                dependency_leverage=0.0,
                dependency_leverage_explanation="N/A",
                search_effectiveness=0.0,
                structural_understanding=0.0,
                missed_opportunities=["All MCP tools were available but unused"],
                effective_uses=[],
                fallback_to_native="Agent used only native tools",
                recommendation="Agent should try using MCP tools for structural understanding",
            )

        condensed = condense_trajectory(trajectory)
        available_mcp_tools = (
            "init_repository, get_code, get_dependencies, search_code, get_symbol_info, find_references"
        )
        prompt = MCP_UTILIZATION_PROMPT.format(
            task_id=trajectory.task_id,
            profile_key=trajectory.profile_key,
            available_mcp_tools=available_mcp_tools,
            mcp_tool_calls=metrics.mcp_tool_calls,
            native_tool_calls=metrics.native_tool_calls,
            mcp_tools_used=", ".join(metrics.mcp_tools_used),
            success=metrics.success,
            total_steps=metrics.total_steps,
            condensed_trajectory=condensed,
        )
        result = self._call_llm(prompt)

        return MCPUtilizationAnalysis(
            utilization_quality=result.get("utilization_quality", 0.0),
            init_timing=result.get("init_timing", "unknown"),
            init_quality=result.get("init_quality", ""),
            dependency_leverage=result.get("dependency_leverage", 0.0),
            dependency_leverage_explanation=result.get("dependency_leverage_explanation", ""),
            search_effectiveness=result.get("search_effectiveness", 0.0),
            structural_understanding=result.get("structural_understanding", 0.0),
            missed_opportunities=result.get("missed_opportunities", []),
            effective_uses=result.get("effective_uses", []),
            fallback_to_native=result.get("fallback_to_native", ""),
            recommendation=result.get("recommendation", ""),
            raw_response=result,
        )

    def compare_profiles(
        self,
        task_id: str,
        traj_a: ParsedTrajectory,
        metrics_a: DeterministicMetrics,
        traj_b: ParsedTrajectory,
        metrics_b: DeterministicMetrics,
    ) -> ComparativeNarrative:
        task_desc = TASK_DESCRIPTIONS.get(task_id, "Unknown task")
        condensed_a = condense_trajectory(traj_a, max_steps=30)
        condensed_b = condense_trajectory(traj_b, max_steps=30)

        prompt = COMPARATIVE_NARRATIVE_PROMPT.format(
            task_id=task_id,
            task_description=task_desc,
            profile_a=traj_a.profile_key,
            profile_a_desc="with MCP" if metrics_a.mcp_tool_calls > 0 else "text-only",
            profile_a_success=metrics_a.success,
            profile_a_steps=metrics_a.total_steps,
            profile_a_tool_calls=metrics_a.tool_calls_count,
            profile_a_cost=metrics_a.total_cost_usd,
            profile_a_elapsed=metrics_a.elapsed_sec,
            profile_a_trajectory=condensed_a,
            profile_b=traj_b.profile_key,
            profile_b_desc="with MCP" if metrics_b.mcp_tool_calls > 0 else "text-only",
            profile_b_success=metrics_b.success,
            profile_b_steps=metrics_b.total_steps,
            profile_b_tool_calls=metrics_b.tool_calls_count,
            profile_b_cost=metrics_b.total_cost_usd,
            profile_b_elapsed=metrics_b.elapsed_sec,
            profile_b_trajectory=condensed_b,
        )
        result = self._call_llm(prompt)

        return ComparativeNarrative(
            winner=result.get("winner", "tie"),
            winner_reason=result.get("winner_reason", ""),
            performance_delta=result.get("performance_delta", {}),
            exploration_comparison=result.get("exploration_comparison", ""),
            tool_substitution=result.get("tool_substitution", {}),
            key_insight=result.get("key_insight", ""),
            quote_worthy_moment=result.get("quote_worthy_moment", {}),
            narrative_paragraph=result.get("narrative_paragraph", ""),
            raw_response=result,
        )

    def synthesize_insights(
        self,
        profiles: List[str],
        tasks: List[str],
        aggregate_metrics: Dict[str, Dict[str, Any]],
        per_task_summary: str,
        individual_summaries: str,
    ) -> InsightSynthesis:
        metrics_lines = []
        for profile, metrics in aggregate_metrics.items():
            metrics_lines.append(f"\n### {profile}")
            for k, v in metrics.items():
                metrics_lines.append(f"- {k}: {v:.2f}" if isinstance(v, float) else f"- {k}: {v}")

        prompt = INSIGHT_SYNTHESIS_PROMPT.format(
            profiles=", ".join(profiles),
            tasks=", ".join(tasks),
            total_runs=sum(m.get("count", 0) for m in aggregate_metrics.values()),
            aggregate_metrics_table="\n".join(metrics_lines),
            per_task_summary=per_task_summary,
            individual_summaries=individual_summaries,
        )
        result = self._call_llm(prompt)

        return InsightSynthesis(
            task_difficulty_ranking=result.get("task_difficulty_ranking", []),
            mcp_benefit_patterns=result.get("mcp_benefit_patterns", []),
            mcp_overhead_patterns=result.get("mcp_overhead_patterns", []),
            emergent_findings=result.get("emergent_findings", []),
            recommended_improvements=result.get("recommended_improvements", []),
            paper_claims=result.get("paper_claims", []),
            limitations=result.get("limitations", []),
            future_work=result.get("future_work", []),
            raw_response=result,
        )


def estimate_analysis_cost(num_trajectories: int, include_synthesis: bool = True) -> Dict[str, Any]:
    cost_per_trajectory = 0.05
    cost_per_mcp_trajectory = 0.03
    cost_per_comparison = 0.04
    cost_synthesis = 0.10

    num_comparisons = num_trajectories // 2
    base_cost = num_trajectories * cost_per_trajectory
    mcp_cost = (num_trajectories // 2) * cost_per_mcp_trajectory
    comparison_cost = num_comparisons * cost_per_comparison
    synthesis_cost = cost_synthesis if include_synthesis else 0

    return {
        "num_trajectories": num_trajectories,
        "estimated_cost_usd": round(base_cost + mcp_cost + comparison_cost + synthesis_cost, 2),
        "breakdown": {
            "strategy_analysis": round(base_cost, 2),
            "mcp_analysis": round(mcp_cost, 2),
            "comparisons": round(comparison_cost, 2),
            "synthesis": round(synthesis_cost, 2),
        },
        "note": "Estimates only - actual cost depends on trajectory lengths",
    }
