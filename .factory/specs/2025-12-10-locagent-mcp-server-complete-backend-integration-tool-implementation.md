## Complete LocAgent MCP Server Implementation

### Current State Analysis
**Status:** 55% complete, NOT benchmark-ready
- ✅ 2/7 tools working: `initialize_repo`, `get_code_snippet`
- ❌ 5/7 tools are stubs: `search_entity`, `explore_graph`, `bm25_search`, `get_entity_content`, `reset_repo`
- ❌ Backend modules (dependency_graph, retriever) not integrated
- ❌ No graph building or BM25 search functionality

### Objective
Transform the current skeleton into a **fully functional MCP server** that:
1. Preserves original LocAgent algorithms (baseline validity)
2. Follows MCP best practices (workflow-oriented, context-optimized)
3. Enables Claude Code to perform graph-guided code localization
4. Achieves 100% tool coverage (7/7 functional)

---

## Phase 1: Backend Module Extraction (1-2 hours)

### 1.1 Create Backend Directory Structure
```
locagent/
├── backend/
│   ├── __init__.py                    # Export main classes
│   ├── dependency_graph/              # Copy from original
│   │   ├── __init__.py
│   │   ├── build_graph.py             # NetworkX graph builder
│   │   ├── traverse_graph.py          # RepoEntitySearcher, RepoDependencySearcher
│   │   └── constants.py               # NODE_TYPE_*, EDGE_TYPE_*
│   ├── retriever/                     # Copy from original
│   │   ├── __init__.py
│   │   ├── bm25_retriever.py          # BM25 ranking
│   │   └── fuzzy_retriever.py         # Fuzzy entity matching
│   └── utils/                         # Copy from original
│       ├── __init__.py
│       ├── result_format.py           # QueryInfo, QueryResult
│       └── util.py                    # Helper functions
```

### 1.2 Copy Strategy
**Copy WITHOUT modification** from `original_locagent/`:
- `dependency_graph/` → `locagent/backend/dependency_graph/`
- `plugins/location_tools/retriever/` → `locagent/backend/retriever/`
- `plugins/location_tools/utils/` → `locagent/backend/utils/`

**Fix imports only:**
```python
# Before: from dependency_graph import build_graph
# After:  from locagent.backend.dependency_graph import build_graph
```

### 1.3 Backend Exports
```python
# locagent/backend/__init__.py
from .dependency_graph import (
    build_graph,
    RepoEntitySearcher,
    RepoDependencySearcher,
    traverse_graph_structure,
    traverse_tree_structure,
    NODE_TYPE_FILE, NODE_TYPE_CLASS, NODE_TYPE_FUNCTION,
    EDGE_TYPE_CONTAINS
)
from .retriever.bm25_retriever import (
    build_code_retriever_from_repo,
    build_module_retriever_from_graph
)
from .retriever.fuzzy_retriever import fuzzy_retrieve_from_graph_nodes
from .utils.result_format import QueryInfo, QueryResult

__all__ = [
    'build_graph', 'RepoEntitySearcher', 'RepoDependencySearcher',
    'traverse_graph_structure', 'build_code_retriever_from_repo',
    'build_module_retriever_from_graph', 'fuzzy_retrieve_from_graph_nodes',
    'NODE_TYPE_FILE', 'NODE_TYPE_CLASS', 'NODE_TYPE_FUNCTION'
]
```

---

## Phase 2: Enhanced State Management (1 hour)

### 2.1 Global State Variables (handlers.py)
```python
# Enhanced global state
_current_repo_path: Optional[str] = None
_current_instance_id: Optional[str] = None

# Graph components
_dependency_graph: Optional[nx.MultiDiGraph] = None
_entity_searcher: Optional[RepoEntitySearcher] = None
_dependency_searcher: Optional[RepoDependencySearcher] = None

# BM25 retrievers
_bm25_module_retriever = None
_bm25_content_retriever = None

# Entity caches
_all_files: Optional[List[dict]] = None
_all_classes: Optional[List[dict]] = None
_all_functions: Optional[List[dict]] = None
```

