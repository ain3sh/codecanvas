## Goal
Prevent `lsp_warmup.json` from staying `running` for long periods and ensure warmup never blocks or suppresses init.

## Changes
1. Warmup worker becomes **single-shot**:
   - One attempt only (no retry loop / no long sleeps).
   - Writes `status=ready` or `status=failed` and exits.
2. Warmup uses a **small workspace root**:
   - The LSP sessions are started with `workspace_root=<repo>/.codecanvas` (where the warmup files live), reducing indexing cost vs using the full repo root.
3. AutoContext init becomes **non-blocked by warmup**:
   - If warmup isn’t `ready`, init proceeds with `use_lsp=False` (tree-sitter), instead of being skipped as `warmup_not_ready`.
   - LSP init is only attempted when warmup is `ready`.
4. Worker respawn is throttled:
   - `ensure_worker_running()` won’t immediately respawn if warmup just `failed`/`skipped` for the same root.

## Expected result
- `lsp_warmup.json` should quickly reach `ready` or `failed` (no long-lived `running`).
- PreToolUse init should not get stuck in warmup-related cooldown loops.
