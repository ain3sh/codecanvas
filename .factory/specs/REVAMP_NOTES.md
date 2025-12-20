# CodeCanvas Backend Revamp Notes (Post Context-Compression)

This file is intended as a “treasure trove” / brain dump of everything learned so far about:

- How CodeCanvas works today (anchors into the current backend)
- Why LSP parsing is currently *extremely latent*
- Concrete, low-risk changes that should make LSP viable
- A bigger re-architecture that borrows proven ideas from Zed (fast editor primitives)

If context gets compressed, I should be able to reopen *only this* and quickly reconstruct the plan.

---

## 0) Primary Goal

Make CodeCanvas backend “blazing fast” while enabling high-quality LSP-powered symbol + call graph extraction.

Constraints / biases:

- Keep the UI/visualization pipeline unchanged unless necessary.
- Prefer **incremental, measurable wins** (start with reuse + caching + deferral).
- Avoid “N×requests per symbol” patterns.
- Treat LSP servers as *stateful, expensive processes* (warm them, don’t respawn).

---

## 1) CodeCanvas Anchor Points (Where to Re-Orient)

### 1.1 Entry point and action routing

- `codecanvas/server.py`
  - `canvas_action(...)` is the single explicit API.
  - `action=init` builds a graph via `Parser()` and stores state.
  - `action=impact` runs graph traversals via `Analyzer` and renders impact view.
  - `action=claim/decide/mark/skip/task_select/status/read` are stateful workflow actions.

Key observation:

- `server._action_init(...)` currently instantiates `Parser()` with defaults.
- Parser defaults matter because they decide whether LSP is used.

### 1.2 Graph construction

- `codecanvas/parser/main.py`
  - `class Parser` with `__init__(self, use_lsp: bool = False)`
    - LSP is **off by default** (comment: “LSP is ~500x slower but ~8% more accurate”).
  - `parse_directory(...)`:
    - scans files (extensions allowlist, exclude_patterns)
    - calls `_parse_file` for each
    - then calls `infer_calls(funcs, graph)` (regex-ish inference from bodies)
  - `_parse_file(...)`:
    - if `self.use_lsp` and `has_lsp_support(lang)`: tries `_try_lsp_parse`
    - else for `lang in {"py", "ts"}` uses `NaiveParser.parse(...)`
    - else “plain module only” parsing for some languages
  - `_try_lsp_parse(...)`:
    - calls `asyncio.run(self._parse_with_lsp(...))` **per file**
  - `_parse_with_lsp(...)`:
    - `async with LSPClient(server_cmd, workspace) as client:`
    - `symbols = await client.document_symbols(uri)`
    - `self._process_lsp_symbols(...)` (creates GraphNode(s) for modules/classes/functions)
    - tries `await self._extract_call_edges(client, uri, funcs, graph)`
      - **IMPORTANT**: loops every function, calls LSP call hierarchy
    - still uses naive import detection after (py/ts)

### 1.3 LSP client implementation

- `codecanvas/parser/lsp.py`
  - `LANGUAGE_SERVERS` maps language -> cmd
    - e.g. `basedpyright-langserver`, `typescript-language-server`, `gopls`, `rust-analyzer`, `jdtls`, etc.
  - `class LSPClient` (async JSON-RPC over subprocess stdio)
    - `start()` spawns process with **stdin/stdout/stderr = PIPE**
    - creates `_reader_task = asyncio.create_task(self._read_responses())`
    - `_read_responses()` reads **ONLY stdout**, never drains stderr
      - this can deadlock if server writes enough to stderr
    - `_initialize()` sets `root_uri` + `workspace_folders` to `self.workspace`
    - `document_symbols()` sends `textDocument/documentSymbol`
    - `call_hierarchy_prepare()` calls `textDocument/prepareCallHierarchy`
    - `outgoing_calls()` calls `callHierarchy/outgoingCalls`
    - `incoming_calls()` exists too
    - `_ensure_document_open()` reads file from disk and sends `didOpen` with `version=1`
      - no incremental `didChange` support (fine for “read-only analysis”, but important if we ever want incremental indexing)

### 1.4 Impact traversal (graph algorithms)

- `codecanvas/core/analysis.py`
  - `Analyzer.compute_slice(...)` (BFS slice, import + call edges)
  - `_include_ancestors(...)` (func → class → module)
  - `neighborhood(...)` (k-hop neighborhood, max node cap)
  - `find_target(...)` (ID match, exact label match, partial label match)

---

## 2) Why LSP Mode Is So Slow Today (Root Cause Inventory)

This is the critical “why” to preserve.

### 2.1 Per-file server process lifecycle

In `codecanvas/parser/main.py`, LSP parsing does:

- `asyncio.run(...)` per file
- `async with LSPClient(...)` per file
  - which spawns a **fresh language server process per file**
  - initializes per file
  - does documentSymbol + call hierarchy per file
  - then terminates per file

This is the biggest multiplier (process spawn + initialize is expensive).

