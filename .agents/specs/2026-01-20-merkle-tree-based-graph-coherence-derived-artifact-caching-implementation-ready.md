## Executive summary
We will introduce a **Merkle-root “graph snapshot identity”** and make every graph-derived artifact (architecture image, symbol index, call-edge cache) explicitly keyed to that identity, persisted via **atomic writes + a shared cross-process lock**, and protected against **stale-writer regressions**. This removes the current stale/half-baked behavior (e.g., impacts referencing new files while `architecture.png` and `state.symbol_files` stay stuck at init-time).

---

## Goals
1. **No stale architecture**: `architecture.png` always corresponds to the latest known graph snapshot.
2. **No stale symbol mapping**: symbol→file mapping is authoritative and refreshed when graph changes.
3. **Safe call-edge cache**: cached call edges are only merged when compatible with the current snapshot.
4. **Cross-process correctness**: multiple hook processes cannot corrupt or regress the persisted artifacts.
5. **Extensible, idiomatic design**: clear separation of concerns: *board state* vs *graph metadata*.

## Non-goals
- We will **not** build a long-lived daemon server or distributed cache.
- We will **not** persist a full graph snapshot unless needed later (this spec keeps it optional).

---

## New artifact: `graph_meta.json` (authoritative graph metadata)
### Location
In the CodeCanvas artifact directory (same place as `state.json`, `manifest.json`, `call_edges.json`):
- `artifact_dir = get_canvas_dir(Path(project_dir))`
- `graph_meta.json = artifact_dir / "graph_meta.json"`

### Ownership model
- `state.json`: Evidence Board + user intent (claims/decisions/analyses) + cached copies of graph-derived fields.
- `graph_meta.json`: **authoritative** graph snapshot metadata:
  - Merkle root (snapshot identity)
  - per-module leaf hashes (for incremental updates)
  - parser/config info affecting IDs
  - current graph stats
  - authoritative `symbol_files`
  - architecture cache pointers

### Schema (v1)
```jsonc
{
  "version": 1,
  "project_path": "/abs/root",
  "generated_at": 0.0,
  "parser": {
    "use_lsp": true,
    "lsp_langs": ["py"],
    "label_strip_prefix": "optional-string-or-null"
  },
  "merkle": {
    "algo": "sha256",
    "strategy": "content_sha256_with_stat_reuse",
    "root": "<hex>",
    "leaf_count": 0,
    "leaves": {
      "<module_label>": {
        "fs_path": "/abs/path/to/file.py",
        "mtime_ns": 0,
        "size": 0,
        "content_sha256": "<hex>",
        "leaf": "<hex>",
        "missing": false
      }
    },
    "config_leaf": "<hex>"
  },
  "graph": {
    "digest": "<hex>",
    "stats": {"modules":0,"classes":0,"funcs":0,"import_edges":0,"call_edges":0,"contains_edges":0},
    "parse_summary": {"parsed_files":0,"skipped_files":0,"lsp_files":0,"tree_sitter_files":0,"lsp_failures":{}},
    "quality": {"parsed_files":0,"skipped_files":0,"lsp_files":0,"tree_sitter_files":0},
    "symbol_files": {"fn_x": "/abs/path.py"}
  },
  "architecture": {
    "latest_png": "architecture.png",
    "digest_png": "architecture.<digest>.png",
    "digest": "<hex>",
    "rendered_at": 0.0
  },
  "updated_by": {"pid": 0, "action": "init|load|refresh"}
}
```

Notes:
- `module_label` must match `GraphNode.label` for `NodeKind.MODULE` (this is what IDs are salted by).
- `graph.digest` is exactly `merkle.root` (single snapshot identity).

---

## Merkle tree definition (deterministic + idiomatic)
### Leaf inputs
For each module node `m` (`kind==MODULE`):
- key = `m.label` (normalized, stable under the parser’s label rules)
- content hash = `sha256(file_bytes)`

Leaf hash bytes:
- `leaf = sha256( b"file\0" + label_utf8 + b"\0" + content_sha256_bytes )`

