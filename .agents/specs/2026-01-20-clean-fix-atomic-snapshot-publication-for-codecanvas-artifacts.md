## Static trace (what I can conclude from the run logs/artifacts)

**Key contradiction:** the run’s *graph* clearly contained `/app/analyze_climate_modern.py` during impact/call-graph, but the persisted **`graph_meta.json`** and **architecture** stayed pinned to the legacy-only snapshot.

Evidence from the run artifacts:
- `sessions/codecanvas/graph_meta.json`
  - `leaf_count=1` (only `climate_analyzer/analyze_climate.py`).
  - **No `updated_by` field**, which strongly implies it was *not* written by `publish_graph_meta()` (that function always injects `updated_by` when it actually writes).
  - The file *was* rewritten later (its `architecture.rendered_at` is later than `generated_at`), which matches `ensure_architecture_current()` rewriting `graph_meta.json`.
- `sessions/codecanvas/state.json`
  - Contains an analysis targeting `fn_3e34fb7c_load_temperature_data` and includes `mod_3e34fb7c` → the in-memory graph at impact time **did** include the modern module.
  - Yet `state.symbol_files` is still legacy-only → reconciliation was still driven by the stale `graph_meta.json`.
- `sessions/codecanvas/call_edges.json` is still the **legacy-only 3 edges** (and a different `instance_id` than `state.call_graph_summary.instance_id`), while `state.call_graph_summary` reports `considered_files=2` and has samples with `caller_path=/app/analyze_climate_modern.py`.

**Most likely failure mode (high confidence):**
- Multiple processes are writing/reading the same artifact directory.
- The single shared artifact lock is sometimes held long enough that other writers time out.
- Current code treats “failed to publish” as “use existing on-disk meta”, which lets stale meta *win*.

**What I’m not 100% sure about:** whether the publish failures are *only* lock contention (very plausible because architecture rendering currently happens while holding the lock) vs. also `_verify_signatures()` rejecting because files changed between hash and publish. The redesign below eliminates both classes of failure.

---

## Core issue to fix (cleanly)
We need a **single, explicit publication protocol** for the “current graph snapshot”, such that:
1) derived artifacts are published **atomically as a coherent set**,
2) long operations don’t hold the lock,
3) “can’t acquire lock” never causes the system to silently keep stale pointers.

---

## Target invariants (what ‘correct’ means)
For a given `graph_digest=D`:
- `graph_meta` (and its `symbol_files`) correspond to the graph that produced `D`.
- `architecture.png` corresponds to `D`.
- `call_edges.json` (if present) is explicitly tagged with `graph_digest=D`.
- `state.json` records which digest it is reconciled against (so it can self-heal on mismatch).
- Writers never hold the artifact lock while doing expensive work (SVG layout / cairosvg rasterization / LSP calls).

---

## Proposal options

### Option A: Two‑phase commit under one lock (no per‑digest meta/call_edges)
**Idea:** Keep single files (`graph_meta.json`, `call_edges.json`, `architecture.png`) but enforce a strict two-phase protocol:
1) compute everything (meta + png + call edges payload) **outside** the lock into temp files
2) acquire lock and perform only atomic renames + manifest updates inside
3) if lock can’t be acquired: **do not overwrite state from stale disk**, and retry later (bounded backoff)

Pros: smaller diff
Cons: still relies on lock acquisition in the critical path; harder to recover if writers frequently contend.

### Option B: Content‑addressed snapshot store + atomic pointers (**recommended**)
**Idea:** Make each snapshot publishable even under contention by writing **digest-addressed** artifacts, and only use the lock for fast “pointer flip”.

Artifacts:
- `graph_meta.<D>.json` (snapshot record)
- `architecture.<D>.png` (already exists)
- `call_edges.<D>.json` (digest-scoped call edges cache)
- Pointers (small, fast to update):
  - `graph_meta.json` → latest snapshot record (copy)
  - `architecture.png` → latest architecture (copy)
  - `call_edges.json` → latest call edges for current digest (copy)
