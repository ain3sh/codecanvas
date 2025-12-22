# Running TerminalBench Analytics

Hybrid evaluation framework for LLM agent trajectories. Combines deterministic metrics (Layer 1) with LLM-powered semantic analysis (Layer 2) to produce publication-ready insights.

**Quick start:** `python -m terminalbench.analytics results/runs/ --output results/analytics/`

## Architecture

```
┌────────────────────────────────────────────────────────┐
│  Layer 2: LLM Analysis (GPT-5.2)                       │
│  Strategy classification, failure diagnosis,           │
│  MCP utilization quality, comparative narratives       │
└───────────────────────┬────────────────────────────────┘
                        │ enriches
┌───────────────────────▼────────────────────────────────┐
│  Layer 1: Deterministic Metrics                        │
│  Tokens, costs, steps, tool usage, behavioral patterns │
└───────────────────────┬────────────────────────────────┘
                        │ computed from
┌───────────────────────▼────────────────────────────────┐
│  Data Sources: results/runs/{timestamp}/{task}/        │
│  trajectory.json, verifier/ctrf.json, result.json      │
└────────────────────────────────────────────────────────┘
```

**Why two layers?** Deterministic metrics are fast, free, and reproducible—use them for quantitative claims. LLM analysis extracts insights that require understanding (strategy quality, root causes, counterfactuals)—use them for qualitative depth.

## Data Sources

| File | Contents | Used For |
|------|----------|----------|
| `results/runs/index.json` | Run manifest with profile keys, task IDs | Discovering runs |
| `trajectory.json` | ATIF-format agent trace (steps, tool calls, tokens) | All metrics |
| `verifier/ctrf.json` | Test results (pass/fail per test) | Success metrics |
| `verifier/reward.txt` | Final reward (0 or 1) | Binary success |
| `result.json` | Timing, aggregate stats | Elapsed time |

