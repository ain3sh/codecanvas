"""
Prompt Templates for LLM-powered analysis (Layer 2).

All prompts designed for GPT-5.2 with structured JSON output.
"""

from typing import Dict, Any

# Strategy Classification Prompt
STRATEGY_ANALYSIS_PROMPT = """You are an expert at analyzing LLM agent behavior. Analyze this agent trajectory and classify its problem-solving strategy.

## Task Context
- **Task ID**: {task_id}
- **Task Description**: {task_description}
- **Profile**: {profile_key} ({profile_desc})

## Deterministic Metrics Summary
- Total Steps: {total_steps}
- Tool Calls: {tool_calls_count}
- Unique Tools: {unique_tools}
- Success: {success}
- Elapsed Time: {elapsed_sec:.1f}s

## Condensed Trajectory
{condensed_trajectory}

## Analysis Required

Classify the agent's strategy and assess its quality. Output valid JSON:

```json
{{
    "primary_strategy": "<one of: systematic_exploration, hypothesis_driven, grep_and_fix, trial_and_error, tool_guided, chaotic>",
    "strategy_quality": <float 0-1>,
    "reasoning_coherence": <float 0-1>,
    "adaptation_events": ["<description of strategy pivots>"],
    "strengths": ["<what the agent did well>"],
    "weaknesses": ["<what could be improved>"],
    "key_decisions": [
        {{"step": <int>, "decision": "<description>", "quality": "<good/neutral/poor>"}}
    ]
}}
```

Strategy definitions:
- **systematic_exploration**: Methodical file-by-file or module-by-module exploration
- **hypothesis_driven**: Forms theories about the problem, tests them
- **grep_and_fix**: Finds patterns via search, directly edits matches
- **trial_and_error**: Tries things until something works, no clear plan
- **tool_guided**: Lets MCP/specialized tools drive the exploration
- **chaotic**: No discernible strategy, random actions"""


# Failure Root Cause Analysis Prompt
FAILURE_ANALYSIS_PROMPT = """You are an expert at diagnosing why LLM agents fail at tasks. Analyze this failed trajectory.

## Task Context
- **Task ID**: {task_id}
- **Task Description**: {task_description}
- **Profile**: {profile_key}

## Test Results
{test_results}

## Deterministic Metrics
- Total Steps: {total_steps}
- Tool Calls: {tool_calls_count}
- Files Read: {files_read_count}
- Files Edited: {files_edited_count}
- Loop Count: {loop_count}
- Backtrack Count: {backtrack_count}

## Condensed Trajectory
{condensed_trajectory}

## Analysis Required

Diagnose the root cause of failure. Output valid JSON:

```json
{{
    "root_cause": "<one of: incomplete_exploration, misunderstood_task, correct_approach_poor_execution, knowledge_gap, tool_misuse, context_loss, premature_termination, infinite_loop>",
    "confidence": <float 0-1>,
    "critical_step": <int or null>,
    "critical_step_explanation": "<what went wrong at this step>",
    "missed_insight": "<what the agent should have noticed but didn't>",
    "counterfactual": "<If agent had done X at step Y, outcome would be...>",
    "contributing_factors": ["<other factors that contributed>"],
    "recovery_opportunity": "<was there a point where agent could have recovered?>",
    "task_specific_difficulty": "<what makes this task hard for agents>"
}}
```

Root cause definitions:
- **incomplete_exploration**: Didn't find/examine necessary files or code
- **misunderstood_task**: Interpreted the task requirements incorrectly
- **correct_approach_poor_execution**: Right strategy, but implementation errors
- **knowledge_gap**: Lacked necessary domain knowledge
- **tool_misuse**: Used tools incorrectly or inefficiently
- **context_loss**: Forgot or ignored earlier discoveries
- **premature_termination**: Stopped before completing the task
- **infinite_loop**: Got stuck repeating actions"""


