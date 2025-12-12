## Evaluation Plan for LocAgent MCP Re-implementation

### Current State
The `locagent/` directory contains a partially implemented MCP server extraction:
- **Working components**: `initialize_repo`, `get_code_snippet`, `reset_repo` (basic file I/O)
- **Placeholder components**: `search_entity`, `explore_graph`, `bm25_search`, `get_entity_content` (marked as ready for backend)
- **Structure**: Clean async API (`direct_api.py`), handlers (`handlers.py`), tool definitions

### Evaluation Objective
Verify that the LocAgent core functionality has been **properly extracted and repackaged as an MCP-ready service** by comparing against the original repository.

### Evaluation Steps

**Phase 1: Source Truth Setup**
1. Clone original LocAgent repo to `/mnt/d/Personal_Folders/Tocho/ain3sh/codecanvas/original_locagent/`
   - `git clone https://github.com/gersteinlab/LocAgent.git original_locagent`
2. Analyze original repo structure to identify:
   - Core backend modules (dependency graph construction, entity search, BM25 retrieval)
   - Tool implementations (what each tool should actually do)
   - Dependencies and configuration

**Phase 2: Completeness Check**
Compare current implementation against requirements:
- [ ] Backend extraction: Check if `dependency_graph/`, `plugins/location_tools/` code is properly referenced or integrated
- [ ] Tool coverage: Verify all 7 tools have proper implementations (not just stubs)
- [ ] State management: Confirm global state (repo context, graph indices) is properly managed
- [ ] Error handling: Check if errors from original code are properly wrapped
- [ ] Async compliance: Verify all handlers are properly async

**Phase 3: Implementation Fidelity**
Verify re-implementation preserves original logic:
- [ ] Function signatures match original tools
- [ ] Return types are consistent (dict with "success", "message", data)
- [ ] Graph traversal logic is intact (upstream/downstream, hop counts)
- [ ] BM25 retrieval maintains original ranking algorithm
- [ ] Entity search uses original matching logic (fuzzy, exact, regex)
- [ ] Code extraction preserves original line number handling

**Phase 4: Dependency Audit**
Check if all required dependencies are properly declared:
- [ ] `networkx` for graph operations
- [ ] `tree-sitter` for AST parsing
- [ ] `bm25s` for semantic search
- [ ] Any custom LocAgent utilities (graph builders, searchers)
- [ ] Python version compatibility (3.10+)

**Phase 5: Integration Readiness**
Verify the package can be used by Claude Code harness:
- [ ] `locagent.LocAgentAPI` is importable and instantiable
- [ ] `locagent.TOOLS` lists all 7 tools with proper JSON schemas
- [ ] Each tool is callable via `api.<tool_name>(...)` 
- [ ] Proper error responses for missing repo context
- [ ] No external API calls required (self-contained)

### Evaluation Criteria

**SUCCESS** = All of:
1. Original repo cloned and analyzed
2. 5+ of 7 tools fully functional (not placeholders)
3. Core backend modules properly integrated or referenced
4. No logic changes from original (functions do same thing)
5. Proper async/await usage throughout
6. MCP-ready (tool defs, proper schemas, error handling)

**PARTIAL** = 3-4 of above criteria met → identify gaps and create implementation tickets

**INCOMPLETE** = Fewer than 3 criteria met → major refactoring needed

### Output Deliverables
1. Side-by-side comparison doc: `evaluation_report.md`
   - What was extracted correctly ✓
   - What's missing/stubbed out
   - What needs integration
   - Priority fixes for functional baseline
2. List of implementation gaps (if any) with effort estimates
3. Recommendation: Ready for benchmark / Needs fixes / Major refactor