## LocAgent MCP Server Extraction Plan

### Overview
Extract LocAgent's core backend and tools into an MCP (Model Context Protocol) server to expose its code localization capabilities as a standardized tool for Claude Code with haiku 4.5. The MCP server will wrap the existing LocAgent backend without modifying its fundamental implementation.

### Architecture

**Core Components to Extract:**

1. **Backend Layer** (from `dependency_graph/` and `plugins/location_tools/`)
   - `build_graph.py` - Parse Python codebases into networkx dependency graphs
   - `traverse_graph.py` - RepoEntitySearcher & RepoDependencySearcher classes for graph traversal
   - Graph construction (AST analysis, import resolution, call graph building)

2. **Tool Functions Layer** (from `plugins/location_tools/repo_ops/repo_ops.py`)
   - `search_entity()` - Find entities (files, classes, functions) in the dependency graph
   - `explore_graph_structure()` - Traverse graph relationships (upstream/downstream, hops)
   - `get_code_block_by_line_nums()` - Extract source code snippets
   - `bm25_module_retrieve()` - BM25-based module retrieval
   - `bm25_content_retrieve()` - BM25-based code snippet retrieval
   - Entity/function content extraction functions
   - Graph structure exploration tools

3. **State Management**
   - Global variables for current issue/repo context (CURRENT_ISSUE_ID, DP_GRAPH, DP_GRAPH_ENTITY_SEARCHER, etc.)
   - Functions: `set_current_issue()`, `reset_current_issue()`, `get_current_*()` accessors

4. **Retrieval Systems** (from `plugins/location_tools/retriever/`)
   - BM25 indexing and retrieval
   - Fuzzy matching for entity lookup
   - Module and code snippet retrievers

### MCP Server Structure

**New Directory Layout:**
```
locagent_mcp/
├── locagent_mcp/
│   ├── __init__.py
│   ├── server.py              # MCP server entry point
│   ├── handlers.py            # MCP tool handlers (wrap tool functions)
│   ├── context.py             # Global context/state management
│   └── tools/                 # Exported tools as MCP resources
│       ├── entity_search.py
│       ├── graph_exploration.py
│       ├── code_retrieval.py
│       └── code_snippet.py
├── locagent_core/             # Extracted from original repo
│   ├── dependency_graph/      # symlink or copy from locagent/dependency_graph/
│   ├── graph_backend/         # Refactored state management
│   └── retriever/             # Copy from locagent/plugins/location_tools/retriever/
├── pyproject.toml
├── requirements.txt
├── server.py                  # Executable entry point
└── README.md
```

### Implementation Steps

1. **Setup MCP Server Base**
   - Use openskills mcp-builder skill to scaffold MCP server structure
   - Create `server.py` as the MCP protocol handler using `mcp` library
   - Set up async tool registration with proper JSON-RPC handling

2. **Extract & Organize Code** (minimize changes to preserve baseline integrity)
   - Copy `locagent/dependency_graph/` → `locagent_core/dependency_graph/`
   - Copy `locagent/plugins/location_tools/retriever/` → `locagent_core/retriever/`
   - Extract core tools from `repo_ops.py` → `locagent_core/tools/`
   - Create wrapper in `context.py` for global state management
   - Preserve original function signatures and logic

3. **Implement MCP Tool Handlers**
   - Tool 1: `initialize_repo(repo_path)` - calls `set_current_issue()` with repo setup
   - Tool 2: `search_entity(query, entity_type)` - wraps `search_entity()`
   - Tool 3: `explore_graph(root, direction, hops)` - wraps `explore_graph_structure()`
   - Tool 4: `get_code_snippet(file_path, start_line, end_line)` - wraps `get_code_block_by_line_nums()`
   - Tool 5: `bm25_search(query, type)` - wraps BM25 retrievers
   - Tool 6: `get_entity_content(entity_names)` - wraps `get_entity_contents()`
   - Tool 7: `reset_repo()` - wraps `reset_current_issue()`

4. **Handle Dependencies**
   - Create `pyproject.toml` with dependencies from original `requirements.txt` (filtered)
   - Include: networkx, ast, tree-sitter, bm25s, datasets, litellm (optional for standalone)
   - Exclude: jupyter, azure-specific, training packages

5. **Configuration & Initialization**
   - Add env var handling for GRAPH_INDEX_DIR, BM25_INDEX_DIR
   - Auto-detect or pre-build graph indices on first repo initialization
   - Cache built graphs to avoid rebuilding

6. **Testing & Integration**
   - Verify each tool function works independently
   - Test MCP protocol compliance
   - Create simple test with claude code to verify tool availability

### Key Design Decisions

- **Zero Logic Changes**: Copy LocAgent code as-is to preserve baseline validity
- **State via Context**: Global state (current repo, graph) managed in `context.py` not module globals
- **Async-First**: All MCP handlers are async; wrap sync LocAgent calls with executors if needed
- **Tool Granularity**: Expose 5-7 focused tools rather than 40+ functions; users call larger workflows
- **Caching**: Graph indices and BM25 indexes cached to avoid expensive rebuilding
- **Error Handling**: Proper MCP error responses with meaningful messages

### Integration with Evaluation Harness

Once complete, the MCP server will be:
1. Started as a subprocess in the Claude Code harness
2. Available as a tool resource via MCP protocol
3. Used by haiku 4.5 model to answer code localization queries
4. Benchmarked against baseline 1 (text-only) and baseline 2 (existing LocAgent integration)

### Deliverables

1. `locagent_mcp/` - Complete MCP server package
2. `server.py` - Executable entry point
3. `pyproject.toml` + `requirements.txt` - Dependencies
4. `tests/test_mcp_tools.py` - Basic tool tests
5. Integration docs for Claude Code harness

### Effort & Complexity

- **Extraction**: Low (copy-paste with minimal refactoring)
- **MCP Wrapping**: Medium (5-7 tool handlers, async I/O handling)
- **Testing**: Medium (verify tool outputs match original behavior)
- **Total**: 2-3 hours of implementation work

