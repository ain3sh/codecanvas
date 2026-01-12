#!/usr/bin/env bash
set -euo pipefail

# TerminalBench Experiment Runner
# Runs all 7 tasks with 3 profiles (text, codegraph, codecanvas) in parallel

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Batch directory management - auto-increment to next available batch ID
RESULTS_BASE="${PROJECT_ROOT}/results"
mkdir -p "$RESULTS_BASE"
BATCH_ID=$(find "$RESULTS_BASE" -maxdepth 1 -type d -regex '.*/[0-9]+' 2>/dev/null | wc -l)
BATCH_DIR="${RESULTS_BASE}/${BATCH_ID}"
mkdir -p "$BATCH_DIR"/{runs,analytics,canvas}

RESULTS_DIR="${BATCH_DIR}/runs"
LOGFILE="${BATCH_DIR}/experiment_$(date +%Y%m%d_%H%M%S).log"

# Redirect all output to log file
exec > >(tee -a "$LOGFILE") 2>&1

# Configuration
MODEL="${MODEL:-anthropic/claude-sonnet-4-5}"
REASONING="${REASONING:-low}"
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
echo "Batch: $BATCH_ID"
echo "Model: $MODEL"
echo "Reasoning: $REASONING"
echo "MCP Source: $MCP_GIT_SOURCE"
echo "Profiles: text, codegraph, codecanvas (parallel: $PROFILES_PARALLEL)"
echo "Tasks: ${#TASKS[@]}"
echo "=============================================="

# Clean up stale Docker networks to prevent address pool exhaustion
echo ""
echo "Pruning unused Docker networks..."
docker network prune -f
echo "Done."

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
        --batch "$BATCH_ID" \
        --model "$MODEL" \
        --reasoning "$REASONING" \
        --profiles-parallel "$PROFILES_PARALLEL" \
        -C --no-mcp --key text \
        -C --mcp-server codegraph --mcp-git-source "$MCP_GIT_SOURCE" --key codegraph \
        -C --mcp-server codecanvas --mcp-git-source "$MCP_GIT_SOURCE" --hooks codecanvas/hooks/hooks.json --key codecanvas
    
    echo ""
    echo "Task $TASK completed."
done

echo ""
echo "=============================================="
echo "All tasks completed!"
echo "Batch $BATCH_ID results in: $BATCH_DIR"
echo ""
echo "Run analytics with:"
echo "  python3 -m terminalbench.analytics $RESULTS_DIR --output $BATCH_DIR/analytics/"
echo "=============================================="
