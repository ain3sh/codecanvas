# Goal
Make `use_lsp=True` practical (seconds, not minutes) by treating language servers as long-lived, stateful resources and by avoiding N×per-file/per-symbol LSP request patterns.

# Constraints / Non-goals
- Keep MCP surface + Views unchanged (`server.py` actions and PNG outputs stay the same).
- No “full semantic call graph eagerly”; semantics are **on-demand** and **budgeted**.
- Don’t introduce new heavy deps unless there’s a clear ROI (Tree-sitter is a later optional phase).

# Current Bottlenecks (confirmed in anchors)
- `Parser._try_lsp_parse()` calls `asyncio.run(...)` **per file**.
- `Parser._parse_with_lsp()` uses `async with LSPClient(...)` **per file** → spawns & initializes server per file.
- `workspace = file_path.parent` (suboptimal root → repeated indexing).
- `_extract_call_edges()` does `prepareCallHierarchy + outgoingCalls` **per function** and also matches targets via an O(n²) scan.
- `LSPClient` uses `stderr=PIPE` but never drains stderr → possible deadlock/backpressure.
- `LSPClient._send()` has no serialization lock → unsafe once we add concurrency.
- `parse_directory()` uses `Path.rglob('*')` and only filters *after* enumeration → still traverses huge dirs like `node_modules/`.

# Proposed Architecture
## 1) Workspace + File Enumeration (fast, deterministic)
- Add a shared workspace-root resolver (no import cycle with `server.py`):
  - `find_workspace_root(start_path)` checks (nearest-first): `.git`, `pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, etc.
  - Cache results per input path.
- Replace `Path.rglob('*')` with `os.walk()` + directory pruning so excluded dirs are never traversed.

## 2) LSP Subsystem = Persistent Sessions
Introduce a small LSP runtime layer that owns processes and caching.

**`LspSession` (one per `(lang, workspace_root)`):**
- Starts server once; initializes once.
- Drains **stdout + stderr** via background tasks.
- Serializes writes with an `asyncio.Lock`.
- Uses per-method timeouts (short for `documentSymbol`, tighter for refinement requests).
- Supports request cancellation:
  - On timeout or task cancellation, send `$/cancelRequest` best-effort.
- Caches:
  - `document_symbols(uri)` cached by `(uri, mtime, size)` (or hash if needed).
  - Optional refinement caches (call hierarchy results) keyed by `node_id`.

**`LspSessionManager` (global singleton):**
- `get(lang, workspace_root) -> LspSession` (create if missing).
- Eviction policy: LRU/idle timeout; cap max sessions to prevent runaway server count.
- Crash recovery: if process exits, transparently restart once, then fall back to naive for that file.

## 3) Parser Pipeline = Two Phases
**Phase A (fast graph build, always):**
- Build MODULE/CLASS/FUNC nodes via:
  - LSP document symbols (if enabled), otherwise Naive.
- Always do naive import detection + existing `infer_calls()` for approximate CALL edges.
- Do **not** do call hierarchy during `init`.

**Phase B (semantic refinement, optional & budgeted):**
- Triggered only on `impact` (or a future explicit `refine` action).
- Refine only the focused neighborhood:
  - For the target node (or top-K nearby funcs), fetch call hierarchy (outgoing/incoming) with hard budgets.
  - Merge results into graph, `rebuild_indexes()`, then run `Analyzer`.

This preserves “instant init” while still allowing high-quality LSP edges where it matters.

# Easy-to-Fix Improvements Rolled In
- Avoid double disk reads: when Parser already has file `text`, let LSP open via `didOpen` using provided text (no `Path.read_text()` inside `_ensure_document_open`).
- Replace O(n²) call-target matching with a dict map: `(simple_name, start_line) -> node_id`.
- Make `LSPClient` concurrency-safe (send lock, use `get_running_loop()`).
- Apply `SYMBOL_FILTERS` during symbol ingestion to reduce noise and downstream work.

# Implementation Steps (ordered, minimal-risk)
1. **Transport correctness/perf in `codecanvas/parser/lsp.py`**
   - Add stderr draining task (or route stderr to DEVNULL behind a debug flag).
   - Add `_send_lock` to serialize writes.
   - Add `open_document(uri, text, language_id, version)` so Parser can pass in-memory text.
   - Optional: cancellation-on-timeout (`$/cancelRequest`).
2. **Shared workspace root resolver**
   - Create `codecanvas/parser/workspace.py` (or `codecanvas/core/fs.py`) with `find_workspace_root()`.
   - Use it in Parser’s LSP path (workspace_root, not `file_path.parent`).
3. **Fast file finder with pruning**
   - Replace `rglob` with `os.walk` pruning using the existing exclude set.
4. **Add `LspSession` + `LspSessionManager`**
   - New module `codecanvas/parser/lsp_session.py`.
   - Implement caching + restart logic.
5. **Refactor Parser LSP path to reuse sessions and avoid per-file event loop**
   - Add an async internal method to parse *all* files in one `asyncio.run(...)` call.
   - Use one session per `(lang, workspace_root)` for the entire directory parse.
   - Ensure concurrency limits per session.
6. **Defer call hierarchy by default**
   - Remove eager `_extract_call_edges()` from `_parse_with_lsp()` (or gate behind a flag default-off).
7. **On-demand refinement in `server.py` impact path**
   - Before rendering impact, optionally run a budgeted refinement around the chosen node.
   - Keep budgets strict so impact never “hangs”.
8. **Validation**
   - Add unit tests for workspace-root resolver and pruned file enumeration.
   - Add session/caching tests using a fake LSP client (no real servers required).
   - Run `uv run python -m pytest codecanvas/tests/ -v`.

# Success Criteria
- `init` with LSP symbols enabled: dominated by file IO + documentSymbol requests; no per-file server spawn.
- No hangs from stderr backpressure.
- Call hierarchy cost is bounded and only paid on-demand.
- Existing visual pipeline remains unchanged; all tests pass.

# Optional Phase (later)
- Introduce a syntax-first extractor (Tree-sitter) for symbols + call sites, using LSP only for cross-file resolution; this can further reduce LSP dependence, but it’s not required to get the big wins above.