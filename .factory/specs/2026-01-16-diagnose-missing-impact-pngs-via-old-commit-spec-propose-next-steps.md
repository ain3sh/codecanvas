## What I found in commit `6486881292cbe71bbb2588ccd2f5f195cab8828e`
### Old hook behavior that *did* reliably generate impact PNGs
In that commit:
- `hooks.json` only had:
  - `SessionStart` → `session_init.py`
  - `PostToolUse` matcher **`Read`** → `post_read.py`
- `post_read.py` did **auto-impact on Read**:
  1) calls `canvas_action(action="status")` to force `_ensure_loaded()` (because `read` action returns early)
  2) selects symbols by scanning the in-memory graph (`_graph.nodes`) for nodes whose `fsPath == file_path`
  3) falls back to `path.stem` if no symbols found
  4) runs `canvas_action(action="impact", symbol=...)` and injects the result text as additional context

Key clue: it **did not rely on `state.symbol_files`** for symbol selection; it used the live graph.

## What the Jan 12 spec says vs what we run today
From `.factory/specs/2026-01-12-codecanvas-autocontext-hooks-v2-deterministic-stateful-low-noise.md`:
- PostToolUse matcher should be broad: `Read|Edit|Write|Grep|Glob|LS|Bash`
- **Auto-impact should run on `Read` only** (explicitly), and be throttled
- Workspace root should be resolved canonically (via `find_workspace_root(prefer_env=False)`), not hard-coded `/app`

Current implementation diverges in important ways:
- We hard-code root to `/app` for TB (`resolve_workspace_root` disabled)
- Our `hooks.json` triggers **PreToolUse `*`** and PostToolUse **`Edit|Write`** (no Read)
- PostToolUse impact selection uses **`state.symbol_files` only**, so for newly created files it often becomes `no_symbol` → **no impact PNG**
- `handle_pre_tool_use`’s init banner reads `cs.get("call_edges_total")` (wrong key; state uses `edges_total`) so it can misleadingly report 0

## What state.json is telling us in the last run
In `results/.../agent/sessions/codecanvas/state.json`:
- `call_graph_summary.status = working`, `phase = init`, and the `result` section lacks completion counters → snapshot was persisted before completion.
- Meanwhile `call_edges.json` exists with 3 edges → edges were produced, but the **state snapshot is not reflecting completion** (likely because hooks call `canvas_action` in short-lived processes, so background thread completion is fragile / races).

---

## Proposed next step (high-alpha) — options
### Option A (minimal, fastest signal)
Bring back the known-good “impact-on-Read” path:
1) Change hooks wiring so PostToolUse includes `Read` again (either `Read` only, or `Read|Edit|Write`).
2) In autocontext, allow `want_impact` for `Read` and select symbols by scanning the live `_graph.nodes` after forcing `_ensure_loaded()` via `canvas_action(action="status")` (like commit 6486881).
3) Fix the `call_edges_total` vs `edges_total` key in the init banner.

**Goal:** get `impact_*.png` reliably back in artifacts before we tackle deeper root/LSP issues.

### Option B (align with Jan 12 spec; bigger but cleaner)
Implement the spec as written:
1) Enable canonical workspace root resolution (use file path/cwd and `find_workspace_root(prefer_env=False)`; remove `/app` hardcode fallback-only).
2) PostToolUse matcher: `Read|Edit|Write|Grep|Glob|LS|Bash`, but **generate impact only on Read**.
3) Symbol selection: prefer `_graph.nodes` matches for that file; fallback to `state.symbol_files`; throttle.
4) Fix init banner key (`edges_total`) and include `status`.

**Goal:** deterministic, low-noise impact generation that matches the design doc.

### Option C (fix “status=working forever” in hook-produced state)
Make hook-mode call graph deterministic:
1) Add a hook-mode flag (e.g. `CODECANVAS_HOOK_MODE=1`) so `init` runs **foreground call-graph only** (slightly higher budget) and **skips the background thread**.
2) Persist a final call-graph summary immediately (status `completed` + counters) so `state.json` is always coherent.

**Goal:** `state.json` becomes a trustworthy diagnostic source even under short-lived hook processes.

---

## Recommended sequence
1) **Option A** first (fastest confirmation that we can reliably produce `impact_*.png` again).
2) Then **Option B** (root correctness + spec alignment).
3) Finally **Option C** if we still see “working” snapshots and want deterministic state.