Config leaf:
- `config_json = canonical_json({"version":1,"use_lsp":...,"lsp_langs":...,"label_strip_prefix":...})`
- `config_leaf = sha256( b"config\0" + config_json_bytes )`

### Root computation
- Build an ordered list of `(key, leaf_hash)` for:
  - all module leaves keyed by `module_label`
  - plus a synthetic config entry keyed by `"\x00config"` (so it sorts first)
- Sort by key ascending.
- Build the Merkle root by hashing pairs:
  - `node = sha256(b"node\0" + left + right)`
  - if odd count at a level, **duplicate the last**.
- Empty-tree root:
  - `sha256(b"empty")`

### Your question: is “stat reuse” a problem?
Using **content-hash with stat-based reuse** is standard and safe in practice:
- We reuse prior `content_sha256` only when `(mtime_ns,size,fs_path)` are unchanged.
- The theoretical failure mode (content changes but mtime+size don’t) is extremely rare; we’ll mitigate it with:
  1) an optional env override `CODECANVAS_MERKLE_ALWAYS_REHASH=1` (forces full re-read)
  2) a pre-write **re-stat verification** step to avoid publishing a digest after inputs changed mid-compute.

---

## Derived artifacts become digest-keyed caches
### Architecture images (per your choice)
We will store:
- `architecture.<digest>.png` (immutable, per snapshot)
- `architecture.png` (latest pointer, overwritten)

Rules:
1. If `graph_meta.graph.digest` changes OR `architecture.<digest>.png` missing → render.
2. Render writes `architecture.<digest>.png` first, then overwrites `architecture.png` with the same bytes.
3. `graph_meta.architecture.digest` must equal `graph_meta.graph.digest` after success.

### Call-edge cache (`call_edges.json`)
We will make the call-edge cache snapshot-aware to prevent stale merges.

Changes:
- Bump cache version: `_CALL_EDGE_CACHE_VERSION = 3`.
- Add required header: `graph_digest`.

Rules:
1. Load/merge cached call edges only if `cache.graph_digest == graph_meta.graph.digest`.
2. Always write `call_edges.json`, **even when edges_total==0**, so we never accidentally reuse a prior snapshot’s edges.

---

## Cross-process safety: one lock, one writer contract
### Unify locking
Introduce a shared context manager used everywhere we write artifacts:
- new module: `codecanvas/core/lock.py` (or equivalent)
- lock file: `artifact_dir / "lock"`
- acquisition: best-effort but with retry for up to `timeout_s` (default 2s)

### Writer contract
Any code that writes any of the following must hold the lock:
- `graph_meta.json`
- `architecture.png` / `architecture.<digest>.png`
- `call_edges.json`
- graph-derived fields in `state.json` (architecture evidence metrics, cached `symbol_files`)

If lock cannot be acquired:
- actions may still run (compute results), but they **must not** write graph_meta/architecture/call_edges/state-derived updates.

---

## Stale-writer prevention (critical)
Even with atomic writes + locks, a process could compute a digest, then the repo changes, then it writes an outdated meta.

Mitigation:
1. While computing leaves we record the observed `mtime_ns`/`size` per module file.
2. Immediately before publishing `graph_meta.json` we re-stat those files under the lock:
   - If any signature changed → abort publish (return “stale compute”).
3. When digest matches existing meta, we only allow updates that **improve** graph quality:
   - Compare `(parsed_files, -skipped_files, lsp_files, tree_sitter_files)` lexicographically.
   - Reject overwriting with a strictly worse quality meta.

This prevents regressions when (e.g.) LSP warmup later improves parsing.

---

## Lifecycle wiring (what changes where)
### 1) Add graph_meta builder utilities
New module `codecanvas/core/graph_meta.py`:
- `graph_meta_path(project_dir: Path) -> Path`
- `load_graph_meta(project_dir: Path) -> dict | None`
- `compute_graph_meta(*, graph: Graph, project_dir: Path, parser_summary: ParseSummary, use_lsp: bool, lsp_langs: set[str] | None) -> dict`
- `publish_graph_meta(project_dir: Path, new_meta: dict, *, timeout_s: float, action: str) -> tuple[bool, dict]`
  - handles lock + stale-input verification + quality rules + atomic write + manifest update
