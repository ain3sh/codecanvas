# TerminalBench Analytics

Hybrid evaluation framework for LLM agent trajectories. Combines deterministic metrics (Layer 1) with LLM-powered semantic analysis (Layer 2) to produce publication-ready insights.

**Quick start:**
```bash
python -m terminalbench.analytics results/runs/ --output results/analytics/
```

---

## Table of Contents

1. [Motivation](#motivation)
2. [Architecture](#architecture)
3. [Data Sources](#data-sources)
4. [Layer 1: Deterministic Analysis](#layer-1-deterministic-analysis)
5. [Layer 2: Intelligent Analysis](#layer-2-intelligent-analysis)
6. [CodeCanvas Extensions](#codecanvas-extensions)
7. [Outputs](#outputs)
8. [Setup](#setup)
9. [CLI Reference](#cli-reference)
10. [Interpreting Results](#interpreting-results)
11. [Implementation](#implementation)

---

## Motivation

### The Evaluation Problem

Standard LLM benchmarks report binary pass/fail. This tells you *what* happened but not *why* or *how*. When comparing agent configurations (text-only vs MCP-enhanced), we need richer signals:

- Did the MCP tools actually get used effectively, or just called?
- When agents fail, what's the root cause?
- Did visual blast radius analysis change editing behavior?
- Are efficiency gains from better strategy or just fewer iterations?

### Two-Layer Solution

| Layer | Nature | Cost | Use Case |
|-------|--------|------|----------|
| **Layer 1: Deterministic** | Computed from trajectory data | Free | Quantitative claims, reproducible metrics |
| **Layer 2: Intelligent** | GPT-5.2 semantic analysis | ~$0.05/trajectory | Qualitative depth, root causes, narratives |

Layer 1 gives you the numbers. Layer 2 explains what they mean.

### Research Questions This Framework Answers

1. **Efficiency**: Do MCP tools reduce token consumption for equivalent outcomes?
2. **Strategy**: Do MCP tools change *how* agents approach problems?
3. **Failure Modes**: Do MCP-enhanced agents fail differently than baselines?
4. **Visual Impact**: Does seeing blast radius visualizations change editing behavior? (CodeCanvas-specific)
5. **Deliberation**: Does the Evidence Board encourage planning before acting? (CodeCanvas-specific)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    TerminalBench Analytics                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  Layer 2: Intelligent Analysis (GPT-5.2)                        │   │
│  │                                                                  │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐    │   │
│  │  │   Strategy   │  │   Failure    │  │   MCP Utilization  │    │   │
│  │  │Classification│  │  Root Cause  │  │      Quality       │    │   │
│  │  └──────────────┘  └──────────────┘  └────────────────────┘    │   │
│  │                                                                  │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐    │   │
│  │  │ Comparative  │  │   Insight    │  │  CodeCanvas Vision │    │   │
│  │  │  Narratives  │  │  Synthesis   │  │     Analysis       │    │   │
│  │  └──────────────┘  └──────────────┘  └────────────────────┘    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                              │ enriches                                 │
│  ┌───────────────────────────▼─────────────────────────────────────┐   │
│  │  Layer 1: Deterministic Metrics                                  │   │
│  │                                                                  │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────────┐  │   │
│  │  │ Outcome  │ │ Economic │ │ Process  │ │ Behavioral        │  │   │
│  │  │ Metrics  │ │ Metrics  │ │ Metrics  │ │ Patterns          │  │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └───────────────────┘  │   │
│  │                                                                  │   │
│  │  ┌───────────────────────────────────────────────────────────┐  │   │
│  │  │  CodeCanvas Extension: Informed Editing Score              │  │   │
│  │  │  blast_radius_edit_rate | anticipated_failure_rate |       │  │   │
│  │  │  deliberation_depth | reasoning_density | systematic_prog  │  │   │
│  │  └───────────────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                              │ computed from                            │
│  ┌───────────────────────────▼─────────────────────────────────────┐   │
│  │  Data Sources                                                    │   │
│  │                                                                  │   │
│  │  trajectory.json    verifier/ctrf.json    state.json            │   │
│  │  (ATIF trace)       (test results)        (CodeCanvas state)    │   │
│  │                                                                  │   │
│  │  architecture.png   impact_*.png          board.png             │   │
│  │  (init viz)         (blast radius)        (evidence board)      │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Module Structure

```
terminalbench/analytics/
├── __init__.py              # Package exports
├── __main__.py              # Entry: python -m terminalbench.analytics
│
├── core/                    # Analysis pillars
│   ├── deterministic.py     # Layer 1: Free, fast, reproducible metrics
│   ├── intelligent.py       # Layer 2: GPT-5.2 semantic analysis
│   └── comparisons.py       # Statistical tests (Wilcoxon, Cohen's h)
│
├── io/                      # Input/output
│   ├── parser.py            # ATIF trajectory parsing
│   ├── cli.py               # CLI orchestration
│   └── reports.py           # Output generation (CSV, JSON, Markdown)
│
└── extensions/              # Extensions
    ├── prompts.py           # All LLM prompts (text + vision)
    └── codecanvas.py        # CodeCanvas-specific analytics (both layers)
```

---

## Data Sources

### Run Directory Structure

```
results/runs/
├── index.json                           # Run manifest
└── 2025-01-15__14-30-00__codecanvas/    # Timestamp + profile
    └── sanitize-git-repo/               # Task ID
        ├── agent/
        │   ├── trajectory.json          # ATIF-format trace
        │   └── sessions/
        │       └── codecanvas/          # CodeCanvas artifacts
        │           ├── state.json       # Evidence, claims, decisions
        │           ├── architecture.png # Init visualization
        │           ├── impact_*.png     # Blast radius visualizations
        │           └── board.png        # Evidence Board snapshot
        ├── verifier/
        │   ├── ctrf.json               # Test results (CTRF format)
        │   └── reward.txt              # Binary reward (0 or 1)
        └── result.json                  # Timing, metadata
```

### File Contents

| File | Format | Contents | Used For |
|------|--------|----------|----------|
| `index.json` | JSON | Run manifest with profile keys, task IDs, paths | Discovering runs |
| `trajectory.json` | ATIF | Agent trace: steps, tool calls, tokens, costs | All Layer 1 metrics |
| `ctrf.json` | CTRF | Per-test pass/fail with names and durations | Success metrics, anticipated failures |
| `reward.txt` | Text | Single float (0.0 or 1.0) | Binary success |
| `state.json` | JSON | CodeCanvas state: evidence, claims, decisions, analyses | CodeCanvas extension metrics |
| `*.png` | Image | Visualizations (architecture, impact, board) | Vision analysis (Layer 2) |

### ATIF Trajectory Format

Trajectories follow [ATIF v1.2+](https://harborframework.com/docs/trajectory-format):

```json
{
  "schema_version": "1.2",
  "session_id": "abc123",
  "agent": {"name": "claude-code", "model_name": "claude-sonnet-4-20250514"},
  "steps": [
    {
      "step_id": 1,
      "timestamp": "2025-01-15T14:30:00Z",
      "source": "agent",
      "message": "I'll start by examining the repository structure...",
      "tool_calls": [
        {"tool_call_id": "tc_1", "function_name": "Read", "arguments": {"file_path": "src/main.py"}}
      ],
      "metrics": {"prompt_tokens": 1500, "completion_tokens": 200, "cost_usd": 0.01}
    }
  ],
  "final_metrics": {"total_prompt_tokens": 50000, "total_cost_usd": 0.50}
}
```

### CodeCanvas State Format

```json
{
  "initialized": true,
  "evidence": [
    {"id": "E1", "kind": "architecture", "png_path": "architecture.png", "metrics": {"nodes": 45}},
    {"id": "E2", "kind": "impact", "symbol": "process_data", "metrics": {"callers": 3, "callees": 2}}
  ],
  "claims": [
    {"id": "C1", "kind": "hypothesis", "text": "Changing process_data may break validate_input", "evidence_ids": ["E2"]}
  ],
  "decisions": [
    {"id": "D1", "kind": "plan", "text": "Update process_data signature, then fix callers", "evidence_ids": ["E2"]}
  ],
  "analyses": {
    "process_data": {
      "target_id": "func_123",
      "affected_ids": ["func_456", "func_789", "func_101"],
      "addressed_ids": ["func_456"],
      "skipped_ids": ["func_101"]
    }
  },
  "symbol_files": {"func_123": "src/data.py", "func_456": "src/validate.py"}
}
```

---

## Layer 1: Deterministic Analysis

All metrics computed directly from trajectory data. Free, fast, and reproducible.

### Outcome Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `success` | bool | Task completed successfully (reward = 1.0) |
| `reward` | float | Raw reward value from verifier |
| `tests_passed` | int | Number of passing tests |
| `tests_failed` | int | Number of failing tests |
| `tests_total` | int | Total test count |
| `tests_passed_ratio` | float | Partial credit: passed / total |

### Economic Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `total_input_tokens` | int | Prompt tokens consumed |
| `total_output_tokens` | int | Completion tokens generated |
| `total_tokens` | int | Sum of input + output |
| `total_cost_usd` | float | API cost (from trajectory or estimated) |
| `cost_per_success` | float | Cost if succeeded, else ∞ |
| `token_efficiency` | float | Success per 1M tokens (higher = better) |

**Interpretation**: Lower tokens/cost for same outcome = more efficient. `cost_per_success` enables fair comparison even when success rates differ.

### Process Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `total_steps` | int | Total trajectory steps |
| `agent_steps` | int | Steps where source = "agent" |
| `tool_calls_count` | int | Total tool invocations |
| `unique_tools` | int | Distinct tools used |
| `tools_per_step` | float | Tool density (calls / agent_steps) |
| `steps_per_minute` | float | Execution speed |
| `elapsed_sec` | float | Wall-clock time |

### Tool Usage Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `tool_distribution` | dict | `{tool_name: count}` |
| `tool_success_rate` | float | 1 - (errors / calls) |
| `tool_error_count` | int | Failed tool invocations |
| `mcp_tools_used` | list | MCP tools invoked (e.g., `["canvas", "init_repository"]`) |
| `mcp_tool_calls` | int | Count of MCP tool calls |
| `native_tool_calls` | int | Count of Claude Code native tools |

**MCP Tool Detection**: Tools prefixed with `mcp__` or matching known base names (`canvas`, `init_repository`, `get_dependencies`, etc.) are classified as MCP tools.

### Behavioral Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `loop_count` | int | Repeated identical tool calls (potential infinite loops) |
| `backtrack_count` | int | Edit-then-re-edit patterns (same file edited multiple times) |
| `exploration_breadth` | int | Unique files touched (read + edited) |
| `files_read` | set | Files read via Read/Grep/Glob |
| `files_edited` | set | Files modified via Edit/MultiEdit/Create |
| `grep_before_edit` | bool | Did agent search before modifying? |

### Failure Indicators

Heuristic flags for common failure patterns:

| Indicator | Triggered When |
|-----------|----------------|
| `tool_misuse` | >30% of tool calls result in errors |
| `infinite_loop` | >5 repeated identical tool calls |
| `budget_exhaustion` | Failed with >80k tokens consumed |
| `premature_stop` | Failed with <10 steps |
| `context_omission` | (Reserved for future use) |

---

## Layer 2: Intelligent Analysis

LLM-powered semantic analysis using GPT-5.2. Requires API key, costs ~$0.05/trajectory.

### Strategy Classification

**Triggered**: All trajectories

**Output**: Primary strategy type, quality score, adaptation events

| Strategy | Description |
|----------|-------------|
| `systematic_exploration` | Methodical file-by-file or module-by-module exploration |
| `hypothesis_driven` | Forms theories, tests them, adapts based on results |
| `grep_and_fix` | Finds patterns via search, directly edits matches |
| `trial_and_error` | Tries things until something works, no clear plan |
| `tool_guided` | Lets MCP/specialized tools drive exploration |
| `chaotic` | No discernible strategy, random actions |

**Quality Score** (0-1): How well-executed was the strategy? A `hypothesis_driven` approach with quality 0.9 beats `systematic_exploration` with quality 0.3.

### Failure Root Cause Analysis

**Triggered**: Failed trajectories (`success = False`)

**Output**: Root cause category, critical step, counterfactual

| Root Cause | Description |
|------------|-------------|
| `incomplete_exploration` | Didn't find/examine necessary files or code |
| `misunderstood_task` | Interpreted requirements incorrectly |
| `correct_approach_poor_execution` | Right strategy, but implementation errors |
| `knowledge_gap` | Lacked necessary domain knowledge |
| `tool_misuse` | Used tools incorrectly or inefficiently |
| `context_loss` | Forgot or ignored earlier discoveries |
| `premature_termination` | Stopped before completing the task |
| `infinite_loop` | Got stuck repeating actions |

**Counterfactual**: "If agent had done X at step Y, outcome would be Z" — directly actionable for tool improvement.

### MCP Utilization Analysis

**Triggered**: Trajectories with `mcp_tool_calls > 0`

**Output**: Utilization quality, missed opportunities, effective uses

| Field | Description |
|-------|-------------|
| `utilization_quality` | 0-1 score of how effectively MCP tools were used |
| `init_timing` | `early` / `late` / `never` — when was repo initialized? |
| `dependency_leverage` | 0-1 — did agent use structural info from MCP? |
| `search_effectiveness` | 0-1 — did MCP search outperform grep patterns? |
| `missed_opportunities` | List of MCP features that could have helped but weren't used |
| `effective_uses` | List of MCP features used well |

### Comparative Narratives

**Triggered**: Multiple profiles for same task

**Output**: Winner determination, key insight, paper-ready paragraph

Compares trajectories head-to-head:
- Which profile won and why?
- What was the key differentiator?
- Quote-worthy moments that illustrate the difference

**Paper-Ready Paragraph**: Directly quotable text for Results section.

### Insight Synthesis

**Triggered**: After all individual analyses complete

**Output**: Cross-run patterns, paper claims with evidence

| Field | Description |
|-------|-------------|
| `task_difficulty_ranking` | Tasks ranked by difficulty with explanations |
| `mcp_benefit_patterns` | Patterns where MCP tools provided clear benefit |
| `mcp_overhead_patterns` | Patterns where MCP tools added overhead |
| `emergent_findings` | Unexpected discoveries from the data |
| `paper_claims` | Statements with evidence and confidence levels |
| `limitations` | Caveats for the findings |
| `future_work` | Suggested follow-up experiments |

### Vision Analysis (CodeCanvas)

**Triggered**: Trajectories with CodeCanvas PNG images

**Output**: Visual-edit alignment, evidence board quality, architecture understanding

Uses GPT-5.2's vision capabilities to analyze:

1. **Visual-Edit Alignment**: Did the agent's edits align with visualized blast radius?
2. **Evidence Board Quality**: Is there a logical evidence → claim → decision flow?
3. **Architecture Understanding**: Did exploration pattern match the visualized structure?

---

## CodeCanvas Extensions

CodeCanvas-specific analytics that answer: **"Did seeing blast radius visually change agent behavior?"**

### Core Insight: The Informed Editing Score

A composite metric capturing whether visual impact analysis influenced editing decisions:

```
informed_editing_score = (
    0.4 × blast_radius_edit_rate +      # Did you edit where you looked?
    0.3 × anticipated_failure_rate +    # Were failures expected?
    0.3 × deliberation_depth / 3        # Did you plan before acting?
)
```

Higher score = more informed, deliberate editing behavior.

### Deterministic Metrics (Layer 1)

| Metric | Type | Description |
|--------|------|-------------|
| `evidence_count` | int | Impact/architecture visualizations created |
| `claims_count` | int | Hypotheses, findings, questions recorded |
| `decisions_count` | int | Plans, edits, marks, skips committed |
| `impact_analyses_count` | int | Blast radius analyses performed |

**Claim Breakdown**:
| Metric | Description |
|--------|-------------|
| `hypotheses_count` | "I think X might cause Y" |
| `findings_count` | "X depends on Y via Z" |
| `questions_count` | "Does X handle null inputs?" |

**Decision Breakdown**:
| Metric | Description |
|--------|-------------|
| `marks_count` | Symbols verified/addressed |
| `skips_count` | Symbols intentionally ignored |
| `plans_count` | Committed plans before editing |
| `edits_count` | Edit decisions recorded |

### Blast Radius Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `blast_radius_edit_rate` | float | % of edits within analyzed impact zones |
| `edits_in_blast_radius` | int | Files edited that were in a blast radius |
| `edits_outside_blast_radius` | int | Files edited outside any analyzed blast radius |
| `total_affected_symbols` | int | Symbols in all blast radii |
| `total_addressed_symbols` | int | Symbols explicitly marked as done |
| `total_skipped_symbols` | int | Symbols explicitly skipped |
| `systematic_progress` | float | (addressed + skipped) / affected |

**Interpretation**: High `blast_radius_edit_rate` means the agent edited where they looked — visual analysis informed their actions. Low rate suggests the agent ignored or didn't understand the visualization.

### Test-Failure Anticipation

| Metric | Type | Description |
|--------|------|-------------|
| `anticipated_failure_rate` | float | % of test failures that were in a previously-analyzed blast radius |
| `failed_tests_in_blast_radius` | int | Failures the agent "should have seen coming" |
| `failed_tests_outside_blast_radius` | int | Surprise failures |

**Interpretation**: High `anticipated_failure_rate` means when the agent broke tests, they had already analyzed the relevant code — they understood their changes might have consequences. Low rate means failures were surprises.

### Deliberation Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `deliberation_depth` | int | Claims + plans recorded (proxy for thinking before acting) |
| `reasoning_density` | float | Claims per evidence item (how much reasoning per visual?) |

**Interpretation**: Higher deliberation = agent used Evidence Board to plan rather than jumping to edits.

### Vision Metrics (Layer 2)

| Metric | Type | Description |
|--------|------|-------------|
| `impact_alignment.alignment_score` | float | Did edits match visualized blast radius? |
| `impact_alignment.visual_understanding` | str | `low` / `medium` / `high` |
| `board_quality.board_quality_score` | float | Quality of reasoning trail |
| `board_quality.reasoning_style` | str | `systematic` / `hypothesis_driven` / `reactive` / `chaotic` |
| `architecture_understanding.edit_appropriateness` | float | Did edits make sense given architecture? |

---

## Outputs

All outputs written to `--output` directory (default: `results/analytics/`).

### Layer 1 Outputs

| File | Format | Contents |
|------|--------|----------|
| `metrics_detail.csv` | CSV | One row per trajectory, all deterministic metrics |
| `metrics_summary.csv` | CSV | Aggregated by profile (success rates, averages) |
| `aggregate_metrics.json` | JSON | Profile aggregates with full tool distributions |
| `comparison_report.md` | Markdown | Statistical comparison tables with p-values |

### Layer 2 Outputs

| File | Format | Contents |
|------|--------|----------|
| `strategy_analysis.json` | JSON | Per-trajectory strategy classifications |
| `failure_analyses.json` | JSON | Root cause diagnoses for failures |
| `mcp_utilization.json` | JSON | MCP usage quality assessments |
| `comparative_narratives.md` | Markdown | Per-task profile comparisons |
| `synthesis.md` | Markdown | Cross-run insights, paper claims |
| `paper_snippets.md` | Markdown | Ready-to-use Results section text |

### CodeCanvas Outputs

| File | Format | Contents |
|------|--------|----------|
| `codecanvas_comparison.md` | Markdown | Informed Editing Score comparison across profiles |
| `codecanvas_analysis.json` | JSON | Per-run CodeCanvas metrics + vision analysis |

---

## Setup

### Dependencies

```bash
pip install python-dotenv litellm scipy pandas
```

Or if using the project's environment:
```bash
uv sync  # If using uv
```

### API Key Configuration

Layer 2 analysis requires an OpenRouter API key:

**Option 1: Environment file (recommended)**
```bash
# terminalbench/.env
OPENROUTER_API_KEY=your_key_here
```

**Option 2: Export directly**
```bash
export OPENROUTER_API_KEY=your_key_here
```

The analytics module auto-loads `terminalbench/.env` if it exists.

### Cost Estimation

Before running full analysis, estimate costs:
```bash
python -m terminalbench.analytics results/runs/ --estimate-cost
```

Typical costs:
- ~$0.05 per trajectory for strategy + failure analysis
- ~$0.03 additional for MCP utilization analysis
- ~$0.04 per comparative narrative
- ~$0.02 per vision analysis (CodeCanvas images)
- ~$0.10 for final synthesis

---

## CLI Reference

### Basic Usage

```bash
python -m terminalbench.analytics <runs_dir> [options]
```

### Selection Flags

| Flag | Description |
|------|-------------|
| `--tasks TASK [...]` | Filter to specific task IDs |
| `--profiles PROFILE [...]` | Filter to specific profiles (e.g., `text`, `codegraph`, `codecanvas`) |
| `--succeeded` | Only analyze successful runs |
| `--failed` | Only analyze failed runs |
| `--limit N` | Randomly sample N trajectories (useful for testing) |

### Analysis Flags

| Flag | Description |
|------|-------------|
| `--no-llm` | Skip Layer 2 analysis (deterministic only, fast & free) |
| `--llm-only` | Skip Layer 1 metrics (assumes deterministic already done) |
| `--compare A B` | Compare two specific profiles |
| `--model MODEL` | LLM model for analysis (default: `openrouter/openai/gpt-5.2`) |

### Inspection Flags

| Flag | Description |
|------|-------------|
| `--list` | List discovered runs and exit (no processing) |
| `--estimate-cost` | Estimate LLM analysis cost and exit |

### Output Flags

| Flag | Description |
|------|-------------|
| `--output, -o DIR` | Output directory (default: `results/analytics/`) |
| `--quiet, -q` | Suppress progress output |

### Example Workflows

```bash
# 1. Preview available data
python -m terminalbench.analytics results/runs/ --list

# 2. Quick test (deterministic only, no API cost)
python -m terminalbench.analytics results/runs/ --limit 3 --no-llm -o results/test/

# 3. Estimate LLM cost before committing
python -m terminalbench.analytics results/runs/ --estimate-cost

# 4. Full analysis
python -m terminalbench.analytics results/runs/ -o results/analytics/

# 5. Compare specific profiles
python -m terminalbench.analytics results/runs/ --compare text codecanvas

# 6. Failure-focused analysis
python -m terminalbench.analytics results/runs/ --failed -o results/failures/

# 7. Filter to specific tasks
python -m terminalbench.analytics results/runs/ --tasks sanitize-git-repo build-cython-ext

# 8. CodeCanvas runs only
python -m terminalbench.analytics results/runs/ --profiles codecanvas --succeeded
```

---

## Interpreting Results

### Key Comparisons for the Paper

#### 1. Efficiency (text-only vs MCP)

From `metrics_summary.csv`:
```
| Profile    | Success Rate | Avg Tokens | Avg Cost |
|------------|--------------|------------|----------|
| text       | 40%          | 85,000     | $0.42    |
| codegraph  | 55%          | 72,000     | $0.36    |
| codecanvas | 60%          | 68,000     | $0.34    |
```

**Claim template**: "CodeCanvas-enhanced agents achieved X% higher success rate while consuming Y% fewer tokens."

#### 2. Strategy Differences

From `strategy_analysis.json`:
- Compare `primary_strategy` distribution across profiles
- Compare `strategy_quality` averages

**Claim template**: "MCP-enhanced agents exhibited more `hypothesis_driven` strategies (X% vs Y%), suggesting structural information enables more deliberate problem-solving."

#### 3. Failure Mode Differences

From `failure_analyses.json`:
- Compare `root_cause` distribution across profiles

**Claim template**: "Text-only agents failed primarily due to `incomplete_exploration` (X%), while CodeCanvas agents failed due to `correct_approach_poor_execution` (Y%), suggesting visual analysis helps agents find relevant code but doesn't guarantee correct edits."

#### 4. CodeCanvas Behavioral Change (NEW)

From `codecanvas_comparison.md`:
```
| Profile    | Informed Editing Score | Blast Radius Edit Rate | Deliberation Depth |
|------------|------------------------|------------------------|-------------------|
| text       | N/A                    | N/A                    | N/A               |
| codecanvas | 0.72                   | 0.78                   | 2.3               |
```

**Claim template**: "Agents with visual blast radius analysis confined X% of their edits to previously-analyzed impact zones, compared to Y% for baselines (where this metric cannot be computed due to absence of impact analysis)."

From `codecanvas_analysis.json`:
- `anticipated_failure_rate`: "When CodeCanvas agents broke tests, X% of those failures were in files the agent had previously analyzed — they knew changes might have consequences."

#### 5. Tool Substitution

From `tool_distribution` in `aggregate_metrics.json`:
- Did MCP tools replace `Grep` patterns?
- Did `canvas` calls correlate with fewer `Read` calls?

**Claim template**: "Agents using CodeCanvas's `impact` action reduced raw `Grep` usage by X%, suggesting visual blast radius replaced pattern-based exploration."

### Statistical Notes

- **Wilcoxon signed-rank test**: Used for paired comparisons (same task, different profiles)
- **Cohen's h**: Effect size for proportion differences (success rates)
- **p < 0.05**: Marked with `*` in comparison tables

With small sample sizes (n < 10 per condition), focus on effect sizes over p-values. Report confidence intervals where possible.

### What to Quote in the Paper

| Source | What to Extract |
|--------|-----------------|
| `metrics_summary.csv` | Success rates, token/cost efficiency |
| `codecanvas_comparison.md` | Informed Editing Score, Blast Radius Edit Rate |
| `comparative_narratives.md` | Per-task winner explanations, key insights |
| `synthesis.md` | Paper claims with evidence, task difficulty rankings |
| `paper_snippets.md` | Ready-to-use Results section text |
| `codecanvas_analysis.json` | Evidence Board usage patterns, vision analysis scores |

---

## Implementation

### Module Reference

| Module | Responsibility |
|--------|----------------|
| `io/parser.py` | ATIF trajectory parsing, run discovery |
| `io/cli.py` | CLI argument parsing, orchestration |
| `io/reports.py` | Output generation (CSV, JSON, Markdown) |
| `core/deterministic.py` | Layer 1 metric computation |
| `core/intelligent.py` | Layer 2 GPT-5.2 analysis |
| `core/comparisons.py` | Statistical tests (Wilcoxon, Cohen's h) |
| `extensions/prompts.py` | All LLM prompts (text + vision) |
| `extensions/codecanvas.py` | CodeCanvas state parsing, metrics, vision analyzer |

### Entry Point

```bash
python -m terminalbench.analytics
```

Invokes `terminalbench/analytics/__main__.py` → `io/cli.py:main()`

### Adding New Metrics

1. **Deterministic metric**: Add to `DeterministicMetrics` dataclass in `core/deterministic.py`, compute in `compute_metrics()`
2. **LLM analysis**: Add method to `LLMAnalyzer` in `core/intelligent.py`, add prompt to `extensions/prompts.py`
3. **CodeCanvas metric**: Add to `CodeCanvasMetrics` in `extensions/codecanvas.py`, compute in `compute_codecanvas_metrics()`
4. **Report output**: Add writer method to `ReportGenerator` in `io/reports.py`

### Extending for New Profiles

MCP tool detection is handled by `is_mcp_tool()` in `core/deterministic.py`. To add new MCP tools:

```python
MCP_TOOL_BASE_NAMES = {
    "canvas",           # CodeCanvas
    "init_repository",  # CodeGraph/locagent
    "get_dependencies",
    "search_code",
    # Add new tools here
}
```

---

## Appendix: Design Rationale

### Why Two Layers?

| Concern | Layer 1 (Deterministic) | Layer 2 (Intelligent) |
|---------|-------------------------|----------------------|
| Cost | Free | ~$0.05/trajectory |
| Reproducibility | Perfect | LLM variance |
| Speed | Fast | Slow |
| Depth | Surface metrics | Root causes, narratives |
| Use in paper | Quantitative claims | Qualitative depth |

Deterministic metrics are the foundation — they're what you can confidently report as numbers. LLM analysis explains *why* those numbers look the way they do.

### Why Informed Editing Score?

The core research question for CodeCanvas is: "Does seeing blast radius visually change how agents edit code?"

Raw metrics like "MCP tool calls" don't answer this — an agent could call `canvas(action="impact")` and then ignore the result. The Informed Editing Score directly measures behavioral change:

- **Blast Radius Edit Rate**: Did you edit where you looked?
- **Anticipated Failure Rate**: Did you expect what broke?
- **Deliberation Depth**: Did you think before acting?

A high score means visual analysis actually influenced behavior, not just that tools were invoked.

### Why Vision Analysis?

Some questions can only be answered by looking at the images:

- "Did the agent's edits match the visualized dependency structure?"
- "Does the Evidence Board show a coherent reasoning trail?"

Text extraction from state.json gives us counts (claims, decisions), but vision analysis gives us *quality* assessments that require understanding the visual representation.
