## Goal
Make CodeCanvas’s **architecture + call graph + impact PNGs** a *live reflection* of the repo as the agent edits files, while keeping overhead low and avoiding “silently stale” graphs.

## Key constraints / reality
- Today, we build a graph at `init` and run a **one-shot** call-graph build on that snapshot. After edits, the graph can be wrong.
- Hooks often run in **short-lived processes**; any “background thread” work risks dying early unless persisted or run in a long-lived process.
- Our call edges come from: **tree-sitter callsite extraction** + **LSP definition resolution**. (Even when defs come from LSP, callsites still come from tree-sitter.)

---

## Option A: Incremental refresh (dirty-set + coalesced rebuild) ✅ Recommended
### High-level idea
Treat edits as events that mark files **dirty**, then run a **coalesced incremental refresh**:
1) Incrementally re-parse changed files (defs/imports) into the existing graph.
2) Incrementally rebuild call edges for changed files.
3) Opportunistically (budgeted) run a broader rebuild to repair edges impacted by symbol renames/removals.

### Components
#### 1) Change detection (very cheap)
- On `PostToolUse(Edit|Write)` (and optionally `Bash` if we can infer file writes), record:
  - `touched_files += {abs_path}`
  - file signature (mtime_ns, size)
  - timestamp
- Persist this to state (or a dedicated `dirty.json`) so it survives process boundaries.

#### 2) Refresh scheduler (coalescing + budgets)
A small scheduler that runs refresh when:
- A dirty file exists and:
  - we’re about to render an impact PNG for that file, **or**
  - a debounce window expires (e.g. 1–2s since last change), **or**
  - a periodic tick (e.g. every 15–30s) happens in a long-lived process.

Budgets:
- `refresh_defs_budget_s` (e.g. 50–150ms per trigger)
- `refresh_calls_budget_s` (e.g. 150–500ms per trigger)
- Hard caps: max dirty files processed per tick.

#### 3) Incremental parse update (defs + imports)
Add graph mutation primitives:
- `Graph.remove_nodes_by_fs_path(fs_path)`
  - removes nodes with `node.fsPath == fs_path`
  - removes all edges referencing removed node ids
- `Graph.remove_edges(predicate)` for targeted call-edge invalidation.

Refresh step for each dirty file:
- Parse file (LSP-first; tree-sitter fallback) and regenerate:
  - module node
  - CONTAINS edges
  - import edges (already tree-sitter derived)
- Replace old nodes/edges for that file atomically under the graph lock.

#### 4) Incremental call-edge update
Call edges are determined by **caller file callsites**, so on `dirty_file` we can always do:
- Remove **outgoing call edges** from functions in `dirty_file`.
- Recompute call edges for callsites in `dirty_file` (tree-sitter → LSP definitions → edges).

Handling renames/removals (the hard part):
- When a file changes, also remove call edges where `to_id` belonged to the previous version of that file (incoming edges become potentially dangling if IDs changed).
- To recover those incoming edges, schedule a **budgeted broader rebuild**:
  - either over “recently interacting” files (read/edited set) first,
  - or over the whole repo with a rolling time budget.

#### 5) “Freshness gates” for impact rendering
Before `impact(symbol=...)` renders PNG:
- If the symbol’s file is dirty (or graph generation < dirty generation), run a **synchronous mini-refresh** within a small budget.
- If background call-graph rebuild is running, render with best-known edges but embed diagnostics:
  - `call_graph_status`, `last_refresh_at`, `dirty_count`, `edges_total`, `edges_stale_estimate`.

#### 6) Persistence & cross-process safety
- Keep the existing `.codecanvas/lock` flock for cross-process mutual exclusion.
- Persist:
  - `dirty_files` + signatures
  - `refresh_generation` (monotonic)
  - call edges cache (`call_edges.json`) after each successful call-edge refresh chunk

#### 7) Observability (so we can *prove* freshness)
Add to `state.json`:
- `refresh_summary`:
  - `dirty_files_count`
  - `last_refresh_at`
  - `last_refresh_reason` (edit/write/impact)
  - `defs_updated_files`, `call_edges_updated_files`
  - `invalidated_edges_count`
- For LSP issues:
  - count of `empty_symbols` fallbacks
  - optional sample list (bounded)

### Optional but high-impact refinement: stable function IDs
Right now function IDs include the **line number**, which makes edges and caches fragile across edits.

A cleaner long-term design is to switch function IDs to:
- `fn_{hash(file_label)}_{qualname}` (qualname includes class prefix)
- keep `start_line`/`end_line` as attributes (for callsite→caller mapping)

This drastically reduces “incoming edge invalidation” and makes incremental updates far more accurate.
We can roll this out behind a `state_version` bump + cache invalidation.

### Tests / verification
- Unit tests:
  1) Edit a file (rename/move a function), run `refresh`, assert nodes replaced.
  2) Call edges: modify callsite, assert outgoing call edges updated.
  3) Ensure dirty coalescing works (multiple edits → single refresh).
- TerminalBench verification:
  - Run `modernize-scientific-stack` and verify:
    - impact PNG after edits matches new callees
    - `state.json.refresh_summary` shows refresh activity

---

## Option B: Dedicated `codecanvasd` daemon (event queue)
### High-level idea
Run a long-lived daemon per workspace that owns the graph and refresh loop. Hooks and MCP clients just enqueue events.

- IPC via file queue in `CLAUDE_CONFIG_DIR/codecanvas/queue/` or a local socket.
- Hook `Edit|Write` enqueues `{type:"file_changed", path, sig}`.
- Daemon coalesces events and performs incremental refresh (as in Option A), guaranteeing background work doesn’t die with hook processes.

### Pros
- Strongest correctness under hook-driven workflows.
- Best place to run rolling background refresh and keep LSP sessions warm.

### Cons
- More engineering (daemon lifecycle, IPC, health checks).

---

## Option C: Periodic full re-init (coarse)
- On a debounce (e.g. every N edits or every 30s), re-run `init` and rebuild everything.
- Simple but expensive; likely too slow for real repos.

---

## Recommendation
Start with **Option A** (incremental refresh) and add the stable-ID refinement if we want “incoming edges remain correct across refactors” without heavy rebuilds. If hook-process lifetimes still prevent meaningful background updating on larger tasks, graduate to **Option B**.

## Open questions for you
1) Should “live freshness” prioritize **correctness** (more rebuild) or **latency** (fewer rebuilds) when they conflict?
2) Are you open to a **state_version bump** to adopt stable function IDs (best long-term)?
3) Should we trigger refresh only on `Edit|Write`, or also on `Bash` when it modifies files?