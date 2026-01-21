# Executive summary
We will replace the current “SessionStart always-init + PostToolUse(Read) best-effort impact” hooks with a **single deterministic AutoContext engine** that:
- uses Claude Code’s **official hook schema** (stdin JSON) and matcher semantics (regex / `*`),
- selects the **correct workspace root** using CodeCanvas’s existing workspace-root algorithm (not ad-hoc cwd assumptions),
- performs **lazy, correct initialization** (solves clone-first empties),
- emits **small, actively useful** additionalContext only when it’s high-signal,
- is **safe under parallel hooks** (idempotent + lock),
- produces the missing artifacts (`impact_*.png`) reliably.

This is a targeted system redesign, not a set of one-off heuristics.

---

# Discovery (source-grounded)
## Claude Code hooks contract (reference)
From `https://code.claude.com/docs/en/hooks.md`:
- Matchers are **case-sensitive** tool-name patterns; support **regex** (e.g. `Edit|Write`) and `*`/empty.
- Hook stdin JSON includes:
  - common: `session_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`
  - tool events: `tool_name`, `tool_input` (snake_case keys like `file_path`), and for PostToolUse also `tool_response` (camelCase e.g. `filePath`, `success`).
- For PostToolUse, hooks can return JSON with `hookSpecificOutput.additionalContext` to inject context to Claude.
- Hook commands receive `CLAUDE_PROJECT_DIR` (stable project root for the session).

## Current repo wiring
- TerminalBench injects hooks via Harbor’s `ClaudeCodeMCP` agent:
  - `terminalbench/harbor/agent.py` writes `--settings /tmp/claude-settings.json` containing `hooks`.
  - `terminalbench/core/profiles.py:adapt_hooks_for_harbor()` rewrites `uv run python` → `/opt/venv/bin/python`.
- Current CodeCanvas hooks config is minimal:
  - `codecanvas/hooks/hooks.json`:
    - `SessionStart` matcher `startup` runs `codecanvas.hooks.session_init`
    - `PostToolUse` matcher `Read` runs `codecanvas.hooks.post_read`

## Why it fails in practice
- `codecanvas/hooks/session_init.py` **always init** at `cwd`.
  - In clone-first tasks, `cwd=/app` initially contains no repo → init creates empty architecture.
  - Evidence: `results/2/.../build-cython-ext.../agent/sessions/codecanvas/state.json` has `project_path=/app`, `parsed_files=0`, `modules=0`.
- `codecanvas/hooks/post_read.py` assumes state is at `cwd/.codecanvas/state.json` and never resolves the correct project root.
  - This is incompatible with CodeCanvas’s own state model where `state.project_path` may be `/app/<repo>`.

---

# Design goals
## Functional
1. **Correct workspace selection**: always use the workspace root that contains the file being read/edited/searched.
2. **Lazy but guaranteed init**: never “lock in” an empty init; initialize as soon as there is a real workspace.
3. **High-signal context**: only inject additionalContext when it is actionable now.
4. **Artifact completeness**: architecture + at least one impact PNG for meaningful reads.

## Non-functional
- Deterministic, idempotent, lock-safe.
- Minimal overhead per tool call.
- No reliance on parsing shell commands to infer semantics.

---

# AutoContext Hooks v2: architecture
We introduce a single cohesive subsystem with three layers:

## 1) Event ingestion
A unified hook entrypoint that supports multiple events:
- SessionStart
- PostToolUse (for a bounded tool set)

Input parsing is schema-tolerant:
- accepts both `hook_event_name` and `hookEventName` if present
- accepts both `tool_input` and `toolInput`
- reads `tool_input.file_path` (snake) and `tool_response.filePath` (camel)

