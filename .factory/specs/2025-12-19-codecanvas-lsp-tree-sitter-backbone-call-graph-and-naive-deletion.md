# Goal
Make CodeCanvas **LSP-first by default**, use **tree-sitter as the universal fallback**, migrate **import + call graph derivation** off regex-naive logic, and reach a point where `codecanvas/parser/naive.py` can be deleted entirely without loss of language coverage.

# Constraints / Product Decisions (confirmed)
- **Tree-sitter is a required runtime dependency** (not an optional extra).
- **Init is two-tier**: return fast with an initial graph, then continue refining edges in the background when the server process stays alive.
- **Fallback policy**: silently fall back (LSP → tree-sitter), but **surface transparency** to the agent (“this portion is tree-sitter-derived and may be less accurate than LSP”).

# What the MCP spec implies for “background work”
From the MCP 2025-11-25 docs:
- MCP is transport-agnostic JSON-RPC; a server is just a process. Nothing forbids internal background threads/tasks.
- On **stdio transport**, servers **must not write non-MCP output to stdout**; background work must log to **stderr** or be silent.
- MCP also introduces **experimental protocol-level Tasks** (`tasks/*`) to represent long-running operations with polling and optional `notifications/progress`. This is requestor-driven and requires negotiated `tasks` capabilities. It’s useful if we want “formal” async jobs, but it’s not required to simply run internal background refinement.

**Conclusion for CodeCanvas:** implement the two-tier init as **internal background refinement** (works for a persistent MCP server), and optionally later add MCP `tasks` capability if/when the Python SDK and host support it cleanly.

# Current state (important for the plan)
- `Parser(use_lsp=...)` still defaults `False` and still uses regex-naive for imports + calls.
- LSP currently provides **document symbols only** (no definition/callHierarchy methods).
- Call edges are currently derived by `infer_calls(...)` (regex-based) after parsing.
- The “2 files LSP failed on CodeCanvas itself” were `__init__.py` files where LSP returns **no symbols**; today we treat “no symbols” as a failure and fall back.

# Target architecture
## 1) Parsing backends
Introduce an explicit internal backend layering per file:
1. **LSP backend (preferred)**
   - `textDocument/documentSymbol` to build MODULE/CLASS/FUNC nodes (+ ranges)
   - Optional semantic resolution for calls via `textDocument/definition` (added back)
2. **Tree-sitter backend (always available fallback)**
   - Extract MODULE/CLASS/FUNC nodes (+ ranges) from the AST
   - Extract import edges from AST
   - Extract call sites from AST (positions)

Regex-naive is removed.

## 2) Data needed for professional call graph
To map “a definition location” back onto a function node we need ranges.
- Extend `GraphNode` to include optional `start_line`, `end_line`, `start_char`, `end_char` (kept optional to avoid breaking views).
- Maintain a per-file index (`FileSymbolIndex`) mapping file → sorted ranges → node IDs.

## 3) Call graph derivation (two-layer)
### A. Call-site enumeration: tree-sitter
For each file:
- Find call expressions and their **cursor position** (line/col) and enclosing function.

### B. Semantic resolution: LSP `textDocument/definition`
For each call-site position:
- Ask LSP for definition.
- If we get a location in a file we know, map it to a function node via `FileSymbolIndex`.
- Add `EdgeType.CALL` caller → callee.

### C. When LSP resolution is unavailable
- Still keep the graph usable: imports + symbols + zero/partial calls.
- Transparently report that call edges are incomplete and which backend was used.

# Execution plan (a → b → c → delete naive)

## (a) Switch defaults to LSP-first
Changes:
- `Parser.__init__(use_lsp: bool = True)`.
- `canvas_action(..., use_lsp: bool = True)` and MCP tool schema default to `true`.
- Keep the flag so callers can force tree-sitter-only for benchmarking or deterministic tests.

Acceptance:
- `canvas_action(init)` uses LSP when available.
- If a language server binary is missing, we do not repeatedly attempt per-file (see (b)).

## (b) Make LSP backbone robust + observable
### Fix false negatives
- Treat **“documentSymbol returns []” as success** (module-only parse) — do not fall back.

### Avoid repeated expensive failures
Add a small “LSP availability cache” per (lang, workspace):
- Pre-check `cmd[0]` via `shutil.which` (or equivalent) once.
- If startup fails, memoize “disabled” for that session so we stop trying per file.