Trajectories follow the [ATIF v1.2+ spec](https://harborframework.com/docs/trajectory-format).

## Layer 1: Deterministic Metrics

### Outcome Metrics
| Metric | Description |
|--------|-------------|
| `success` | Binary task success (reward = 1.0) |
| `reward` | Raw reward value |
| `tests_passed` / `tests_total` | From verifier CTRF |
| `tests_passed_ratio` | Partial credit score |

### Economic Metrics
| Metric | Description |
|--------|-------------|
| `total_input_tokens` | Prompt tokens consumed |
| `total_output_tokens` | Completion tokens generated |
| `total_tokens` | Sum of input + output |
| `total_cost_usd` | API cost (from trajectory or estimated) |
| `cost_per_success` | Cost if succeeded, else ∞ |
| `token_efficiency` | Success per 1M tokens |

### Process Metrics
| Metric | Description |
|--------|-------------|
| `total_steps` | Total trajectory steps |
| `agent_steps` | Steps where source = "agent" |
| `tool_calls_count` | Total tool invocations |
| `unique_tools` | Distinct tools used |
| `tools_per_step` | Tool density |
| `steps_per_minute` | Execution speed |
| `elapsed_sec` | Wall-clock time |

### Tool Usage Metrics
| Metric | Description |
|--------|-------------|
| `tool_distribution` | `{tool_name: count}` |
| `tool_success_rate` | 1 - (errors / calls) |
| `tool_error_count` | Failed tool invocations |
| `mcp_tools_used` | List of MCP tools invoked |
| `mcp_tool_calls` | Count of MCP tool calls |
| `native_tool_calls` | Count of Claude Code native tools |

### Behavioral Metrics
| Metric | Description |
|--------|-------------|
| `loop_count` | Repeated identical tool calls (potential loops) |
| `backtrack_count` | Edit-then-re-edit patterns |
| `exploration_breadth` | Unique files touched |
| `files_read` / `files_edited` | File operation sets |
| `grep_before_edit` | Did agent search before modifying? |
| `failure_indicators` | Heuristic flags (context_omission, tool_misuse, infinite_loop, budget_exhaustion, premature_stop) |

## Layer 2: LLM Analysis

| Analysis | Triggered When | Produces |
|----------|----------------|----------|
| **Strategy Classification** | All trajectories | Primary strategy type, quality score, adaptation events |
| **Failure Root Cause** | `success = False` | Root cause category, critical step, counterfactual |
| **MCP Utilization** | `mcp_tool_calls > 0` | Utilization quality, missed opportunities, effective uses |
| **Comparative Narrative** | Multiple profiles for same task | Winner, key insight, paper-ready paragraph |
| **Insight Synthesis** | After all analyses | Task rankings, MCP patterns, paper claims |

### Strategy Types
`systematic_exploration` · `hypothesis_driven` · `grep_and_fix` · `trial_and_error` · `tool_guided` · `chaotic`

### Failure Root Causes
`incomplete_exploration` · `misunderstood_task` · `correct_approach_poor_execution` · `knowledge_gap` · `tool_misuse` · `context_loss` · `premature_termination` · `infinite_loop`

## Outputs

All outputs written to `--output` directory (default: `results/analytics/`).

| File | Format | Contents |
|------|--------|----------|
| `metrics_detail.csv` | CSV | One row per trajectory, all metrics |
| `metrics_summary.csv` | CSV | Aggregated by profile |
| `aggregate_metrics.json` | JSON | Profile aggregates with tool distributions |
| `comparison_report.md` | Markdown | Statistical comparison tables |
| `strategy_analysis.json` | JSON | Per-trajectory strategy classifications |
| `failure_analyses.json` | JSON | Root cause diagnoses for failures |
| `mcp_utilization.json` | JSON | MCP usage quality assessments |
| `comparative_narratives.md` | Markdown | Per-task profile comparisons |
| `synthesis.md` | Markdown | Cross-run insights, paper claims |
| `paper_snippets.md` | Markdown | Ready-to-use Results section text |

## Setup

### Dependencies
```bash
pip install python-dotenv litellm scipy pandas
```

### API Key Configuration
For LLM analysis (Layer 2), set your OpenRouter API key:

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

## CLI Reference

### Selection Flags
| Flag | Description |
|------|-------------|
| `--tasks TASK [...]` | Filter to specific task IDs |
| `--profiles PROFILE [...]` | Filter to specific profiles (e.g., text, codegraph, codecanvas) |
| `--succeeded` | Only analyze successful runs |
| `--failed` | Only analyze failed runs |
| `--limit N` | Randomly sample N trajectories |

### Analysis Flags
| Flag | Description |
|------|-------------|
| `--no-llm` | Skip LLM analysis (Layer 1 only, fast & free) |
| `--llm-only` | Skip deterministic metrics (Layer 2 only) |
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

## Usage

```bash
# Deterministic metrics only (fast, free, no API key needed)
python -m terminalbench.analytics results/runs/ --no-llm

# Full analysis with LLM insights (requires API key)
python -m terminalbench.analytics results/runs/ --output results/analytics/

# Compare specific profiles
python -m terminalbench.analytics results/runs/ --compare text codegraph

# Filter to specific tasks
python -m terminalbench.analytics results/runs/ --tasks sanitize-git-repo build-cython-ext

# Estimate LLM cost before running
python -m terminalbench.analytics results/runs/ --estimate-cost

# Use different LLM model
python -m terminalbench.analytics results/runs/ --model openrouter/openai/gpt-5.2
```

### Selection & Filtering

```bash
# List all discovered runs without processing
python -m terminalbench.analytics results/runs/ --list

# Filter by profile(s)
python -m terminalbench.analytics results/runs/ --profiles text codegraph

# Filter by outcome
python -m terminalbench.analytics results/runs/ --succeeded   # only passing runs
python -m terminalbench.analytics results/runs/ --failed      # only failing runs

# Random sample N trajectories (useful for testing before full run)
python -m terminalbench.analytics results/runs/ --limit 3 --no-llm

# Combine filters
python -m terminalbench.analytics results/runs/ --profiles codecanvas --succeeded --tasks sanitize-git-repo
```

### Common Workflows

```bash
# 1. Preview what's available
python -m terminalbench.analytics results/runs/ --list

# 2. Test on small subset (no LLM cost)
python -m terminalbench.analytics results/runs/ --limit 3 --no-llm -o results/test/

# 3. Estimate LLM cost before committing
python -m terminalbench.analytics results/runs/ --estimate-cost

# 4. Full analysis
python -m terminalbench.analytics results/runs/ -o results/analytics/

# 5. Failure-focused analysis
python -m terminalbench.analytics results/runs/ --failed -o results/failures/
```

## Interpreting Results

### Key Comparisons (text-only vs MCP)

1. **Efficiency**: Compare `total_tokens` and `total_steps`. Lower is better for same outcome.
2. **Tool substitution**: Check `tool_distribution`—did MCP tools replace grep/read patterns?
3. **Success rate**: Statistical significance requires multiple runs per task.

### Statistical Notes

- **Wilcoxon signed-rank test**: Used for paired comparisons (same task, different profiles).
- **Cohen's h**: Effect size for proportion differences (success rates).
- **p < 0.05**: Marked with `*` in comparison tables.

With small sample sizes (n < 10 per condition), focus on effect sizes over p-values.

### What to Report in Paper

From `metrics_summary.csv`:
- Success rate per profile
- Average tokens/cost (efficiency)
- MCP usage rate

From `comparative_narratives.md`:
- Per-task winner explanations
- Key insights (quote directly)

From `synthesis.md`:
- Paper claims with evidence
- Task difficulty rankings

## Implementation

Located in `terminalbench/analytics/`:

| Module | Responsibility |
|--------|----------------|
| `terminalbench/analytics/parser.py` | ATIF trajectory parsing |
| `terminalbench/analytics/deterministic.py` | Layer 1 metric computation |
| `terminalbench/analytics/llm_analysis.py` | Layer 2 GPT-5.2 analysis |
| `terminalbench/analytics/prompts.py` | LLM prompt templates |
| `terminalbench/analytics/comparisons.py` | Statistical tests |
| `terminalbench/analytics/reports.py` | Output generation |
| `terminalbench/analytics/cli.py` | Entry point |

Entry point: `python -m terminalbench.analytics`