## 2) Workspace resolution (canonical)
We standardize on one resolver:
- `codecanvas.parser.utils.find_workspace_root()` is the canonical implementation because it supports multiple ecosystems (`.git`, `pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, etc.).

However, its current behavior “prefer `CANVAS_PROJECT_DIR` if start is inside it” can be harmful when hooks run in fresh processes with stale env.

**Change**: add `prefer_env: bool = True` parameter to `find_workspace_root()`.
- AutoContext uses `prefer_env=False` to compute a root from observation.
- Server continues to use `prefer_env=True` by default.

Workspace selection algorithm (deterministic):
- Candidate sources (in descending confidence):
  1) tool file path (`tool_input.file_path`, `tool_response.filePath`) for file tools
  2) tool “path” fields (`Grep.path`, `Glob.folder`, `LS.directory_path`) when present
  3) `cwd`
- Filter out non-project roots:
  - ignore paths under `/usr`, `/lib`, `/opt` etc. unless they contain project markers
- Stickiness rule:
  - if we already have an initialized workspace root `R`, we keep it unless the new candidate `R2` is both (a) marker-backed and (b) the current path is inside `R2`.

## 3) Action engine
Actions are produced by event/tool semantics:

### SessionStart (startup)
Goal: prepare without forcing empty init.
- Resolve `root0` from `cwd` and `CLAUDE_PROJECT_DIR`.
- If `root0` contains project markers (or is a previously initialized root), run `init`.
- Else: write AutoContext state “pending init” and emit a single-line additionalContext:
  - `[CodeCanvas] AutoContext armed. Init deferred until workspace is detected.`

### PostToolUse (core)
Use a single matcher (regex) targeting only tools that provide structured locations:
- `Read|Edit|Write|Grep|Glob|LS|Bash`

The hook script branches on `tool_name`:

1) **Workspace detection + init trigger** (for all the tools above)
- Resolve workspace root `R` using the canonical resolver.
- Acquire a process-level lock at `R/.codecanvas/lock` (fcntl flock; best-effort).
- Ensure CodeCanvas is initialized for `R`:
  - set `CANVAS_PROJECT_DIR=R`
  - load state
  - if not initialized OR state.project_path != R OR state.parse_summary.parsed_files == 0 while `R` has markers → run `canvas_action(init, repo_path=R)`
  - persist a small autocontext state in `$CLAUDE_CONFIG_DIR/codecanvas/autocontext_state.json` recording `active_root`, last-init reason, and timestamps.

2) **Auto-impact on Read (only)**
Trigger only when:
- `tool_name == "Read"`
- read target is a file with a supported code extension
- `tool_response` indicates success (if present)
- throttle allows it (below)

Symbol selection (deterministic, high-signal):
- Prefer symbols *defined* in the file (from `_graph.nodes` after `_ensure_loaded`), ranked by the same priorities used by `Analyzer.find_target()`:
  - kind score (FUNC > CLASS > MODULE)
  - degree (incoming+outgoing edges)
  - child_count
  - non-header extensions preference
  - has source range
- If none exist, do **not** fall back to filename stem (that’s often wrong and noisy); instead inject nothing.

Impact execution performance:
- Add a hook-friendly fast path to CodeCanvas: `canvas_action(action="impact", ..., wait_for_call_graph_s: float = 10.0)`.
  - AutoContext uses `wait_for_call_graph_s=1.0` (fast, still yields PNG) and relies on background call graph filling in over time.
  - Interactive/manual impact (agent explicitly calling tool) keeps default 10s.

additionalContext composition (small “card”, strict budget):
- If an impact evidence is created (detectable via returned `CanvasResult.images` containing `impact`):
  - emit ≤ 900 chars:
    - active root
    - symbol
    - callers/callees counts
    - “next suggestion” based on top callers/callees (IDs resolved to labels)
- Otherwise emit nothing.

3) **Error-aware guidance (rare, surgical)**
If `Read` failed because it targeted a directory (common early mistake, e.g. `/app`), emit one line:
- `[CodeCanvas] Read target is a directory; use LS/Glob to discover files. Auto-init will run on first file read.`

This is gated by tool_response error presence to avoid noise.

### Throttling / novelty detection
We treat additionalContext as a scarce resource.
- Persist throttle state under `$CLAUDE_CONFIG_DIR/codecanvas/autocontext_cache.json` (stable across processes).
- Keyed by `(active_root, file_path)`.
- Only emit an impact card when:
  - file differs from last emitted, OR
  - last emitted > 60s ago, OR
  - last emitted symbol differs.

---

# Concrete code changes (by file)
## New
- `codecanvas/hooks/autocontext.py`
  - main entrypoint for SessionStart and PostToolUse
- `codecanvas/hooks/_hookio.py`
  - tolerant JSON parsing + key normalization
- `codecanvas/hooks/_autocontext_state.py`
  - read/write cache in `$CLAUDE_CONFIG_DIR/codecanvas/`
- `codecanvas/hooks/_workspace.py`
  - canonical root selection, filtering, stickiness

## Modified
- `codecanvas/hooks/session_init.py`
  - becomes thin wrapper calling AutoContext SessionStart handler (keeps path stable)
- `codecanvas/hooks/post_read.py`
  - becomes thin wrapper calling AutoContext PostToolUse handler (keeps path stable)
- `codecanvas/hooks/hooks.json`
  - PostToolUse matcher becomes `Read|Edit|Write|Grep|Glob|LS|Bash`
  - timeouts: SessionStart 60s, PostToolUse 30s
- `codecanvas/parser/utils.py`
  - add `prefer_env: bool = True` option to `find_workspace_root()`
- `codecanvas/server.py`
  - use the canonical workspace resolver (so init and hooks agree)
  - add optional `wait_for_call_graph_s` for impact

(Optional but recommended for robustness)
- `codecanvas/core/state.py`
  - process-level lock around `save_state/clear_state` OR provide a shared lock helper used by server and hooks.

---

# Tests
Add `codecanvas/tests/autocontext_hooks.py` with unit-level tests that do not require Harbor:
1. Hook input parsing
- Read PostToolUse payload with `tool_input.file_path`
- Write PostToolUse payload with `tool_response.filePath`

2. Workspace resolution
- ensure `prefer_env=False` ignores stale `CANVAS_PROJECT_DIR`

3. Init policy
- empty workspace at SessionStart → deferred
- later PostToolUse(Glob/LS/Read) inside real repo → init runs

4. Symbol selection
- ensure deterministic “best symbol in file” selection based on edges/degree

5. Throttle
- repeated Read of same file within window → no additionalContext

---

# Validation gate
After implementation:
- `python3 -m pytest`
- `python3 -m ruff check .`

---

# One-task verification run (requested)
Use `build-cython-ext` (clone-first regression case) with `anthropic/claude-haiku-4-5` and `reasoning=low`:
```bash
python3 -m terminalbench.ui.cli \
  --manifest tasks.yaml \
  --tasks build-cython-ext \
  --model anthropic/claude-haiku-4-5 \
  --reasoning low \
  --profiles-parallel 1 \
  -C --mcp-server codecanvas \
     --mcp-git-source https://github.com/ain3sh/codecanvas \
     --hooks codecanvas/hooks/hooks.json \
     --key codecanvas
```

Success criteria:
- `agent/sessions/codecanvas/state.json`: `parse_summary.parsed_files > 0`
- `agent/sessions/codecanvas/` contains `impact_*.png`
- mirror exists under `results/<batch>/canvas/build-cython-ext__*/impact_*.png`

---

# Why this is not “scrappy heuristics”
- We rely on the **official hook schema**, the **structured tool inputs**, and the **existing workspace-root algorithm**.
- The system is a small state machine (pending → initialized → stable), not brittle string parsing.
- Context injection is budgeted and novelty-driven, so it stays actively useful.
