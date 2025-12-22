#!/usr/bin/env bash
set -euo pipefail

# TerminalBench Experiment Runner
# Runs all 7 tasks with 3 profiles (text, codegraph, codecanvas) in parallel

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
RESULTS_DIR="${PROJECT_ROOT}/results/runs"
LOGFILE="${PROJECT_ROOT}/results/experiment_$(date +%Y%m%d_%H%M%S).log"

# Redirect all output to log file
exec > >(tee -a "$LOGFILE") 2>&1

# Configuration
MODEL="${MODEL:-anthropic/claude-sonnet-4-5}"
REASONING="${REASONING:-medium}"
MCP_GIT_SOURCE="${MCP_GIT_SOURCE:-https://github.com/ain3sh/codecanvas}"
PROFILES_PARALLEL="${PROFILES_PARALLEL:-3}"

# All tasks from tasks.yaml
TASKS=(
    "sanitize-git-repo"
    "build-cython-ext"
    "custom-memory-heap-crash"
    "db-wal-recovery"
    "modernize-scientific-stack"
    "rstan-to-pystan"
    "fix-code-vulnerability"
)

echo "=============================================="
echo "TerminalBench Experiment Runner"
echo "=============================================="
echo "Model: $MODEL"
echo "Reasoning: $REASONING"
echo "MCP Source: $MCP_GIT_SOURCE"
echo "Profiles: text, codegraph, codecanvas (parallel: $PROFILES_PARALLEL)"
echo "Tasks: ${#TASKS[@]}"
echo "=============================================="

# Clear previous results
if [[ -d "$RESULTS_DIR" ]]; then
    echo ""
    echo "Clearing previous results in $RESULTS_DIR..."
    rm -rf "$RESULTS_DIR"
    echo "Done."
fi
mkdir -p "$RESULTS_DIR"

cd "$PROJECT_ROOT"

# Run each task
for i in "${!TASKS[@]}"; do
    TASK="${TASKS[$i]}"
    TASK_NUM=$((i + 1))
    
    echo ""
    echo "=============================================="
    echo "Task $TASK_NUM/${#TASKS[@]}: $TASK"
    echo "=============================================="
    
    python3 -m terminalbench.ui.cli \
        --manifest tasks.yaml \
        --tasks "$TASK" \
        --model "$MODEL" \
        --reasoning "$REASONING" \
        --profiles-parallel "$PROFILES_PARALLEL" \
        -C --no-mcp --key text \
        -C --mcp-server codegraph --mcp-git-source "$MCP_GIT_SOURCE" --key codegraph \
        -C --mcp-server codecanvas --mcp-git-source "$MCP_GIT_SOURCE" --key codecanvas
    
    echo ""
    echo "Task $TASK completed."
done

echo ""
echo "=============================================="
echo "All tasks completed!"
echo "Results in: $RESULTS_DIR"
echo ""
echo "Run analytics with:"
echo "  python3 -m terminalbench.analytics $RESULTS_DIR --output results/analytics/"
echo "=============================================="
