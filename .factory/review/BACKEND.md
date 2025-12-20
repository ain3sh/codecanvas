# CodeCanvas Backend (Architecture & Internals)

This document describes the **current** CodeCanvas backend: how it parses a repo into a dependency graph, renders multimodal PNG “maps”, persists an Evidence Board, and exposes everything as an MCP tool for agent UX.

## Doc Structure (why it’s organized this way)

1. **Anchor points**: the few files you should read first.
2. **End-to-end flows**: what happens for each `action` (the real runtime contract).
3. **Core data models**: `Graph` + `CanvasState` invariants.
4. **Sub-systems**: Parser (LSP + tree-sitter), LSP runtime/sessions, Call graph builder, Analyzer.
5. **Agent UX surface**: MCP tool + PNG views + Evidence Board semantics.
6. **Operational notes**: performance levers, concurrency, troubleshooting, extension points.

---

## 1) Anchor Points (start here)

If you only read a handful of files, read these in this order:

- `codecanvas/server.py`
  - The public synchronous API (`canvas_action`) and the MCP server wrapper.
  - Global graph lifecycle, state persistence, and call-graph background refinement.
- `codecanvas/parser/main.py`
  - Repo parsing into `Graph` nodes/edges.
  - LSP-first defs, tree-sitter fallback, and import-edge resolution.
- `codecanvas/parser/lsp_session.py` + `codecanvas/parser/lsp_runtime.py`
  - Persistent LSP sessions + background asyncio loop used from sync code.
  - Caching strategy and concurrency controls.
- `codecanvas/parser/call_graph.py`
  - CALL edge construction: tree-sitter callsites + LSP `textDocument/definition`.
- `codecanvas/core/models.py`
  - `GraphNode`, `GraphEdge`, `Graph` indexes/dedup.
- `codecanvas/core/state.py`
  - Evidence Board persistence (`results/canvas/state.json`), evidence/claim/decision models.
- `codecanvas/core/analysis.py`
  - Impact traversal over the graph (slices + neighborhood).
- `codecanvas/views/*`
  - The “frontend” is a set of SVG renderers rasterized to PNG.
  - `ArchitectureView`, `ImpactView`, `TaskView` (Evidence Board).

---

## 2) Mental Model: What CodeCanvas is doing

CodeCanvas is **not** a long-running web server. It’s a **synchronous tool API** that:

1. **Parses** a codebase into a compact graph (`Graph`).
2. **Analyzes** impact (blast radius / neighborhood) on that graph.
3. **Renders** PNG “maps” (architecture + impact + evidence board).
4. **Persists** a lightweight Evidence Board state file so an agent can iteratively make claims/decisions tied to evidence.
5. **Exposes** the above as a single MCP tool (`canvas`) that returns text + PNGs.

High-level pipeline:

```text
MCP tool call (canvas)
  └─> codecanvas.server.canvas_action(action=...)
        ├─ init: Parser -> Graph -> Analyzer -> ArchitectureView -> PNG
        │                 └─ (optional) CALL edges foreground + background refinement
        │                 └─ persist CanvasState (Evidence Board)
        ├─ impact: Analyzer -> neighborhood -> ImpactView -> PNG
        ├─ claim/decide/mark/skip/task_select: mutate CanvasState -> TaskView -> PNG
        ├─ status: TaskView -> PNG
        └─ read: text-only summary of state + telemetry
```

---

## 3) The Public Contract: `canvas_action` and `action`s

`codecanvas/server.py` exposes one synchronous function:

- `canvas_action(action=..., repo_path=..., use_lsp=..., symbol=..., text=..., kind=..., task_id=..., depth=..., max_nodes=...) -> CanvasResult`

`CanvasResult` contains:

- `text`: always present
- `images`: optional list of `{name, png_path, png_bytes}`

### Actions and their side-effects

#### `init`

Purpose: build the initial graph + architecture map and initialize the Evidence Board.

What happens:

1. Determine repo root and set `CANVAS_PROJECT_DIR`.
2. Clear any prior state file.
3. `Parser(use_lsp=use_lsp)` builds a `Graph` from `repo_path`.
4. `Analyzer(Graph)` is created.
5. If `use_lsp`:
   - Run a **fast** call-graph pass (foreground, tight budget).
   - Start a **background** call-graph refinement thread (larger budget).
6. Persist `CanvasState` with:
   - `parse_summary` (LSP vs fallback breakdown)
   - `symbol_files` mapping
   - initial architecture `Evidence` record
7. Render `ArchitectureView` to `results/canvas/architecture.png`.
8. Render `TaskView` (Evidence Board) to `results/canvas/task.png`.