# MCP Utilization Quality Prompt
MCP_UTILIZATION_PROMPT = """You are an expert at evaluating how effectively LLM agents use specialized tools. Analyze this MCP-enabled trajectory.

## Task Context
- **Task ID**: {task_id}
- **Profile**: {profile_key}
- **Available MCP Tools**: {available_mcp_tools}

## MCP Usage Statistics
- MCP Tool Calls: {mcp_tool_calls}
- Native Tool Calls: {native_tool_calls}
- MCP Tools Used: {mcp_tools_used}

## Deterministic Metrics
- Success: {success}
- Total Steps: {total_steps}

## Condensed Trajectory (focusing on MCP tool usage)
{condensed_trajectory}

## Analysis Required

Evaluate the quality of MCP tool utilization. Output valid JSON:

```json
{{
    "utilization_quality": <float 0-1>,
    "init_timing": "<early|late|never>",
    "init_quality": "<description of how well initialization was done>",
    "dependency_leverage": <float 0-1>,
    "dependency_leverage_explanation": "<how well did agent use structural info>",
    "search_effectiveness": <float 0-1>,
    "structural_understanding": <float 0-1>,
    "missed_opportunities": [
        "<specific MCP tool usage that could have helped>"
    ],
    "effective_uses": [
        "<specific MCP tool usage that was well done>"
    ],
    "fallback_to_native": "<description of when/why agent fell back to grep/etc>",
    "recommendation": "<how agent should use MCP tools differently>"
}}
```

Key questions to consider:
- Did the agent call init_repository early or waste time exploring first?
- Did get_dependencies results inform subsequent actions?
- Did agent use search_code or fall back to grep?
- Did agent build a mental model from MCP tools or ignore the structural info?"""


# Comparative Narrative Prompt
COMPARATIVE_NARRATIVE_PROMPT = """You are an expert at analyzing comparative experiments in AI research. Compare these two trajectories for the same task.

## Task Context
- **Task ID**: {task_id}
- **Task Description**: {task_description}

## Trajectory A: {profile_a} ({profile_a_desc})
### Metrics
- Success: {profile_a_success}
- Steps: {profile_a_steps}
- Tool Calls: {profile_a_tool_calls}
- Cost: ${profile_a_cost:.4f}
- Time: {profile_a_elapsed:.1f}s

### Condensed Trajectory
{profile_a_trajectory}

---

## Trajectory B: {profile_b} ({profile_b_desc})
### Metrics
- Success: {profile_b_success}
- Steps: {profile_b_steps}
- Tool Calls: {profile_b_tool_calls}
- Cost: ${profile_b_cost:.4f}
- Time: {profile_b_elapsed:.1f}s

### Condensed Trajectory
{profile_b_trajectory}

---

## Analysis Required

Generate a comparative analysis suitable for a research paper. Output valid JSON:

```json
{{
    "winner": "<profile_a|profile_b|tie>",
    "winner_reason": "<one sentence explanation>",
    "performance_delta": {{
        "success_diff": "<A succeeded where B failed / both succeeded / both failed / etc>",
        "efficiency_diff": "<which was more efficient and why>",
        "approach_diff": "<how did approaches differ>"
    }},
    "exploration_comparison": "<how did exploration strategies differ>",
    "tool_substitution": {{
        "<native_tool>": "<mcp_equivalent_used_instead>"
    }},
    "key_insight": "<one sentence insight for the paper>",
    "quote_worthy_moment": {{
        "step": <int>,
        "profile": "<which profile>",
        "description": "<what happened that illustrates the difference>"
    }},
    "narrative_paragraph": "<2-3 sentence narrative comparing the two approaches, suitable for a paper's Results section>"
}}
```"""