### 2.2 Getter Functions
```python
def get_entity_searcher() -> Optional[RepoEntitySearcher]:
    return _entity_searcher

def get_dependency_searcher() -> Optional[RepoDependencySearcher]:
    return _dependency_searcher

def get_bm25_module_retriever():
    return _bm25_module_retriever

def get_bm25_content_retriever():
    return _bm25_content_retriever

def check_initialized() -> tuple[bool, str]:
    """Check if repo is initialized. Returns (is_ready, error_message)."""
    if not _current_repo_path:
        return False, "No repository initialized. Call initialize_repo() first."
    if not _entity_searcher:
        return False, "Graph not built. Try re-initializing the repository."
    return True, ""
```

---

## Phase 3: Implement handle_initialize_repo() (30 min)

### 3.1 Full Implementation
```python
async def handle_initialize_repo(repo_path: str, instance_id: Optional[str] = None) -> dict:
    """Initialize repository with full graph building and BM25 indexing."""
    global _current_repo_path, _current_instance_id
    global _dependency_graph, _entity_searcher, _dependency_searcher
    global _bm25_module_retriever, _bm25_content_retriever
    global _all_files, _all_classes, _all_functions
    
    try:
        if not os.path.isdir(repo_path):
            return {"success": False, "error": f"Repository path does not exist: {repo_path}"}
        
        logger.info(f"Initializing repository: {repo_path}")
        _current_repo_path = repo_path
        _current_instance_id = instance_id or os.path.basename(repo_path)
        
        # Build dependency graph (may take 10-60 seconds)
        logger.info("Building dependency graph...")
        _dependency_graph = await asyncio.to_thread(build_graph, repo_path)
        
        # Create searchers
        _entity_searcher = RepoEntitySearcher(_dependency_graph)
        _dependency_searcher = RepoDependencySearcher(_dependency_graph)
        
        # Cache entity lists
        _all_files = _entity_searcher.get_all_nodes_by_type(NODE_TYPE_FILE)
        _all_classes = _entity_searcher.get_all_nodes_by_type(NODE_TYPE_CLASS)
        _all_functions = _entity_searcher.get_all_nodes_by_type(NODE_TYPE_FUNCTION)
        
        # Build BM25 indices (may take 10-30 seconds)
        logger.info("Building BM25 indices...")
        _bm25_module_retriever = await asyncio.to_thread(
            build_module_retriever_from_graph, _dependency_graph
        )
        _bm25_content_retriever = await asyncio.to_thread(
            build_code_retriever_from_repo, repo_path
        )
        
        logger.info(f"Repository initialized successfully")
        
        return {
            "success": True,
            "message": f"Repository '{_current_instance_id}' initialized successfully",
            "instance_id": _current_instance_id,
            "repo_path": repo_path,
            "stats": {
                "nodes": len(_dependency_graph.nodes()),
                "edges": len(_dependency_graph.edges()),
                "files": len(_all_files),
                "classes": len(_all_classes),
                "functions": len(_all_functions)
            }
        }
    except Exception as e:
        logger.error(f"Error initializing repo: {e}", exc_info=True)
        # Reset state on error
        _current_repo_path = None
        _dependency_graph = None
        return {"success": False, "error": f"Initialization failed: {str(e)}"}
```

---

## Phase 4: Implement Core Tools (2-3 hours)

### 4.1 handle_search_entity() - Workflow-Oriented
**Purpose:** Find entities matching a query (files, classes, functions)

```python
async def handle_search_entity(query: str, entity_type: Optional[str] = None) -> dict:
    """Search for entities using fuzzy matching and graph lookups."""
    is_ready, error_msg = check_initialized()
    if not is_ready:
        return {"success": False, "error": error_msg}
    
    try:
        searcher = get_entity_searcher()
        
        # Map entity_type to node types
        node_type_filter = None
        if entity_type == "file":
            node_type_filter = NODE_TYPE_FILE
        elif entity_type == "class":
            node_type_filter = NODE_TYPE_CLASS
        elif entity_type == "function":
            node_type_filter = NODE_TYPE_FUNCTION
        
        # Use fuzzy retrieval from original LocAgent
        results = await asyncio.to_thread(
            fuzzy_retrieve_from_graph_nodes,
            searcher._graph,  # Access internal graph
            query,
            node_type_filter=node_type_filter
        )
        
        # Format results for agent consumption
        formatted_results = []
        for result in results[:20]:  # Limit to top 20
            formatted_results.append({
                "name": result.get("name", ""),
                "type": result.get("type", ""),
                "file": result.get("file_path", ""),
                "line_range": f"{result.get('start_line', 0)}-{result.get('end_line', 0)}"
            })
        
        return {
            "success": True,
            "query": query,
            "entity_type": entity_type or "all",
            "results": formatted_results,
            "count": len(formatted_results),
            "total_matches": len(results)
        }
    except Exception as e:
        logger.error(f"Error searching entity: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
```

