## Goal
Make `lsp_warmup.json` reflect reality consistently by preventing late/incorrect warmup worker spawns.

## Problem
Warmup workers can be spawned:
- on `SessionStart` using `cwd` (which is often not a marker-backed repo root in TerminalBench), and
- repeatedly on `PreToolUse` even after init is already announced.

This can create a late (re)spawn where the last writer leaves `lsp_warmup.json` as `running` long after init has finished, confusing post-run inspection.

## Approach
1. **SessionStart gating**: only spawn warmup if `cwd` is already a marker-backed repo root (contains one of `.git`, `pyproject.toml`, etc.). Otherwise, write `status=skipped` with `reason=not_repo_root`.
2. **PreToolUse gating**: only call `ensure_worker_running()` before init is announced, and only for marker-backed roots.

## Expected outcome
- Warmup starts early (when we actually have a stable workspace root), not late.
- `lsp_warmup.json` should transition to `ready` early when possible, or remain stable without late `running` updates.