### Surface why fallback happened
Extend `ParseSummary` with:
- `tree_sitter_files` count
- `lsp_failures` dict counters: `missing_server`, `timeout`, `protocol_error`, `no_support`, `unknown`
- `fallback_samples` (bounded list) with `{file, reason}`

Plumb into:
- `init` result text: “LSP X files, tree-sitter Y files; fallbacks: …”
- `read/status` output (so the agent can see whether call graph is still refining)

Acceptance:
- CodeCanvas self-parse no longer “fails LSP” on `__init__.py`.
- A repo without e.g. `typescript-language-server` doesn’t thrash; it cleanly falls back to tree-sitter for TS.

## (c) Replace call graph derivation (LSP + tree-sitter)
### 1) Add tree-sitter extractor module
Create `codecanvas/parser/treesitter.py` (name flexible) that provides:
- `extract_definitions(text, lang) -> classes/functions with ranges/names`
- `extract_imports(text, lang) -> import specs (plus resolver to local file labels)`
- `extract_call_sites(text, lang) -> call positions + enclosing function`

Implementation detail:
- Use `tree_sitter_language_pack.get_language(...)` and cache parsers per language.
- Store per-language query strings (SCM) under a small `codecanvas/parser/queries/` package-data directory (mirroring the existing locagent approach).

### 2) Re-add minimal LSP “definition” support
Extend `LSPClient` with:
- `definition(file_path_or_uri, line, char) -> locations` (support `Location` + `LocationLink`).

Add caching in `LspSession`:
- `definition_cache[(uri, line, char, file_sig)]` to avoid re-querying.

### 3) Build call edges incrementally
Add a `CallGraphBuilder`:
- Input: graph + file list + symbol index + LSP session manager + tree-sitter extractor.
- Output: a list of `GraphEdge(CALL)` plus stats.
- Concurrency: bounded (e.g. 4) to keep LSP stable.
- Budgets:
  - per-file max callsites
  - global max callsites per second
  - time budget for “foreground init” vs “background refinement”

### 4) Two-tier init behavior
On `init`:
1. Foreground (fast): build module/class/func nodes + import edges.
2. Kick off background refinement:
   - In MCP server process, start an `asyncio.Task` (preferred) or a background thread.
   - Ensure no stdout writes; log only to stderr if needed.
   - Periodically merge results into `_graph` under a lock and rebuild indexes.

Expose status:
- `read` (and/or `status`) includes: `call_graph_status = idle|working|completed`, counts, and backend breakdown.

Feasibility notes:
- Works well when the server process is persistent (MCP stdio server).
- If CodeCanvas is invoked as a one-shot Python call and the process exits immediately, background refinement won’t finish; we can optionally add a `full_init=true` mode later.

Acceptance:
- `impact` gets better over time without requiring the agent to request “rebuild call graph”.
- No races/crashes: graph reads/writes are protected.

## Ready-to-delete naive (finalization)
Once tree-sitter covers Python/TS imports + definitions + call sites:
- Delete `codecanvas/parser/naive.py`.
- Remove all `NaiveParser`, `infer_calls`, and `_FuncDef` plumbing.
- Update tests:
  - Existing import-edge tests should pass using tree-sitter import extraction.
  - Add at least one call-edge test using tree-sitter call-site extraction + (optional) LSP definition resolution.

# Validation plan
- `uv run ruff check codecanvas`
- `uv run pytest codecanvas/tests`
- Add a regression test for the prior “__init__.py causes LSP fallback” bug.

# Rollout / risk mitigation
- Keep `use_lsp` flag for now (default True) to allow emergency forcing tree-sitter-only.
- Keep call-graph refinement budgeted + cancellable internally.
- Always annotate tool output with backend provenance when any tree-sitter fallback happened.

# Deliverables (files likely to change)
- `codecanvas/parser/main.py` (new default, new pipeline, remove naive)
- `codecanvas/parser/lsp.py` (add `definition`)
- `codecanvas/parser/lsp_session.py` (definition cache)
- `codecanvas/parser/treesitter.py` + `codecanvas/parser/queries/*` (new)
- `codecanvas/server.py` (default use_lsp=True; background refinement orchestration; status text)
- `pyproject.toml` (move tree-sitter deps into required dependencies)
- `codecanvas/tests/*` (update/extend for tree-sitter + fallback behavior)

If you approve this spec, I’ll implement it in the same (a→b→c) order, keeping the system continuously runnable and validators green after each major step.