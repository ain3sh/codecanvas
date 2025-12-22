#!/usr/bin/env bash
# Kill all experiment processes and containers cleanly
# Usage: ./terminalbench/scripts/kill-experiment.sh
#
# Order matters:
#   1. Docker containers first (they hold the actual agents)
#   2. Local wrapper processes (terminalbench, harbor CLI)
#   3. Prune stopped containers
#   4. Verify clean state

set -eu  # No pipefail - grep returns 1 on no match, we handle that

echo "=== Killing experiment ==="

# 1. Kill running docker containers first
CONTAINERS=$(docker ps -q 2>/dev/null) || true
if [[ -n "${CONTAINERS:-}" ]]; then
    COUNT=$(echo "$CONTAINERS" | wc -w)
    echo "Killing $COUNT running containers..."
    echo "$CONTAINERS" | xargs docker kill 2>/dev/null || true
fi

# 2. Kill local processes
echo "Killing local processes..."
PIDS=$(ps aux | grep -E "(terminalbench|harbor|run-experiment)" | grep -v grep | awk '{print $2}') || true
if [[ -n "${PIDS:-}" ]]; then
    echo "$PIDS" | xargs kill -9 2>/dev/null || true
fi

# 3. Remove stopped containers
sleep 1
EXITED=$(docker ps -aq 2>/dev/null) || true
if [[ -n "${EXITED:-}" ]]; then
    COUNT=$(echo "$EXITED" | wc -w)
    echo "Removing $COUNT stopped containers..."
    echo "$EXITED" | xargs docker rm 2>/dev/null || true
fi

# 4. Verify
sleep 1
echo ""
echo "=== Verification ==="
REMAINING_CONTAINERS=$(docker ps -q 2>/dev/null | wc -l) || true
REMAINING_PROCS=$(ps aux | grep -E "(terminalbench|harbor|run-experiment)" | grep -v grep | wc -l) || true

if [[ "${REMAINING_CONTAINERS:-0}" -eq 0 && "${REMAINING_PROCS:-0}" -eq 0 ]]; then
    echo "CLEAN: No containers or processes remaining"
    exit 0
else
    echo "WARNING: ${REMAINING_CONTAINERS:-0} containers, ${REMAINING_PROCS:-0} processes still running"
    docker ps 2>/dev/null || true
    ps aux | grep -E "(terminalbench|harbor)" | grep -v grep || true
    exit 1
fi
