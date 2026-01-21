## Findings (why impacts/state went missing)
- The hooks **did run**: `agent/sessions/debug/*.txt` shows `executePreToolHooks`/`executePostToolHooks` and a parsed hook output containing `[CodeCanvas AUTO-INIT] root=/app ...`.
- The run ended with `agent/sessions/codecanvas/state.json.bak` (0 bytes) and **no** `state.json`, so later `load_state()` treated `state.json` as corrupted and renamed it.
- Current `save_state()` writes `state.json` twice:
  1) atomic `state.json.tmp -> state.json`
  2) `_save_for_harbor_extraction()` does a **non-atomic** `write_text()` to `CLAUDE_CONFIG_DIR/codecanvas/state.json`.
  In TerminalBench we set `CANVAS_ARTIFACT_DIR` to that same directory, so (2) rewrites the **same file**, briefly truncating it; with concurrent hook invocations this can race with `load_state()` and get renamed to `.bak`.
- `_workspace_lock()` in hooks will **proceed even if it fails to acquire the lock**, allowing concurrent init/impact processes.

## Proposed Fix
1. **Make `_save_for_harbor_extraction()` atomic** (tmp+replace) and **skip it entirely when its destination is the same path as the primary state path**.
2. Change hooks’ `_workspace_lock()` to `yield locked` and in callers **skip init/impact when the lock wasn’t acquired** (instead of running concurrently).
3. (Optional, cheap) Add a small `load_state()` retry on JSON decode error (e.g. 2 retries with 10–20ms sleep) to tolerate transient reads.

## Verification
- Run project validators (`ruff`, `ty`, `pytest`) as currently done in this repo.
- Rerun TerminalBench `modernize-scientific-stack` and confirm `agent/sessions/codecanvas/state.json` exists (no `.bak`), and PostToolUse produces an impact PNG after reading a `.py` file.