# Goal
Make `dirty.json` semantics unambiguous and robust: it should behave like a proper “dirty queue” for incremental refresh, without losing entries on crashes/timeouts, and without confusing `missing:true`.

# Current behavior (careful trace)
- **Write/queue:** `codecanvas/hooks/autocontext.py` calls `mark_dirty(root, paths, reason=tool_name)` (via `codecanvas/core/refresh.py`).
  - `mark_dirty()` *immediately* records a `stat()` signature. If `stat()` fails, the entry gets `missing: true`.
- **Consume/dequeue:** `codecanvas/server.py::_refresh_graph_for_dirty_files()` calls `take_dirty(project_dir, max_items=...)`.
  - `take_dirty()` **removes items from `dirty.json` up front** and writes the reduced file back.
- **Refresh:** server removes old nodes for that file path, and only re-parses if the file exists.
- **Deferred work:** if budgets hit, skipped paths are re-queued via `mark_dirty(..., reason="refresh_deferred")`.

Implication: “update dirty.json after success” is *not* how it currently works—items are deleted at **claim time**, not after a successful refresh. That’s correct for “best-effort”, but it’s not crash-safe and it’s easy to misinterpret.

# Why `missing: true` shows up
`missing: true` means `stat()` failed **at the moment the path was marked**, not that a dirty update failed. Commonly this happens because marking can occur before the file exists (pre-tool), or because the hook payload doesn’t include a usable post-tool path to re-mark with a good `stat()`.

---

# Option A: Minimal clarifications + better marking
**Best if you want least code churn.**

## Changes
1. **Schema clarification:** keep `missing` but rename in output/logic to “missing_at_mark”. Add `phase: pre|post`.
2. **Improve post-marking fidelity:**
   - Extend PostToolUse hook matcher to include `Bash` so we can mark again *after* bash runs (same extracted paths, but now they exist so `stat()` is accurate).
   - In `autocontext.py`, if PostToolUse lacks `file_path`, fall back to the pre-tool cached path (store last tool’s file_path in `autocontext_cache.json` with a per-invocation key) and re-mark.
3. **Observability:** in `state.refresh_summary`, include counts for `{deleted_missing, reparsed, deferred}` and `dirty_queue_len_before/after`.

## Pros/cons
- ✅ Reduces confusing `missing:true`.
- ✅ Minimal changes to refresh engine.
- ❌ Still drops items if server dies after `take_dirty()` but before completing refresh.

---

# Option B: Robust claim/ack queue (recommended)
**Makes semantics match intuition:** items only disappear after being successfully applied (or explicitly deferred), and they aren’t lost on crashes.

## Final list of changes
1. **Replace dequeue-on-read with lease/claim semantics** in `codecanvas/core/refresh.py`:
   - `claim_dirty(project_dir, max_items) -> list[dict]`: move items from `pending` → `in_progress` with `claim_id`, `claimed_at`.
   - `ack_dirty(project_dir, claim_id, path, outcome)`:
     - `ok` (reparsed) or `deleted` (file missing handled) → remove item.
     - `deferred` → move back to `pending` with reason `refresh_deferred`.
     - `error` → keep in `pending` (or `error`) with `attempts += 1`, `last_error`.
2. **Stale-claim reaper:** on init/status/impact, before claiming new work:
   - if `in_progress` older than TTL (e.g. 60s), move back to `pending`.
3. **Schema upgrade (backwards compatible):**
   - Each entry stores: `path`, `queued_at`, `updated_at`, `status`, `reason`, `attempts`, `missing_at_mark` (current `missing`), optional `mtime_ns/size`, optional `last_error`.
   - Old `dirty.json` loads as all `pending`.
4. **Server refresh uses claim/ack:**
   - `_refresh_graph_for_dirty_files()` claims N items, then for each:
     - remove nodes
     - if file exists: parse + merge
     - ack outcome (`ok` vs `deleted`)
     - if budget exceeded: ack remaining as `deferred`
5. **Hook improvements (optional but recommended):**
   - PostToolUse matcher includes `Bash`.
   - Add `phase` to marks; re-mark post-tool when possible for better signatures.

## Pros/cons
- ✅ No lost updates on crashes/timeouts.
- ✅ Semantics are clear: only removed from queue after it’s applied.
- ✅ `missing:true` becomes purely informational.
- ❌ More code and tests.

---

# Validation plan (after approval)
- Add unit tests for `claim/ack/reap` behavior (including crash simulation: claim without ack → reap → reprocess).
- Run validators: `uv run ty check codecanvas terminalbench && uv run ruff check --fix codecanvas terminalbench && uv run pytest`.
- Run TB task and confirm behavior doesn’t regress and `dirty.json` entries drain only after refresh.

# Recommendation
Go with **Option B**. It aligns with how you expect `dirty.json` to behave (“clear on success”), prevents dropped items, and keeps `missing:true` from being interpreted as a failure.