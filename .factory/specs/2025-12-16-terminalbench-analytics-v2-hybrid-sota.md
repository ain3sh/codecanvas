# terminalbench/analytics.py v2 - Hybrid SOTA Agent Analysis

## Philosophy: Two-Layer Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 2: LLM-POWERED SEMANTIC ANALYSIS (GPT-5.2)              │
│  - Strategy classification & quality assessment                 │
│  - Root cause analysis for failures                            │
│  - Counterfactual reasoning ("what if agent did X?")           │
│  - MCP utilization quality scoring                             │
│  - Cross-run insight synthesis                                 │
│  - Narrative generation for paper                              │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ feeds into
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1: DETERMINISTIC METRICS (computed from ATIF)           │
│  - Token/cost economics                                        │
│  - Step counts, tool distributions                             │
│  - Success rates, timing                                       │
│  - Pattern detection (loops, backtracks)                       │
│  - Profile comparisons with statistical tests                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Layer 1: Deterministic Metrics (No LLM)

### 1.1 Economic Metrics
```python
total_input_tokens, total_output_tokens, total_cost_usd
cost_per_success, token_efficiency (success/1M tokens)
pareto_rank  # Position on accuracy-vs-cost frontier
```

### 1.2 Process Metrics
```python
total_steps, tool_calls_count, unique_tools
tools_per_step, steps_per_minute
tool_error_rate  # From observation errors
```

### 1.3 Behavioral Patterns (regex/heuristic detection)
```python
loop_count           # Repeated identical tool calls
backtrack_count      # Edit followed by revert pattern
exploration_breadth  # Unique file paths touched
grep_before_edit     # Did agent search before modifying?
```

### 1.4 Profile Comparisons
```python
delta_metrics        # MCP - baseline for all metrics
wilcoxon_test        # Statistical significance
effect_size          # Cohen's d
```

---

## Layer 2: LLM-Powered Analysis (GPT-5.2)

### 2.1 Strategy Classification
**Input**: Full trajectory (or smart summary)
**Output**: Structured classification

```python
class StrategyAnalysis:
    primary_strategy: Literal[
        "systematic_exploration",    # Methodical file-by-file
        "hypothesis_driven",         # Form theory, test it
        "grep_and_fix",             # Find pattern, edit directly
        "trial_and_error",          # Try things until something works
        "tool_guided",              # Let MCP tools drive exploration
        "chaotic"                   # No clear strategy
    ]
    strategy_quality: float         # 0-1 score
    adaptation_events: List[str]    # "Pivoted at step 12 when..."
    reasoning_coherence: float      # Did reasoning chain make sense?
```

**Prompt Pattern**:
```
Analyze this agent trajectory for strategy patterns.

TRAJECTORY SUMMARY:
{deterministic_summary}  # Steps, tools used, key actions

FULL TRAJECTORY:
{condensed_trajectory}   # Agent thoughts + tool calls (not full outputs)

Classify the agent's strategy and assess its quality...
```

### 2.2 Failure Root Cause Analysis
**When**: Only for failed runs (reward=0)
**Output**: Actionable diagnosis

```python
class FailureAnalysis:
    root_cause: Literal[
        "incomplete_exploration",    # Didn't find the right files
        "misunderstood_task",       # Wrong interpretation
        "correct_approach_poor_execution",  # Right idea, botched it
        "knowledge_gap",            # Didn't know how to do X
        "tool_misuse",              # Used tools incorrectly
        "context_loss",             # Forgot earlier discoveries
        "premature_termination",    # Stopped too early
        "infinite_loop",            # Got stuck
    ]
    critical_step: int              # Where things went wrong
    missed_insight: str             # What it should have noticed
    counterfactual: str             # "If agent had done X at step Y..."
```

### 2.3 MCP Utilization Quality (for MCP runs only)
**Purpose**: Did the agent actually leverage the MCP tools well, or just have them?

```python
class MCPUtilizationAnalysis:
    tools_discovered: List[str]     # Which MCP tools it used
    utilization_quality: float      # 0-1: Did it use them effectively?
    
    # Specific assessments
    init_timing: Literal["early", "late", "never"]  # When did it init?
    dependency_leverage: float      # Did get_dependencies inform actions?
    search_vs_grep: str            # Did it use search_code or fall back to grep?
    structural_understanding: float # Did it build mental model from MCP?
    
    missed_opportunities: List[str] # "Could have used X to find Y"
    effective_uses: List[str]       # "Good use of get_dependencies at step 5"
```

### 2.4 Comparative Narrative Synthesis
**When**: After analyzing both profiles for same task
**Output**: Paper-ready comparative analysis

```python
class ComparativeNarrative:
    winner: Literal["text", "mcp", "tie"]
    performance_delta_explanation: str   # WHY did MCP help/hurt?
    
    # Specific contrasts
    exploration_comparison: str     # "Text agent took 15 steps to find X, MCP found it in 3"
    tool_substitution: Dict[str, str]  # {"grep": "search_code", ...}
    
    key_insight: str               # One-liner for the paper
    quote_worthy_moment: str       # Specific step that illustrates the difference
```

### 2.5 Cross-Run Insight Synthesis
**When**: After all runs analyzed
**Output**: High-level patterns for paper's discussion section

```python
class InsightSynthesis:
    task_difficulty_ranking: List[str]  # Which tasks were hardest and why
    mcp_benefit_patterns: List[str]     # "MCP helps most when..."
    mcp_overhead_patterns: List[str]    # "MCP hurts when..."
    
    emergent_findings: List[str]        # Unexpected discoveries
    recommended_improvements: List[str] # For locagent/codecanvas
    
    paper_claims: List[str]            # Supported claims with evidence
```