Returns:

- `text`: “Initialized: … Created evidence E… Parse: … Call graph: …”
- `images`: `architecture`, `board`

#### `impact`

Purpose: produce a focused “blast radius” view for a symbol.

What happens:

1. Resolve the target node via `Analyzer.find_target(symbol)`.
2. Compute inbound/outbound slices (callers/callees and import relations).
3. Store an `AnalysisState` in `CanvasState.analyses` and set `CanvasState.focus`.
4. Extract a bounded k-hop neighborhood subgraph for visualization.
5. Render `ImpactView` to `results/canvas/impact_<node_id>.png`.
6. Add an `Evidence` record and re-render the board (`TaskView`).

Returns:

- `images`: `impact`, `board`

#### `claim` / `decide`

Purpose: attach agent-authored statements to evidence.

- `claim`: creates a `Claim` (`hypothesis|finding|question`)
- `decide`: creates a `Decision` (`plan|test|edit|mark|skip`, etc.)

Linking rule:

- If there is recent evidence for the current focus (`last_evidence_id_by_focus[focus]`), auto-link to it.
- Else link to the most recent evidence overall.

Returns:

- `images`: `board` (updated)

#### `mark` / `skip`

Purpose: update the active `AnalysisState` for the chosen symbol.

What happens:

- Resolve a node ID (ID match, analyzer match, exact label match).
- If it’s in the current analysis’ affected set, mark it as addressed or skipped.
- Add a `Decision` (`kind="mark"` or `kind="skip"`) linked to current evidence.
- Re-render the board.

Returns:

- `images`: `board`

#### `task_select`

Purpose: associate the session with a task from `tasks.yaml`.

- Loads `tasks.yaml` from `project_path` (optional file).
- Stores `active_task_id` in state.
- `TaskView` footer shows task metadata.

Returns:

- `images`: `board`

#### `status`

Purpose: a cheap “refresh” of the board with call-graph status reflected in the title.

Returns:

- `images`: `board`

#### `read`

Purpose: text-only state snapshot (for non-multimodal contexts).

Includes:

- initialization/focus/active task
- call graph status + last edge count (if present)
- parse backend breakdown (`parse_summary`)
- recent Evidence / Claims / Decisions

---

## 4) Core Data Models

### 4.1 `Graph` (`codecanvas/core/models.py`)

CodeCanvas keeps the graph intentionally small:

- **Nodes** (`GraphNode`)
  - `kind`: `module | class | func`
  - `id`: stable-ish hashed ID (see below)
  - `label`: human-facing name (module path, class name, or `Class.method`)
  - `fsPath`: absolute path to the defining file
  - `parent`: hierarchical parent (`func -> class/module`, `class -> module`)
  - `snippet`: source excerpt for display
  - `(start_line,start_char,end_line,end_char)`: definition range, used heavily by call-graph mapping

- **Edges** (`GraphEdge`)
  - `type`: `import | call`
  - `from_id`, `to_id`
  - `key()`: stable edge key used for dedup

Indexes maintained inside `Graph`:

- `_node_map[id] -> GraphNode` (O(1) lookup)
- `_edges_from[from_id] -> [GraphEdge]` (O(1) fanout)
- `_edges_to[to_id] -> [GraphEdge]` (O(1) fanin)
- `_edge_keys` for edge dedup

ID utilities:

- `make_module_id(path)` => `mod_<fnv1a(path)>`
- `make_class_id(file_label, class_name)` => `cls_<fnv1a(file_label)>_<class_name>`
- `make_func_id(file_label, func_name, line)` => `fn_<fnv1a(file_label)>_<func_name>_<line>`

Implications:

- Module IDs are stable for a given repo-relative path.
- Function IDs encode the start line, so edits that move definitions will change IDs.

### 4.2 `CanvasState` (`codecanvas/core/state.py`)

`CanvasState` is persisted to `results/canvas/state.json` and is the backbone of the Evidence Board.

Key fields:

- `project_path`: the repo root used for outputs + task loading
- `use_lsp`: whether graph reload should use LSP and spawn call-graph refinement
- `parse_summary`: persisted backend breakdown for transparency
- `analyses`: `{target_node_id: AnalysisState}` (currently used as a single active analysis)
- `focus`: current “context symbol” used for auto-linking evidence
- `active_task_id`: optional selection from `tasks.yaml`
- Evidence Board lists:
  - `evidence: [Evidence]` (points at on-disk PNG paths)
  - `claims: [Claim]`
  - `decisions: [Decision]`