- `ensure_architecture_current(project_dir: Path, graph: Graph, meta: dict) -> dict`
  - renders if needed; updates meta; atomic write.

### 2) Server changes (`codecanvas/server.py`)
#### Init (`_action_init`)
Rewire ordering:
1. parse graph
2. compute candidate `graph_meta`
3. publish `graph_meta` under lock
4. load/merge call-edge cache **only if digest matches**
5. start call graph workers
6. ensure architecture current (writes per-digest + latest)
7. create/repair `state.json`:
   - create `E1` architecture evidence if missing
   - set `E1.metrics` from `graph_meta.graph.stats`
   - set `state.symbol_files = graph_meta.graph.symbol_files` (cached)
   - save_state

#### Ensure-loaded (`_ensure_loaded`)
After parsing:
1. compute+publish graph_meta (quality-gated)
2. merge call-edge cache only if digest matches
3. ensure architecture current (if missing)
4. reconcile `state.json` cached fields (symbol_files + architecture evidence metrics) from graph_meta; save only if changed.

#### Refresh (`_refresh_graph_for_dirty_files`)
After defs update (nodes/edges added/removed):
1. compute+publish updated graph_meta (incremental via leaf reuse)
2. if digest changed → ensure architecture current
3. persist call-edge cache with `graph_digest` header (even if empty)
4. set `state.symbol_files` from graph_meta (or directly from graph; must match)

#### Call-edge persistence (foreground/background)
Update `_persist_call_edge_cache(...)` to accept `graph_digest` and always write.

### 3) Hooks changes (`codecanvas/hooks/autocontext.py`)
Update `_select_symbol_from_state(file_path)`:
- Prefer `graph_meta.json`’s `graph.symbol_files` (authoritative)
- Fallback to `state.symbol_files` if graph_meta missing/unreadable

This removes the “symbol selection based on stale init-time state” failure mode.

---

## Migration behavior
- If `graph_meta.json` is missing (older runs):
  - first action that loads graph will create it.
- If `call_edges.json` is version 2 (no digest):
  - ignored under version check; regenerated.
- `state.json` remains compatible (no version bump); we only refresh cached fields.

---

## Tests (implementation-ready)
Add tests in `codecanvas/tests/`:
1. **Merkle determinism**: same inputs → same root; reorder files → same root.
2. **Digest change on new module**: add new file → root changes; architecture.<digest>.png created.
3. **Call-edge cache gating**: write call_edges.json with digest A, load graph digest B → ensure merge is skipped.
4. **State reconciliation**: start with state.json missing new symbols; after `_ensure_loaded`, cached `state.symbol_files` includes them and architecture evidence metrics match.
5. **Quality gating**: simulate existing meta with higher `parsed_files` and attempt publish worse quality with same digest → reject.

---

## Validation / verification checklist
Run:
- `uv run ruff check --fix codecanvas terminalbench`
- `uv run ty check codecanvas terminalbench`
- `uv run pytest codecanvas/tests`

TerminalBench verification:
- rerun `modernize-scientific-stack` and confirm:
  - `graph_meta.json` exists
  - `architecture.<digest>.png` exists and `architecture.png` updated
  - state `E1.metrics.modules/classes/funcs` match `graph_meta.graph.stats`
  - `state.symbol_files` includes `analyze_climate_modern.py` symbols
  - `call_edges.json` contains `graph_digest` and is not merged across mismatches
  - no `.bak` files from parse failures.

---

## Implementation steps (atomic)
1. Add `core/lock.py` (shared lock).
2. Add `core/graph_meta.py` (Merkle + meta compute + publish + ensure_architecture_current).
3. Update `server.py`:
   - cache v3 with graph_digest
   - init/load/refresh wiring to publish meta + reconcile state + render architecture by digest
4. Update `hooks/autocontext.py` to read symbol mapping from graph_meta.
5. Add tests.
6. Run validators + TerminalBench rerun.

If you confirm, I’ll implement exactly the above (with the per-digest architecture file naming as `architecture.<full_digest>.png` unless you prefer a shorter prefix).