### 4.2 handle_explore_graph() - Graph Traversal
**Purpose:** Explore dependencies (callers/callees) from a root entity

```python
async def handle_explore_graph(
    root_entity: str, 
    direction: str = "downstream", 
    hops: int = 2
) -> dict:
    """Explore code dependencies using graph traversal."""
    is_ready, error_msg = check_initialized()
    if not is_ready:
        return {"success": False, "error": error_msg}
    
    try:
        # Use original LocAgent's traverse_graph_structure
        result_str = await asyncio.to_thread(
            traverse_graph_structure,
            _dependency_graph,
            start_entities=[root_entity],
            direction=direction,
            traversal_depth=hops
        )
        
        # Parse result string into structured format
        # (Original returns formatted string, convert to dict for JSON)
        return {
            "success": True,
            "root": root_entity,
            "direction": direction,
            "hops": hops,
            "graph": result_str,  # Keep as formatted string for readability
            "note": "Use this to understand which code depends on (upstream) or is used by (downstream) the root entity"
        }
    except Exception as e:
        logger.error(f"Error exploring graph: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "suggestion": "Try using search_entity first to find valid entity names"
        }
```

### 4.3 handle_bm25_search() - Semantic Search
**Purpose:** Semantic/keyword search using BM25 ranking

```python
async def handle_bm25_search(
    query: str, 
    search_type: str = "content", 
    k: int = 5
) -> dict:
    """Search code using BM25 ranking."""
    is_ready, error_msg = check_initialized()
    if not is_ready:
        return {"success": False, "error": error_msg}
    
    try:
        if search_type == "module":
            retriever = get_bm25_module_retriever()
        elif search_type == "content":
            retriever = get_bm25_content_retriever()
        else:
            return {"success": False, "error": f"Invalid search_type: {search_type}. Use 'module' or 'content'."}
        
        if not retriever:
            return {"success": False, "error": "BM25 indices not built. Try re-initializing."}
        
        # Perform BM25 retrieval
        results = await asyncio.to_thread(retriever.retrieve, query, k=min(k, 20))
        
        # Format results
        formatted_results = []
        for result in results:
            formatted_results.append({
                "score": result.get("score", 0.0),
                "content": result.get("content", "")[:500],  # Truncate for context
                "file": result.get("file", ""),
                "line_range": result.get("line_range", "")
            })
        
        return {
            "success": True,
            "query": query,
            "search_type": search_type,
            "results": formatted_results,
            "count": len(formatted_results)
        }
    except Exception as e:
        logger.error(f"Error in BM25 search: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
```

### 4.4 handle_get_entity_content() - Content Retrieval
**Purpose:** Get full source code of specific entities

```python
async def handle_get_entity_content(entity_names: List[str]) -> dict:
    """Retrieve full source code for specified entities."""
    is_ready, error_msg = check_initialized()
    if not is_ready:
        return {"success": False, "error": error_msg}
    
    try:
        searcher = get_entity_searcher()
        
        # Get node data with code content
        results = await asyncio.to_thread(
            searcher.get_node_data,
            entity_names,
            return_code_content=True
        )
        
        # Format results
        formatted_results = {}
        for result in results:
            if result:
                entity_name = result.get('name', 'unknown')
                formatted_results[entity_name] = {
                    'type': result.get('type'),
                    'file': result.get('file_path', ''),
                    'line_range': f"{result.get('start_line', 0)}-{result.get('end_line', 0)}",
                    'code': result.get('code_content', '')
                }
        
        return {
            "success": True,
            "entities": entity_names,
            "results": formatted_results,
            "count": len(formatted_results)
        }
    except Exception as e:
        logger.error(f"Error getting entity content: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
```

### 4.5 handle_reset_repo() - Cleanup
**Purpose:** Reset repository context and free memory