- `state.json` gains fields like: `graph_digest`, `graph_meta_digest`, `call_edges_digest`.

Publication protocol:
1) Build/refresh `_graph` in memory.
2) Compute digest `D` and produce:
   - meta JSON bytes
   - architecture PNG bytes
   - (optional) call edges payload bytes
   **all outside the lock**.
3) Write digest-addressed files with atomic rename (safe even if multiple writers race on same digest).
4) Acquire lock and do a tiny atomic pointer flip:
   - overwrite `graph_meta.json`, `architecture.png`, `call_edges.json` to point to digest `D`
   - update manifest
5) Readers always treat `graph_meta.json` digest as authoritative for reconciliation.

This removes the “scotch tape” fallback behavior: even if the pointer flip is delayed, the snapshot artifacts exist and a later run can flip pointers deterministically.

---

## Implementation plan (for whichever option you choose)

### 1) Introduce a single ‘SnapshotPublisher’ / ‘ArtifactTxn’ API
New core module (name tbd, e.g. `codecanvas/core/snapshot.py`):
- `compute_snapshot(graph, project_dir, parse_summary, …) -> Snapshot` (digest + bytes payloads)
- `write_snapshot_files(snapshot)` (writes digest-addressed files; atomic rename)
- `flip_pointers(snapshot)` (lock-held, fast)

### 2) Remove long work from inside the artifact lock
- Refactor `ensure_architecture_current()` so the expensive `ArchitectureView(...).render()` + `cairosvg.svg2png()` happens **before** lock acquisition.
- The lock should cover only file renames/copies and manifest updates.

### 3) Make “publish failure” non-regressive
- Eliminate any path where “can’t publish” causes us to reuse stale meta as the logical current snapshot.
- `_graph_digest` should always track the in-memory graph digest; persistence should be retried / pointer-flipped later.

### 4) Digest-scoped call edge cache
- Write `call_edges.<D>.json` and only set `call_edges.json` when it matches `graph_meta.json`’s digest.
- This prevents mixing call edges from different snapshots and avoids the current multi-process `instance_id` confusion.

### 5) State coherence
- Add `graph_digest` to `state.json` and reconcile on load:
  - if `state.graph_digest != graph_meta.digest`, rewrite `state.symbol_files` from meta and update the architecture evidence metrics/path.
- Remove `_save_state_with_lock()`’s current “merge-from-latest” fallback; instead:
  - either block longer on lock for state writes (cheap), or
  - make state writes append-only + compact (bigger change, probably unnecessary once lock holds are short).

### 6) Lock unification
- Replace `core/refresh.py`’s `_canvas_lock` (which currently proceeds without lock on contention) with the unified artifact lock API.
- Ensure **all** artifact writes that affect coherence (`dirty.json`, `graph_meta*`, `call_edges*`, `state.json`, pointer PNGs) go through the same transaction semantics.

### 7) Diagnostics (so we can be sure)
Add a small persisted diagnostic record (either inside `state.json` or a new `coherence.json`):
- last snapshot digest computed
- whether digest files were written
- whether pointer flip succeeded
- lock wait time / failure reason

This will let us prove causality on the very next TB run.

---

## Tests
- Unit: snapshot digest-addressed files are written even when pointer flip lock is held by another process.
- Unit: pointer flip never regresses (if `graph_meta.json` is already newer/different digest, don’t flip back).
- Unit: state reconciliation updates `symbol_files` when digest changes.

---

## Verification run
Re-run `modernize-scientific-stack` and confirm:
- `graph_meta.<D>.json` exists with **leaf_count=2** (legacy + modern)
- `graph_meta.json` digest matches `<D>`
- `architecture.<D>.png` exists and `architecture.png` matches it
- `call_edges.<D>.json` + `call_edges.json` show edges_total=5 and `graph_digest=<D>`
- `state.json.symbol_files` includes `/app/analyze_climate_modern.py`

---

## My recommendation
Pick **Option B**: it’s the cleanest way to make coherence robust under multi-process contention without relying on “best-effort fallback” semantics.
