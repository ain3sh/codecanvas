#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/mnt/d/Personal_Folders/Tocho/ain3sh/codecanvas"
RESULTS_DIR="${PROJECT_ROOT}/results/runs"
LOGFILE="${PROJECT_ROOT}/results/experiment_codecanvas_rerun.log"

exec > >(tee -a "$LOGFILE") 2>&1

echo "=============================================="
echo "CodeCanvas Re-run (Tasks 2-7)"
echo "Started: $(date)"
echo "=============================================="

declare -A TASK_TIMESTAMPS=(
    ["build-cython-ext"]="2025-12-22__04-25-12"
    ["custom-memory-heap-crash"]="2025-12-22__04-39-22"
    ["db-wal-recovery"]="2025-12-22__05-01-52"
    ["modernize-scientific-stack"]="2025-12-22__05-13-20"
    ["rstan-to-pystan"]="2025-12-22__05-17-35"
    ["fix-code-vulnerability"]="2025-12-22__05-53-25"
)

TASKS=(
    "build-cython-ext"
    "custom-memory-heap-crash"
    "db-wal-recovery"
    "modernize-scientific-stack"
    "rstan-to-pystan"
    "fix-code-vulnerability"
)

cd "$PROJECT_ROOT"

for i in "${!TASKS[@]}"; do
    TASK="${TASKS[$i]}"
    TARGET_TS="${TASK_TIMESTAMPS[$TASK]}"
    TASK_NUM=$((i + 1))
    
    echo ""
    echo "=============================================="
    echo "Task $TASK_NUM/6: $TASK"
    echo "Target timestamp: $TARGET_TS"
    echo "=============================================="
    
    # Run the task
    python3 -m terminalbench.ui.cli \
        --manifest tasks.yaml \
        --tasks "$TASK" \
        --model anthropic/claude-sonnet-4-5 \
        --reasoning medium \
        -C --mcp-server codecanvas --mcp-git-source https://github.com/ain3sh/codecanvas --key codecanvas
    
    # Find the newly created codecanvas dir (one that doesn't match any expected timestamp)
    NEW_DIR=""
    for d in "${RESULTS_DIR}"/*__codecanvas; do
        DIRNAME=$(basename "$d")
        # Check if this dir's timestamp matches any of our target timestamps or task 1's timestamp
        IS_KNOWN=false
        if [[ "$DIRNAME" == "2025-12-22__04-18-30__codecanvas" ]]; then
            IS_KNOWN=true  # Task 1, already done
        fi
        for ts in "${TASK_TIMESTAMPS[@]}"; do
            if [[ "$DIRNAME" == "${ts}__codecanvas" ]]; then
                IS_KNOWN=true
                break
            fi
        done
        if [[ "$IS_KNOWN" == "false" ]]; then
            NEW_DIR="$d"
            break
        fi
    done
    
    if [[ -z "$NEW_DIR" ]]; then
        echo "ERROR: No new codecanvas directory found after running $TASK"
        echo "Existing dirs:"
        ls -1 "${RESULTS_DIR}"/*__codecanvas
        exit 1
    fi
    
    NEW_DIRNAME=$(basename "$NEW_DIR")
    TARGET_DIRNAME="${TARGET_TS}__codecanvas"
    
    if [[ "$NEW_DIRNAME" != "$TARGET_DIRNAME" ]]; then
        echo "Renaming: $NEW_DIRNAME -> $TARGET_DIRNAME"
        mv "$NEW_DIR" "${RESULTS_DIR}/${TARGET_DIRNAME}"
    else
        echo "Directory already has correct name: $TARGET_DIRNAME"
    fi
    
    echo "Task $TASK completed and renamed."
done

echo ""
echo "=============================================="
echo "All 6 tasks completed!"
echo "Finished: $(date)"
echo "=============================================="

# Rebuild index.json with all runs
echo ""
echo "Rebuilding index.json..."
python3 << 'PYTHON'
import json
from pathlib import Path

runs_dir = Path("/mnt/d/Personal_Folders/Tocho/ain3sh/codecanvas/results/runs")
index = {"runs": []}

for run_dir in sorted(runs_dir.iterdir()):
    if not run_dir.is_dir() or run_dir.name == "index.json":
        continue
    
    result_json = run_dir / "result.json"
    if not result_json.exists():
        continue
    
    with open(result_json) as f:
        result = json.load(f)
    
    # Find task dir and trajectory
    task_dirs = [d for d in run_dir.iterdir() if d.is_dir() and not d.name.startswith('.')]
    if not task_dirs:
        continue
    
    task_dir = task_dirs[0]
    task_id = task_dir.name.split('__')[0]
    trajectory = task_dir / "agent" / "trajectory.json"
    
    # Extract profile from dir name
    profile = run_dir.name.split('__')[-1]
    
    entry = {
        "task_id": task_id,
        "agent_key": profile,
        "exit_code": 0,
        "success": result.get("accuracy", 0) == 1.0,
        "job_dir": str(run_dir),
        "results_json": str(result_json),
        "trajectory_json": str(trajectory) if trajectory.exists() else None,
        "accuracy": result.get("accuracy", 0),
        "resolved": result.get("accuracy", 0) == 1.0
    }
    index["runs"].append(entry)

with open(runs_dir / "index.json", "w") as f:
    json.dump(index, f, indent=2)

print(f"Rebuilt index.json with {len(index['runs'])} entries")
PYTHON

echo "Done!"
