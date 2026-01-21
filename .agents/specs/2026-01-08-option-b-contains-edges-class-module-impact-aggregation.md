## Goal
Fix the “impact view shows `{symbol, module}` + `edge_count: 0`” failure for **CLASS/MODULE targets** by making containment first-class in the graph and then computing impact at the correct semantic level (calls happen in funcs, but users often ask about classes/modules).

## Problem recap
- Today the graph has `IMPORT` (module→module) and `CALL` (func→func) edges.
- Containment (module/class membership) exists only as `GraphNode.parent` metadata.
- Impact rendering assumes the **target node participates directly in call edges**, so CLASS/MODULE targets yield 0 callers/callees even when their methods do have call edges.

## Proposal (Option B)
### 1) Add `EdgeType.CONTAINS`
Represent structure explicitly:
- `MODULE ─CONTAINS→ CLASS`
- `MODULE ─CONTAINS→ FUNC` (top-level)
- `CLASS  ─CONTAINS→ FUNC` (methods)
- (Bonus, recommended for correctness) `CLASS ─CONTAINS→ CLASS` for nested classes when present.

### 2) Redesign impact computation to support compound targets
Define an **effective call-participant set**:
- target is `FUNC`: `{target}`
- target is `CLASS`: all descendant methods (transitive `CONTAINS` closure)
- target is `MODULE`: all descendant funcs (transitive `CONTAINS` closure)

Then compute callers/callees using only `CALL` edges incident to that set, and **aggregate** neighbors for readability.

### 3) Keep slices clean
Impact “blast radius” (`compute_slice`) should stay **call/import-only**. `CONTAINS` must never explode a slice to “entire module/class tree” unless explicitly requested later.

## Key design decisions you need to make
### Decision A (choose one; I recommend Canonical)
1. **Incremental: add CONTAINS edges (keep GraphNode.parent)**
   - Pros: smaller diff.
   - Cons: two sources of truth; easy to drift.

2. **Canonical: CONTAINS as source of truth (remove GraphNode.parent)** *(recommended)*
   - Pros: clean model; fewer special cases; faster lookups via edge indexes.
   - Cons: breaks internal APIs; requires updating parser/analyzer/tests (contained + manageable).

### Decision B: Aggregation level for CLASS/MODULE impact (default = aggregated)
- **Aggregated (recommended):** show neighbor **CLASS** (else MODULE) nodes for class targets, and neighbor **MODULE** nodes for module targets.
- **Fine-grained:** show neighbor **FUNC** nodes (more detail, more noise).

### Decision C: “Too many children” policy (recommended)
- Count over **all** descendant funcs for accuracy.
- Display only top-N neighbors by call frequency (current view already hard-caps to 8 per side).

## Implementation plan (high-level)
### Step 1 — Model
- `codecanvas/core/models.py`
  - Add `EdgeType.CONTAINS`.
  - If **Canonical**: remove `GraphNode.parent`; add `Graph.get_children() / get_parent()` implemented via `CONTAINS` edges and existing edge indexes.
  - Update `Graph.stats()` to report `contains_edges`.

### Step 2 — Parser emits containment edges (and fixes nesting)
- `codecanvas/parser/__init__.py`
  - Emit `CONTAINS` edges during symbol ingestion rather than relying on `parent` fields.
  - Rework LSP symbol walk to pass a `parent_container_id` instead of `parent_class` string.
  - For tree-sitter defs, build class IDs first, then create class nodes/edges so nested classes can attach to the correct outer class.

### Step 3 — Analyzer impact API
- `codecanvas/core/analysis.py`
  - Ensure slice traversal filters **only** `{CALL, IMPORT}`.
  - Add helpers:
    - `descendant_funcs(node_id) -> set[str]` (transitive via `CONTAINS`).
    - `impact_call_counts(target_id) -> (caller_counts, callee_counts)` using graph edge indexes.
    - `impact_display_id(func_id, center_kind)` for aggregation (FUNC vs CLASS/MODULE).

### Step 4 — Impact view consumes aggregated counts (and ignores CONTAINS)
- `codecanvas/views/impact.py`
  - Change render input to use **precomputed callers/callees** (or update internal aggregation to use the effective target-set and filter `EdgeType.CALL`).
  - Never treat `CONTAINS` as a caller/callee edge.

### Step 5 — Server wiring + evidence metrics
- `codecanvas/server.py`
  - `_action_impact` uses the new Analyzer impact API.
  - Evidence metrics become explicit, e.g.:
    - `call_edges_shown`, `callers_shown`, `callees_shown`, `node_count` (optional), rather than raw “all edges in neighborhood”.

### Step 6 — Tests
- Add/update unit tests:
  - Parser produces `CONTAINS` edges.
  - CLASS impact aggregates method call edges into non-zero callers/callees.
  - Slices remain unaffected by `CONTAINS`.

### Step 7 — Validation / rollout
- Run `uv run ruff check codecanvas` and `uv run pytest codecanvas/tests`.
- Re-run the Harbor task (`custom-memory-heap-crash`) and confirm:
  - class impacts show non-zero callers/callees when methods have call edges.
  - diagnostics clearly indicate whether remaining misses are “external/not indexed” vs “range mismatch”.

## Logging cleanup note (tracked for later)
After we confirm correctness on Harbor, we should do a focused cleanup pass to either (a) keep only durable state-based diagnostics, or (b) remove all temporary debug logging in both CodeCanvas + TerminalBench harness.