- `last_evidence_id_by_focus`: focus/symbol -> last evidence ID (auto-linking)
- `symbol_files`: node ID -> fsPath (quick lookup)

Persistence model:

- Atomic-ish write: write `state.json.tmp` then rename.
- If load fails, rename the broken file to `state.json.bak`.

---

## 5) Parser Subsystem (LSP-first + tree-sitter fallback)

Entry: `codecanvas/parser/main.py`.

Design goals:

- Prefer **semantic** definitions via LSP when available.
- Always compute **local import edges** where possible.
- Fall back to deterministic tree-sitter for Python/TS when LSP is missing/flaky.
- Avoid regex-naive call inference (call edges are built separately via LSP definitions).

### 5.1 Directory scan + “known module labels”

`Parser.parse_directory(...)`:

1. Walks the directory with `os.walk`.
2. Prunes known “junk” directories (`.git`, `node_modules`, `venv`, `context`, etc.).
3. Collects candidate files by extension.
4. Builds `_known_module_labels`: normalized repo-relative paths of all candidate files.

Why this matters:

- Import edges are only added when they resolve to a file in `_known_module_labels`.
- This prevents graph bloat from stdlib/third-party imports and avoids edges to missing nodes.

### 5.2 Per-file parsing (`Parser._parse_file`)

Every candidate file gets a MODULE node:

- `id = make_module_id(<normalized repo-relative path>)`
- `label = <normalized repo-relative path>`

Language detection:

- `detect_language(path)` uses extension mapping in `codecanvas/parser/lsp.py`.
- `.cc`/`.hh` are normalized to `lang="c"`.
- Unknown extensions become `lang=<suffix>` (best-effort).

Non-LSP languages get *only* lightweight module import detection:

- C/C++: `#include` scanning (`_detect_includes_c`)
- shell: `source` / `.` scanning (`_detect_sources_sh`)
- R: `source("...")` scanning (`_detect_sources_r`)

Python/TypeScript specifically also get tree-sitter support (imports + defs fallback).

### 5.3 LSP defs path (preferred)

When `use_lsp=True` and the language has an installed server:

1. Choose a stable workspace root (`codecanvas/parser/workspace.py`).
2. Reuse a persistent session (`codecanvas/parser/lsp_session.py`).
3. Fetch `textDocument/documentSymbol`.
4. Convert the symbol tree into CLASS/FUNC nodes.

Important behavior:

- If the LSP returns `documentSymbol=[]`, it is treated as “success but no defs”, and tree-sitter fallback is not triggered.
- LSP failures are categorized and recorded into `ParseSummary.lsp_failures`.

### 5.4 Tree-sitter path (Python/TS)

Tree-sitter is used for two separate things:

1. **Imports (always)** for Python/TS: `import_specs_from_parsed(parsed)`
2. **Defs (fallback)** when LSP is not used/supported: `definitions_from_parsed(parsed)`

Implementation details (`codecanvas/parser/treesitter.py`):

- Thread-local parser cache keyed by language name (python/typescript/tsx/javascript).
- Compatibility with both `Parser.set_language(...)` and `parser.language = ...` APIs.
- Extraction is structural and intentionally shallow:
  - defs: top-level classes + top-level functions/methods (no nested defs)
  - calls: call-site positions (line/char), used by the call-graph builder

### 5.5 Import resolution rules (local-only)

Import specs are normalized into repo-relative file labels using `resolve_import_label(...)`:

- Python: dotted module -> `<path>.py`, relative dots are resolved against the importing file’s directory
- TypeScript: relative imports become `<path>.ts` by default, then are normalized to existing files

`Parser._add_import_edges(...)` only adds an edge if the final label is in `_known_module_labels`.

TS normalization tries (in order):

- `base.ts`, `base.tsx`, `base.js`, `base.jsx`
- `base/index.ts`, `base/index.tsx`, `base/index.js`, `base/index.jsx`

Python normalization:

- `pkg/module.py` can be rewritten to `pkg/module/__init__.py` if the latter exists.

---

## 6) LSP Subsystem (async servers used from sync code)

CodeCanvas’ public API is synchronous, but LSP servers are easiest to manage asynchronously.

### 6.1 Background runtime (`codecanvas/parser/lsp_runtime.py`)

- Starts a dedicated asyncio event loop in a daemon thread.
- Provides `run(coro, timeout=...)` as a sync bridge via `asyncio.run_coroutine_threadsafe`.

### 6.2 Persistent sessions (`codecanvas/parser/lsp_session.py`)

Sessions are keyed by:

- `(lang, workspace_root)`

Each `LspSession`:

- Lazily starts an `LSPClient` subprocess (`codecanvas/parser/lsp.py`).
- Uses an `asyncio.Semaphore` to cap in-flight requests.
- Caches:
  - `document_symbols` by file signature `(mtime_ns, size)`
  - `definition` results by `(file, line, char, file_signature)`
- Provides batched `definitions(...)` to avoid per-callsite `stat` and repeated setup.

`LspSessionManager`:

- Maintains up to `max_sessions` (default 8).
- Evicts sessions idle longer than `idle_ttl_s` (default 300s), then LRU if over cap.

### 6.3 LSP client details (`codecanvas/parser/lsp.py`)

- Uses JSON-RPC over stdio to subprocess-based language servers.
- Always ensures documents are opened via `textDocument/didOpen` before symbol/definition requests.
- Normalizes `textDocument/definition` responses (`Location | LocationLink`) into a list of `{uri, range}` dicts.

Configured servers (`LANGUAGE_SERVERS`):

- Python: `basedpyright-langserver --stdio`
- TS/JS: `typescript-language-server --stdio`
- plus go/rust/java/ruby/c/bash (defs via LSP may work, but tree-sitter fallback is currently only for py/ts).

---

## 7) Call Graph Subsystem (CALL edges)

CALL edges are built **after** the initial parse, in a separate pass:

- callsites: cheap syntactic enumeration via tree-sitter
- resolution: semantic binding via LSP `textDocument/definition`

### 7.1 Builder: `build_call_graph_edges(...)` (`codecanvas/parser/call_graph.py`)

Key properties:

- **Never mutates** the graph; it returns edges to add.
- Bounded by:
  - `time_budget_s`
  - `max_callsites_total`
  - `max_callsites_per_file`
- Supports early-cancel via `should_continue()` (used to stop stale background work).

Algorithm (per file):

1. Filter to `lang in {py, ts}` with installed LSP.
2. Read file text.
3. Extract callsites (`extract_call_sites`).
4. Map each callsite to a caller function using `FileSymbolIndex`:
   - Sort functions by start position, use `bisect` to find the most likely enclosing definition.
5. Batch-resolve definitions for callsites (`LspSession.definitions(...)`).
6. For each callsite, pick the first resolved location that maps to a known function node and add `CALL` edge.

Notes:

- This is intentionally conservative: if the callee can’t be mapped to a known function node, the edge is skipped.
- Edge dedup is performed at the builder level and again when inserting into the `Graph`.

### 7.2 Orchestration: foreground + background refinement (`codecanvas/server.py`)

On `init` (and on lazy reload), if `use_lsp=True`:

- Foreground pass:
  - small budgets (fast “good enough” call edges for early UX)
- Background pass:
  - larger budgets to fill in more edges

Concurrency + staleness control:

- `_call_graph_generation` is incremented whenever a new graph is built.
- The builder receives `should_continue=lambda: generation == _call_graph_generation`.
- Background results are only applied if they still match the current generation.

Telemetry:

- `_call_graph_status`: `idle|working|completed|error`
- `_call_graph_last`: `{edges: <call_edges_total>, duration_s: ...}`
- surfaced in `action=read` and included in init text.

---

## 8) Analysis Subsystem (Impact)

`codecanvas/core/analysis.py` owns graph traversal, not parsing.

Two primitives:

- `compute_slice(start_id, direction="in|out", include_imports=True, include_calls=True)`
  - BFS over incoming/outgoing edges
  - includes ancestors (`func -> class -> module`) so views keep context
- `neighborhood(node_id, hops, max_nodes)`
  - bounded k-hop neighborhood for rendering (hard-capped)

`Analyzer.analyze(target, depth)` returns `(inbound_slice, outbound_slice)`.

---

## 9) Views = “Frontend” (Agent UX)

There is no traditional web UI. The “frontend” is:

1. SVG renderers in `codecanvas/views/*`
2. rasterized to PNG via `CairoSVG`
3. returned as MCP `ImageContent` so multimodal models can see them

### 9.1 PNG generation

- Renderers return SVG strings.
- `save_png(svg, path)` writes PNG bytes to disk and returns bytes.
- PNGs are stored under: `<project_path>/results/canvas/`.

### 9.2 `ArchitectureView` (`codecanvas/views/architecture.py`)

Purpose: an overview of the module dependency structure.

- Builds a module-only graph (IMPORT edges).
- Condenses SCCs, layers components, clusters into “districts”.
- Renders up to 24 district cards and ~20 “highways” (strong edges).
- Optimized for glanceability over completeness.

