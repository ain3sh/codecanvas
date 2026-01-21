## Goals
- Stop the catastrophic “30s per tool” PreToolUse stall loop permanently.
- Warm up multilspy/LSP on `SessionStart` without blocking the agent.
- Attempt first real init with `use_lsp=True` (≤60s), then retry on a **2 minute** cooldown, and after **5 attempts** (or warmup hard-fails) fall back to `use_lsp=False`.
- Keep “intelligence” in Python hook scripts; `hooks.json` stays declarative (matchers + timeouts only).

## Current Root Cause (why TB times out)
- `PreToolUse` matches `"*"` and calls `canvas_action(init)` inside the hook.
- That init path is exceeding the hook timeout (30s), so the hook process gets killed; next tool repeats → 30s × many tools → agent hits 900s timeout.

## Proposed Design (state machine)
### 1) LSP Warmup (SessionStart)
- On `SessionStart`, start a detached background worker that tries to initialize LSP sessions for the most relevant multilspy languages (at minimum: `py`, `ts`).
- The SessionStart hook itself returns immediately (≤1s) after spawning.
- The worker writes `lsp_warmup.json` under `$CLAUDE_CONFIG_DIR/codecanvas/` with fields:
  - `status`: `"running" | "ready" | "failed"`
  - `pid`: worker pid
  - `attempt`: integer
  - `started_at`, `updated_at`
  - `ready_langs`: list
  - `last_error`: string
- Worker behavior:
  - Up to 5 attempts.
  - Each attempt tries `get_lsp_session_manager().get(lang, workspace_root)` and a cheap `document_symbols()` call against a tiny dummy file in a dedicated warmup workspace directory.
  - If success (at least `py` is ready), mark `status="ready"` and exit.
  - Otherwise record error, sleep 120s, retry.
  - After 5 attempts mark `status="failed"` and exit.

### 2) Init Attempt Policy (PreToolUse `*`)
- PreToolUse remains `"*"`, but it becomes *cheap and bounded*:
  - Resolve root and update `active_root`.
  - Only consider init when `allow_init` is true (markers or a real file path).
  - Enforce a per-root cooldown and “inflight” guard to prevent repeated hook stalls.

State persisted via `AutoContextState` (`autocontext_cache.json`):
- `init_inflight::<root>` (already added): set immediately before starting init; if the hook is killed, it remains and blocks reattempts.
- `init_next_allowed_at::<root>`: next time an init attempt is allowed (now + 120s after any failed/timeout-prone attempt).
- `lsp_init_attempts::<root>`: number of `use_lsp=True` init attempts made.

Init decision:
1. If `init_announced::<root>` is already true → return `None`.
2. If `init_inflight::<root>` exists and is younger than 120s → return `None` (prevents per-tool stalls even after hard kills).
3. If `now < init_next_allowed_at::<root>` → return `None`.
4. Determine `want_lsp`:
   - If warmup `status=="failed"` → `want_lsp=False`.
   - Else if `lsp_init_attempts::<root> < 5` → `want_lsp=True`.
   - Else → `want_lsp=False`.
5. Attempt init:
   - When `want_lsp=True`, run init with `use_lsp=True` (this is the “first real init attempt” requirement).
   - If the process times out and gets killed, the inflight marker remains, and we don’t try again until ≥120s.
   - When attempts exceed 5 (or warmup fails), run init with `use_lsp=False`.
6. On successful init (state initialized + parsed_files>0), emit `[CodeCanvas AUTO-INIT] ...` exactly once and set `init_announced::<root>=true`.

### 3) PostToolUse (Edit|Write)
- PostToolUse should **not** run init (to avoid paying init cost after every mutation).
- It only runs impact if the state is already initialized; otherwise it logs `skipped=not_initialized` and returns `None`.

## Hook Config Changes (`codecanvas/hooks/hooks.json`)
- `SessionStart`: keep timeout 60, still runs the main hook entry; script will spawn warmup worker.
- `PreToolUse`: keep matcher `"*"` but set timeout to **60s** to allow the first `use_lsp=True` init attempt to complete when it can.
- `PostToolUse`: keep matcher `"Edit|Write"` at 30s (impact only).

## Code Changes (files)
- `codecanvas/hooks/lsp_warmup.py` (new)
  - `ensure_worker_running()` + `main()` for SessionStart.
  - `worker_main()` that performs up to 5 warmup attempts with 120s sleeps.
  - Writes `lsp_warmup.json` and appends to existing `hook_debug.jsonl`.
- `codecanvas/hooks/autocontext.py`
  - `handle_session_start`: call `ensure_worker_running()`.
  - `handle_pre_tool_use`: implement cooldown + inflight guard + bounded lsp attempts + `use_lsp` selection.
  - `handle_post_tool_use`: remove `_maybe_init()` call; impact-only.
  - Keep existing `.codecanvas` → `$CLAUDE_CONFIG_DIR/codecanvas/` artifact mirroring.
- `codecanvas/hooks/_autocontext_state.py`
  - Extend beyond the already-added `init_inflight` APIs with:
    - `get/set_init_next_allowed_at(root)`
    - `get/inc_lsp_init_attempts(root)`
- `codecanvas/tests/autocontext_hooks.py`
  - Update the test that previously relied on PostToolUse(Grep) doing init; it should now call `handle_pre_tool_use` and/or set warmup status to `failed` so tests deterministically use `use_lsp=False` (no multilspy/network).

## Why this is durable
- Even if `use_lsp=True` init is slow, broken, or killed by the hook timeout, we *never* re-enter the “stall every tool call” loop:
  - `init_inflight` persists across killed processes.
  - `init_next_allowed_at` enforces the 2 minute cooldown.
  - `lsp_init_attempts` caps the expensive path at 5 tries and then forces `use_lsp=False`.
- LSP warmup happens off the critical path and can take as long as it needs without burning agent tool time.

## Validation Plan
- Run `ruff` and `pytest`.
- Re-run TerminalBench with `TERMINALBENCH_FORCE_REBUILD=1`.
- Confirm evidence:
  - `$CLAUDE_CONFIG_DIR/codecanvas/hook_debug.jsonl` shows `phase=init` entries and `skipped=init_inflight` instead of repeated 30s gaps.
  - `$CLAUDE_CONFIG_DIR/codecanvas/lsp_warmup.json` transitions to `ready` or `failed`.
  - `$CLAUDE_CONFIG_DIR/codecanvas/state.json` and PNG artifacts appear once init succeeds.

## One small judgement call (override)
- I’m proposing PostToolUse to be impact-only (no init), because doing init after every edit is the easiest way to reintroduce tool-call stalls. This keeps side-effect summaries fast and predictable, and aligns with your “post-mutation summaries” intent.