```python
async def handle_reset_repo() -> dict:
    """Reset repository context and clean up resources."""
    global _current_repo_path, _current_instance_id
    global _dependency_graph, _entity_searcher, _dependency_searcher
    global _bm25_module_retriever, _bm25_content_retriever
    global _all_files, _all_classes, _all_functions
    
    try:
        _current_repo_path = None
        _current_instance_id = None
        _dependency_graph = None
        _entity_searcher = None
        _dependency_searcher = None
        _bm25_module_retriever = None
        _bm25_content_retriever = None
        _all_files = None
        _all_classes = None
        _all_functions = None
        
        logger.info("Repository context reset")
        
        return {
            "success": True,
            "message": "Repository context reset successfully"
        }
    except Exception as e:
        logger.error(f"Error resetting repo: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
```

---

## Phase 5: MCP Best Practices Application (30 min)

### 5.1 Update Tool Definitions (TOOLS array)
Add comprehensive descriptions following mcp-builder guidelines:

```python
{
    "name": "search_entity",
    "description": "Search for code entities (files, classes, functions) by name or pattern. Use fuzzy matching to find entities even with partial or imprecise queries. Returns top matching entities with location info.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search term or pattern (e.g., 'MyClass', 'calculate_', 'helper'). Supports fuzzy matching."
            },
            "entity_type": {
                "type": "string",
                "enum": ["file", "class", "function"],
                "description": "Filter by entity type. Omit to search all types."
            }
        },
        "required": ["query"]
    }
}
```

### 5.2 Error Message Guidelines
All error responses should:
- Suggest next steps (e.g., "Try calling initialize_repo() first")
- Provide context (e.g., "Graph not initialized" vs generic "Error")
- Be actionable (e.g., "Use search_entity to find valid entity names")

### 5.3 Response Optimization
- Return structured JSON (not formatted strings)
- Limit results to top 20 items (context budget)
- Truncate long code snippets to 500 chars with indication
- Include `count` and `total_matches` for pagination awareness

---

## Phase 6: Testing & Validation (1 hour)

### 6.1 Unit Tests
```python
# tests/test_handlers.py
async def test_full_workflow():
    api = LocAgentAPI()
    
    # Initialize
    result = await api.initialize_repo("/path/to/sample/repo")
    assert result["success"]
    assert result["stats"]["files"] > 0
    
    # Search entity
    result = await api.search_entity("MyClass", entity_type="class")
    assert result["success"]
    
    # Explore graph
    if result["count"] > 0:
        entity_name = result["results"][0]["name"]
        result = await api.explore_graph(entity_name, direction="downstream", hops=2)
        assert result["success"]
    
    # BM25 search
    result = await api.bm25_search("calculate sum", search_type="content", k=5)
    assert result["success"]
    
    # Get code snippet
    result = await api.get_code_snippet("README.md", 1, 10)
    assert result["success"]
    
    # Reset
    result = await api.reset_repo()
    assert result["success"]
```

### 6.2 Integration Test with Sample Repo
Test on a real Python repository (e.g., `requests`, small OSS project):
1. Initialize repo
2. Search for entities
3. Explore dependencies
4. Verify results match expected behavior

---

## Success Criteria

✅ **Phase 1:** Backend modules copied, imports working  
✅ **Phase 2:** State management enhanced  
✅ **Phase 3:** initialize_repo builds graph and BM25 indices  
✅ **Phase 4:** All 7 tools functional (not stubs)  
✅ **Phase 5:** Tool descriptions comprehensive, errors actionable  
✅ **Phase 6:** Tests pass, sample repo works  

**Final State:**
- 7/7 tools functional (100%)
- Original LocAgent algorithms preserved
- MCP best practices followed
- Benchmark-ready for Claude Code evaluation

---

## Estimated Timeline

| Phase | Task | Time |
|-------|------|------|
| 1 | Backend extraction | 1-2h |
| 2 | State management | 30m |
| 3 | initialize_repo | 30m |
| 4 | Core tools (5 handlers) | 2-3h |
| 5 | MCP best practices | 30m |
| 6 | Testing | 1h |
| **Total** | | **5.5-7.5 hours** |

---

## Key Design Decisions

1. **Preserve Original Code:** Copy backend modules WITHOUT modification (baseline validity)
2. **Async Wrappers:** Use `asyncio.to_thread()` for sync operations (graph building, BM25)
3. **Structured Responses:** Return JSON dicts, not formatted strings (agent-friendly)
4. **Context Optimization:** Limit results, truncate long content (token budget)
5. **Error Guidance:** All errors suggest next steps (agent learning)
6. **Workflow Focus:** Tools enable complete tasks, not just API calls

This implementation transforms the 55% skeleton into a 100% functional MCP server ready for TerminalBench evaluation.