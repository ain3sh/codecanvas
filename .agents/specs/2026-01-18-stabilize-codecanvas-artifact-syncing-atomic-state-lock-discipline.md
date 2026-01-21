## Answer
- The **atomic+dedupe state write** + **strict hook locking** are the only *required* changes I’d make to stop the instability we saw.
- If you want “cleaner”/more future-proof syncing, I’d add a **tiny load retry** (and optionally a **cross-process file lock**) as cheap defense-in-depth.
- **Merkle trees aren’t useful for this specific problem** (we’re syncing a handful of small artifacts + we already know the changed paths from tool events); they’re only worth it if we later need fast whole-tree equivalence checks / content-addressed caching across many files.

## Root cause recap (why it flaked)
1. In TerminalBench we set `CANVAS_ARTIFACT_DIR=$CLAUDE_CONFIG_DIR/codecanvas`, so the “primary” state path and the “Harbor extraction” path are **the same file**.
2. `save_state()` writes the primary file atomically, but `_save_for_harbor_extraction()` rewrites that same file **non-atomically** (`write_text()` truncates first).
3. Hooks run **in parallel**; a concurrent `load_state()` can read an empty/partial file and rename it to `state.json.bak`, leaving no `state.json`.
4. Hook `_workspace_lock()` currently **yields even when it didn’t acquire the lock**, allowing concurrent init/impact to overlap and amplify the race.

## Option 1 — Minimal fix (recommended)
### 1) Make Harbor extraction write safe and non-duplicative
**File:** `codecanvas/core/state.py`
- Make `_save_for_harbor_extraction()` write **atomically** (tmp + replace).
- In `save_state()`, **skip** `_save_for_harbor_extraction()` when the extraction target resolves to the same path as `_get_state_path()`.

### 2) Enforce “no lock => no init/impact” in hooks
**File:** `codecanvas/hooks/autocontext.py`
- Change `_workspace_lock(root)` to `yield locked: bool`.
- In `handle_pre_tool_use()` and `handle_post_tool_use()`:
  - `with _workspace_lock(root) as locked:`
  - if `not locked`: `_debug_log(... skipped='lock_busy')` and return `None`.

## Option 2 — Minimal + extra robustness
Includes Option 1, plus:
- **`load_state()` retry:** on JSON decode error, sleep 10–20ms and retry 1–2 times before giving up/renaming to `.bak`.
- (Optional) Add a **cross-process lock** in `core/state.py` around read/write (best-effort `fcntl.flock`), so even non-hook processes can’t race on `state.json`.

## Option 3 — Bigger cleanup (if you want the “cleanest” model)
- Treat `CANVAS_ARTIFACT_DIR` as the **single source of truth** for all artifacts in agent runs.
- Remove/disable the “Harbor extraction” duplicate write when `CANVAS_ARTIFACT_DIR` is set.
- Add a small `manifest.json` (list of artifact filenames + timestamps) so sync/copy logic is explicit and can be made atomic as a unit.

## Merkle trees: when they *would* help (and when they won’t)
- **Not helpful here:** preventing truncated `state.json` / hook concurrency races.
- **Potentially helpful later:**
  - verifying “graph corresponds to this exact workspace snapshot” without trusting tool-event dirty tracking
  - content-addressed caching across many files / remote sync
- Even then, a **flat per-file hash map** (computed during parse) usually gets you 90% of the value without maintaining a full Merkle tree.

## Verification (for any option)
- Run `ruff`, `ty`, `pytest` (current repo validators).
- Rerun TerminalBench `modernize-scientific-stack` and confirm:
  - `agent/sessions/codecanvas/state.json` exists (no `.bak`),
  - `architecture.png` always present,
  - PostToolUse after reading a `.py` yields an impact PNG + stable state.