# Cross-Run Insight Synthesis Prompt
INSIGHT_SYNTHESIS_PROMPT = """You are an expert at synthesizing research findings. Analyze these aggregate results across all tasks and profiles.

## Experiment Setup
- **Profiles Compared**: {profiles}
- **Tasks Evaluated**: {tasks}
- **Total Runs**: {total_runs}

## Aggregate Metrics by Profile
{aggregate_metrics_table}

## Per-Task Results Summary
{per_task_summary}

## Individual Analysis Summaries
{individual_summaries}

## Analysis Required

Synthesize high-level insights for a research paper. Output valid JSON:

```json
{{
    "task_difficulty_ranking": [
        {{"task": "<task_id>", "difficulty": "<easy|medium|hard>", "reason": "<why>"}}
    ],
    "mcp_benefit_patterns": [
        "<pattern where MCP tools provided clear benefit>"
    ],
    "mcp_overhead_patterns": [
        "<pattern where MCP tools added overhead without benefit>"
    ],
    "emergent_findings": [
        "<unexpected discovery from the data>"
    ],
    "recommended_improvements": [
        {{"tool": "<tool_name>", "improvement": "<suggestion>"}}
    ],
    "paper_claims": [
        {{
            "claim": "<statement that can go in the paper>",
            "evidence": "<specific data supporting it>",
            "confidence": "<high|medium|low>"
        }}
    ],
    "limitations": [
        "<limitation of these findings>"
    ],
    "future_work": [
        "<suggested follow-up experiment>"
    ]
}}
```"""


def condense_trajectory(trajectory, max_steps: int = 50, max_chars_per_step: int = 500) -> str:
    """
    Condense a trajectory into LLM-digestible format.
    
    Preserves:
    - Agent reasoning (truncated)
    - Tool calls with summarized arguments
    - Key results (first/last N chars)
    """
    lines = []
    step_count = 0
    
    for step in trajectory.steps:
        if step_count >= max_steps:
            lines.append(f"\n... [{len(trajectory.steps) - max_steps} more steps truncated]")
            break
        
        if step.source == "agent":
            # Agent step: show reasoning + tool calls
            thought = (step.message or "")[:max_chars_per_step]
            if len(step.message or "") > max_chars_per_step:
                thought += "..."
            
            tool_strs = []
            for tc in step.tool_calls:
                args_summary = _summarize_args(tc.arguments)
                tool_strs.append(f"{tc.function_name}({args_summary})")
            
            tools_line = " | ".join(tool_strs) if tool_strs else "[no tools]"
            lines.append(f"[{step.step_id}] {thought}")
            if tool_strs:
                lines.append(f"    -> {tools_line}")
            
            step_count += 1
        
        elif step.observation_results:
            # Tool results: summarize
            for obs in step.observation_results[:2]:  # Max 2 results per step
                content = obs.content
                if len(content) > 200:
                    content = content[:100] + "..." + content[-100:]
                if obs.error:
                    lines.append(f"    ERROR: {obs.error[:100]}")
                else:
                    lines.append(f"    <- {content}")
    
    return "\n".join(lines)


def _summarize_args(args: Dict[str, Any], max_len: int = 100) -> str:
    """Summarize tool arguments for display."""
    if not args:
        return ""
    
    parts = []
    for k, v in args.items():
        v_str = str(v)
        if len(v_str) > 50:
            v_str = v_str[:25] + "..." + v_str[-25:]
        parts.append(f"{k}={v_str}")
    
    result = ", ".join(parts)
    if len(result) > max_len:
        result = result[:max_len] + "..."
    return result


def format_test_results(verifier_results) -> str:
    """Format test results for prompt."""
    if not verifier_results:
        return "No test results available"
    
    lines = [
        f"Reward: {verifier_results.reward}",
        f"Tests: {verifier_results.tests_passed}/{verifier_results.tests_total} passed",
    ]
    
    for test in verifier_results.test_results[:5]:  # Max 5 tests
        status_emoji = "PASS" if test.status == "passed" else "FAIL"
        lines.append(f"  [{status_emoji}] {test.name}")
        if test.message and test.status != "passed":
            lines.append(f"       {test.message[:200]}")
    
    return "\n".join(lines)