---

## Smart Context Management for LLM Calls

### Trajectory Condensation
Don't send raw 950KB trajectories. Build smart summaries:

```python
def condense_trajectory(traj: Trajectory) -> str:
    """Create LLM-digestible summary preserving key info."""
    
    condensed = []
    for step in traj.steps:
        if step.source == "agent":
            # Keep reasoning (truncated) + tool calls
            thought = step.message[:500] if step.message else ""
            tools = [f"{tc.function_name}({summarize_args(tc.arguments)})" 
                    for tc in (step.tool_calls or [])]
            condensed.append(f"[{step.step_id}] {thought}\n  Tools: {tools}")
        elif step.source == "user" and "tool_result" in str(step):
            # Summarize tool results (first/last 200 chars)
            condensed.append(f"  Result: {summarize_result(step)}")
    
    return "\n".join(condensed)
```

### Batch Analysis
Group related analyses to reduce API calls:

```python
# Instead of 1 call per trajectory, batch by task:
analyze_task_pair(
    task_id="sanitize-git-repo",
    text_trajectory=...,
    mcp_trajectory=...,
)  # One call gets: both failure analyses + comparative narrative
```

---

## Output Artifacts

### Deterministic Outputs
```
results/
├── metrics_raw.csv           # All numeric metrics per (task, profile)
├── metrics_summary.csv       # Aggregated by profile
├── statistical_tests.json    # Wilcoxon, effect sizes, CIs
└── figures/
    ├── pareto_frontier.png   # Accuracy vs Cost
    ├── tool_distribution.png
    └── success_by_task.png
```

### LLM-Generated Outputs
```
results/
├── strategy_analysis.json    # Per-trajectory strategy classifications
├── failure_analyses.json     # Root causes for failed runs
├── mcp_utilization.json      # MCP quality assessments
├── comparative_narratives.md # Per-task text vs MCP comparisons
├── synthesis.md              # Cross-run insights
└── paper_snippets.md         # Ready-to-use text for Results section
```

---

## Example LLM Outputs

### Failure Analysis Example
```json
{
  "task_id": "sanitize-git-repo",
  "profile": "text",
  "root_cause": "incomplete_exploration",
  "critical_step": 23,
  "missed_insight": "Agent found hf_token in ray_cluster.yaml but missed the second occurrence in the JSON file's git diff hunk",
  "counterfactual": "If agent had grepped for the exact token string 'hf_ocffijsv' after finding it once, it would have discovered all 3 locations"
}
```

### MCP Utilization Example
```json
{
  "task_id": "sanitize-git-repo", 
  "profile": "loc",
  "utilization_quality": 0.65,
  "init_timing": "early",
  "dependency_leverage": 0.3,
  "structural_understanding": 0.4,
  "missed_opportunities": [
    "Could have used get_dependencies on config files to find all secret-using modules",
    "search_code('token') would have been more targeted than grep"
  ],
  "effective_uses": [
    "Good init_repository call established working context"
  ]
}
```

### Comparative Narrative Example
```markdown
## sanitize-git-repo: Text vs LocAgent

**Winner**: Tie (both failed, but MCP was more efficient)

The text-only agent took a brute-force approach, running 47 grep 
commands across the repository. It found the AWS keys and GitHub 
token but missed the second HuggingFace token embedded in a JSON 
file's git diff output.

The LocAgent-equipped agent initialized the repository graph and 
used `get_dependencies` to identify config-related files, reducing 
exploration to 24 steps. However, it similarly missed the nested 
token, suggesting the failure mode is task-specific (tokens in 
unexpected formats) rather than tooling-related.

**Key Insight**: MCP reduced exploration overhead by 49% but didn't 
improve success rate for this task. The failure mode (tokens in git 
diff hunks) requires pattern-matching capability neither approach 
provided.
```

---

## CLI Interface

```bash
# Full analysis (deterministic + LLM)
python -m terminalbench.analytics runs/ --output results/

# Deterministic only (fast, free)
python -m terminalbench.analytics runs/ --no-llm

# LLM analysis only (assumes deterministic already run)
python -m terminalbench.analytics runs/ --llm-only

# Specific comparisons
python -m terminalbench.analytics runs/ --compare text loc --task sanitize-git-repo

# Cost estimate before running
python -m terminalbench.analytics runs/ --estimate-cost
```

---

## Implementation Modules

```python
terminalbench/
├── analytics/
│   ├── __init__.py
│   ├── parser.py          # ATIF trajectory parsing
│   ├── deterministic.py   # Layer 1 metrics computation
│   ├── llm_analysis.py    # Layer 2 GPT-5.2 integration
│   ├── prompts.py         # Prompt templates
│   ├── comparisons.py     # Profile comparison logic
│   ├── reports.py         # Output generation
│   └── cli.py             # Entry point
```

---

## Key Innovations Over Current analytics.py

| Current | New |
|---------|-----|
| Chunks trajectory, loses context | Smart condensation preserving key moments |
| Generic "judge" prompt | Task-specific analysis prompts |
| 4 vague metrics | 20+ deterministic + 5 semantic analyses |
| No profile comparison | Built-in A/B with statistics |
| Manual CSV only | Multi-format with paper-ready narratives |
| Parses claude-code.txt | Native ATIF trajectory.json |
| No cost tracking | Full economic analysis |

---

## Why This Matters for Your Paper

1. **Quantitative rigor** (Layer 1): Statistical tests, effect sizes, Pareto analysis
2. **Qualitative depth** (Layer 2): "Why" not just "what" - publishable insights
3. **Direct paper integration**: Generates comparative narratives ready for Results section
4. **MCP-specific analysis**: Proves whether your tools actually help (not just "were available")