### 9.3 `ImpactView` (`codecanvas/views/impact.py`)

Purpose: blast-radius visualization for a symbol.

- Uses an `Analyzer.neighborhood(...)` subgraph.
- Aggregates caller/callee edges and draws thicker lines for higher counts.
- Centers on the target with a snippet excerpt.

### 9.4 `TaskView` (Evidence Board) (`codecanvas/views/task.py`)

Purpose: persistent, agent-friendly working memory.

Board structure:

- CLAIMS: latest active claims
- EVIDENCE: recent evidence PNG thumbnails
- DECISIONS: recent decisions (mark/skip/plan/etc.)

Evidence thumbnails:

- The board embeds PNG thumbnails by reading the PNG file and converting to a data URL.
- This makes the “board PNG” self-contained and easy to view.

Task footer:

- If `tasks.yaml` exists, `TaskView` shows the selected task’s metadata in the footer.

---

## 10) MCP Integration (how agents call it)

`codecanvas/server.py` contains an MCP stdio server wrapper:

- Tool name: `canvas`
- Returns:
  - `TextContent` with the textual summary
  - `ImageContent` for each PNG returned by the action

This is the primary “agent UX” mechanism:

- The agent calls `canvas(action="init", repo_path=..., use_lsp=true)`
- Receives architecture + board images
- Iterates:
  - `impact` to generate evidence
  - `claim` / `decide` to record reasoning
  - `mark` / `skip` to track verification

---

## 11) Concurrency & Lifecycle

CodeCanvas uses in-process singletons:

- `_graph`, `_analyzer` in `codecanvas/server.py`
- LSP runtime thread + loop in `codecanvas/parser/lsp_runtime.py`
- LSP sessions cached globally in `codecanvas/parser/lsp_session.py`
- Call-graph refinement thread in `codecanvas/server.py`

Thread-safety:

- `_graph_lock` (RLock) guards graph reads/writes and analyzer access.
- Call-graph builder runs outside the lock, then acquires it briefly to apply edges.
- Generation gating prevents stale background updates from corrupting a new graph.

Lifecycle expectations:

- Best UX comes from repeated calls in the **same process**, so LSP sessions stay warm.
- If the process restarts, state is loaded from disk, but the graph is recomputed.

---

## 12) Performance Levers (what matters at scale)

- **Import edges are local-only**: avoids graph bloat from external dependencies.
- **Warm LSP sessions**: starting servers is the biggest fixed cost.
- **Cached `document_symbols` and `definition`** results keyed by `(mtime,size)`.
- **Batched definitions** per file to reduce per-callsite overhead.
- **Budgets everywhere**:
  - call graph time budgets and callsite caps
  - neighborhood node caps
- **Foreground + background refinement**: fast initial answers, then improve asynchronously.

If you need to tune speed vs accuracy, the main knob is `use_lsp` at `init`.

---

## 13) Extension Points (how to evolve this backend)

### Add/Improve language support

- LSP-only defs: add to `LANGUAGE_SERVERS` + extension mapping in `codecanvas/parser/lsp.py`.
- Tree-sitter fallback (py/ts pattern): extend `codecanvas/parser/treesitter.py` with language mapping + extraction.

### Add new edge types

1. Extend `EdgeType` in `codecanvas/core/models.py`.
2. Emit edges in `Parser` / call graph builder.
3. Update `Analyzer` traversal filters.
4. Update views to use/ignore the new type.

### Add new views

- Implement `render(...) -> svg_string` in `codecanvas/views/`.
- Call it from `codecanvas/server.py` and persist as new Evidence kind.

---

## 14) Troubleshooting (common failure modes)

### “Missing language server” / no LSP results

- Ensure the relevant server executable is on `PATH`:
  - `basedpyright-langserver`, `typescript-language-server`, etc.
- Check `action=read` → `lsp_fallbacks:` summary.

### Call graph stuck at `working`

- Background thread may still be running under its time budget.
- Use `action=read` to see `call_graph_status` and last edge count.
- A new `init` increments generation and cancels further work via `should_continue()`.

### “Impact is empty”

- For **function** targets, `ImpactView` is primarily driven by CALL edges; if the call graph hasn’t populated yet, the view can be sparse/empty.
- For **module** targets, IMPORT edges still provide structure.
- Allow a moment for background call-graph refinement, or trigger `status`/another action.

### `documentSymbol=[]` but you expected defs

- This is treated as success (no tree-sitter fallback) to avoid slow fallback loops on servers that legitimately return empty.
- If you need a stricter policy, change `_process_lsp_symbols` / fallback conditions in `Parser._parse_file`.