### 2.2 Wrong / suboptimal workspace root

`workspace = str(file_path.parent.absolute())` in `_parse_with_lsp`.

For most language servers, workspace root should be the *project/worktree root* (the folder with config / package manifests / build graph), not the file’s directory.

Symptoms:

- repeated re-indexing across siblings
- worse symbol resolution
- typecheck context missing

### 2.3 Call hierarchy amplification (N×calls per function)

`_extract_call_edges(...)` loops over **every function** and requests:

- `prepareCallHierarchy` per function
- `outgoingCalls` per function

Even with a warm server, this is heavy. With a cold server per file, it’s catastrophic.

### 2.4 Event loop churn

`asyncio.run(...)` creates and destroys an event loop per file.

### 2.5 Potential stderr pipe deadlock

`LSPClient.start()` uses `stderr=PIPE`, but `_read_responses()` never reads stderr.

If a language server writes enough logs to stderr, the pipe can fill and block the process → requests stall → perceived “infinite latency”.

### 2.6 Other likely contributors

- No request cancellation support; long requests just block until timeout.
- No batching/limits; call hierarchy requests can be huge.
- No caching across files; repeated work for every file.

---

## 3) Minimal Fix Set (“Make LSP Viable First”)

These are the highest ROI changes that should unlock usable performance without changing the core product.

### 3.1 Introduce persistent per-workspace LSP sessions

Goal: **one server process per (workspace, language)**, reused across all files.

Conceptually:

- `LspSessionManager` keyed by `(lang, workspace_root)`
- session owns:
  - the subprocess
  - initialize lifecycle
  - opened documents set
  - request queue and cancellation

Then parsing becomes:

- detect workspace root
- get (or create) session
- open all needed docs (or just-in-time)
- query documentSymbols (fast-ish)

### 3.2 Fix workspace root detection

Use `server._find_repo_root(...)` or similar logic to detect project root from input path, and pass that as the workspace root.

For multi-language monorepos, root detection might need heuristics:

- nearest `pyproject.toml` / `package.json` / `go.mod` / `Cargo.toml` / `.git` boundary
- optional override via env var or argument

### 3.3 Drain stderr (mandatory correctness/perf)

If `stderr=PIPE`, always read it.

Options:

- simplest: spawn an asyncio task that continuously reads stderr and discards or stores last N KB
- or redirect stderr to `DEVNULL` if we don’t need it

### 3.4 Defer call hierarchy (don’t do it in the initial full parse)

Instead of building call edges via call hierarchy while parsing, split into phases:

1. Build symbol table (modules/classes/funcs) cheaply
2. Build *approximate* call edges via regex/Tree-sitter
3. Use LSP call hierarchy only:
   - on-demand for a focused view
   - or as a background refinement pass with strict budgets

### 3.5 Add cancellation + budgets

Hard limits:

- max call hierarchy requests per file / per second
- timeouts per request
- ability to cancel in-flight requests when the parse phase ends

---

## 4) Zed: Concrete Performance Patterns Worth Stealing

Zed’s approach isn’t “LSP everywhere”; it’s “Tree-sitter for syntax features, LSP for semantics, both fully async”.

### 4.1 Reuse warm servers + incremental sync

Zed doesn’t spawn language servers per file; it starts a server for a worktree and registers buffers via didOpen.

Relevant code pointers (in the sparse clone):

- `context/zed-repo/crates/project/src/lsp_store.rs`
  - `start_language_server(...)` shows persistent server startup tied to a worktree.
  - it later registers buffers (didOpen) for already-open buffers.

- `context/zed-repo/crates/lsp/src/lsp.rs`
  - `LanguageServer::new(...)` spawns the process once.
  - it continuously drains stdout and stderr.

### 4.2 Always drain stderr and avoid IO deadlocks

- `context/zed-repo/crates/lsp/src/lsp.rs` has explicit `handle_stderr(...)` to drain stderr.
- outbound writes are buffered (`BufWriter`) and serialized.

### 4.3 Cancellation is default

Zed sends `$/cancelRequest` on drop of an in-flight request:

- `context/zed-repo/crates/lsp/src/lsp.rs` uses a `cancel_on_drop` deferred action around requests.

### 4.4 Capability tuning to avoid “slow by default” LSP behaviors

Example from Zed: don’t request completion resolve fields that cause server slowness.

- `context/zed-repo/crates/lsp/src/lsp.rs` explicitly avoids resolving completion `textEdit`.

### 4.5 UTF-16 position translation is *cheap* (rope indexes it)

Zed invests in fast point/offset conversions so LSP interop doesn’t dominate:

- `context/zed-repo/crates/rope/src/chunk.rs` uses `u128` bitmaps for newlines, utf16 widths, etc.
- `context/zed-repo/crates/language/src/language.rs` maps `PointUtf16` to LSP `Position`.

### 4.6 Tree-sitter queries power lots of “structure” features

Example: runnable tags come from Tree-sitter queries:

- `context/zed-repo/crates/languages/src/rust/runnables.scm`

This is the bigger philosophical lesson:

- Use Tree-sitter (or cheap parsing) for “what’s in this file?”
- Use LSP for “what does this mean?” and cross-file semantics

---

## 5) A Better Architecture for CodeCanvas (Conceptual Decomposition)

If we want “blazing fast” and correct, CodeCanvas should treat indexing as a long-lived service, not a one-shot parse.

### 5.1 Proposed new core layers

**(A) Workspace / project model**

- detects workspaces (root(s), language configs)
- enumerates source files (already done in `Parser.parse_directory`)

**(B) Document store**

- owns file content snapshots and versions
- supports incremental updates (future: if used interactively)
- provides stable “file id” mapping (similar to Zed’s `file_index` mapping)

**(C) Syntax index (fast, local)**

- produces symbols (module/class/func) + ranges
- produces approximate call edges cheaply:
  - Tree-sitter if available
  - regex fallback
- can run fully offline and fast

**(D) LSP semantic index (slow, external, cached)**

- persistent per-language per-workspace server sessions
- can provide:
  - documentSymbols (if syntax index not available for that language)
  - call hierarchy (budgeted)
  - implementations / definitions / references (on demand)

**(E) Graph builder**

- merges syntax edges + semantic edges into a single `Graph`
- supports incremental rebuilds and caching

**(F) Analyzer / Views**

- keep mostly unchanged: they consume `Graph`

### 5.2 Two-phase graph building (strong recommendation)

Phase 1: Fast graph

- modules/classes/functions via syntax index
- imports via naive/regex
- calls via naive inference

Phase 2: Optional refinement

- call hierarchy only for:
  - “focus” node neighborhood
  - or nodes with ambiguous call targets
  - or top-K central functions

This aligns with “make it feel instant, then enrich”.

---

## 6) Concrete Design Notes for a CodeCanvas LSP Session Manager

### 6.1 API shape (sketch)

- `LspSessionManager.get(lang, workspace_root) -> LspSession`
- `LspSession.ensure_open(uri, text, version)`
- `LspSession.document_symbols(uri)`
- `LspSession.call_hierarchy_outgoing(uri, position)` (budgeted)
- `LspSession.shutdown()`

### 6.2 Key behaviors

- Start server once; keep process running.
- Always drain stderr.
- Serialize outbound messages (avoid interleaving).
- Track pending requests and allow cancellation.
- Use a bounded concurrency semaphore per server.

### 6.3 Caching

Cache at least:

- `document_symbols(uri, mtime/hash)`
- call hierarchy results per function signature/range

Invalidation:

- if file content changes (mtime/hash)
- if server restarts

### 6.4 Request budgets

Hard limits to prevent runaway:

- `max_call_hierarchy_requests_total`
- `max_call_hierarchy_requests_per_file`
- `timeout_call_hierarchy_seconds`

---

## 7) Tree-sitter Integration (Optional, but Likely the Best Long-Term Path)

Why:

- Tree-sitter incremental parsing can supply symbols/outline quickly.
- Query-based extraction can drive features without round-tripping to LSP.
- LSP becomes a semantic augmenter instead of the primary parser.

Suggested approach:

- Add a lightweight “syntax extractor” that:
  - identifies function boundaries
  - identifies call expressions + callee names
  - identifies imports

Then only ask LSP for:

- resolving callee → definition target when needed
- cross-file symbol linking

This mirrors Zed’s philosophy.

---

## 8) Performance Measurement (Don’t Fly Blind)

Add basic instrumentation counters/timers:

- per language server:
  - spawn time
  - initialize time
  - request count by method
  - p50/p95 request latency by method
- per parse run:
  - total parse time
  - number of files
  - cache hit rate
  - number of call hierarchy requests

Success criteria (example targets):

- “init” on medium repo: usable architecture view in seconds, not minutes.
- “impact” request: always fast (graph traversal only).
- LSP refinement: time-boxed and cancellable.

---

## 9) Known Pitfalls / Gotchas

- Language servers differ wildly in semantics and required init options.
- Some servers require `didOpen` *and* `didChange` consistency.
- URI handling (Windows vs WSL paths) must be robust.
- LSP positions are typically UTF-16; conversion correctness matters.
- A persistent server needs robust crash recovery + restart logic.
- Don’t build a full call graph eagerly if you only need local neighborhoods.

---

## 10) Immediate Next Steps (After Context Compression)

When we come back “post compression”, do this in order:

1. Re-open the anchors:
   - `codecanvas/server.py`
   - `codecanvas/parser/main.py`
   - `codecanvas/parser/lsp.py`
   - `codecanvas/core/analysis.py`
2. Confirm LSP latency multipliers:
   - per-file subprocess spawn
   - call hierarchy in parse loop
   - stderr not drained
3. Implement minimal fixes first:
   - drain stderr
   - persistent LSP sessions
   - correct workspace root
   - defer call hierarchy
4. Validate with a benchmark repo and record timings.
