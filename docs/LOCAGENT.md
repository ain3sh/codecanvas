# LocAgent MCP: Graph-Guided Code Localization for LLM Agents

## Overview

This document provides comprehensive documentation of the **LocAgent MCP** implementation, which serves as the second baseline in our evaluation framework for comparing code navigation approaches. LocAgent represents a **graph-based code localization** paradigm that leverages dependency graphs to help LLM agents navigate and understand codebases.

**Baselines in our evaluation:**
1. **Text-only (no MCP)** - Agent uses only file reads, grep, and basic tools
2. **CodeGraph (LocAgent MCP)** - Graph-guided navigation with dependency traversal
3. **CodeCanvas MCP** - Our approach (visualization-first code understanding)

---

## Original Research

### Paper Reference
- **Title:** LocAgent: Graph-Guided LLM Agents for Code Localization
- **Authors:** Zhaoling Chen et al.
- **ArXiv:** https://arxiv.org/html/2503.09089v2
- **Published:** 2025

### Core Contribution
The paper introduces a **hierarchical code entity graph** that enables LLM agents to:
1. Navigate code structure systematically (not just text search)
2. Understand call relationships before making changes
3. Perform two-stage localization: coarse (file) → fine (function/class)
4. Combine graph structure with semantic search for comprehensive code discovery

### Key Insight
> "LLM agents struggle with code localization because they lack structural understanding of how code entities relate. By providing a dependency graph, agents can traverse relationships (who calls what, who inherits from whom) rather than relying solely on keyword matching."

---

## MCP Extraction

### From Agent Framework to Tool Suite
The original LocAgent implementation was a **complete agent harness** (`auto_search_main.py`) that orchestrated:
- Graph construction
- Multi-step localization loops
- LLM prompting with graph context
- Result aggregation

**Our extraction** isolated the **core primitives** (tools) that provide structural code navigation, repackaging them as a standalone **MCP (Model Context Protocol) server**. This allows any LLM agent (Claude, GPT, etc.) to leverage the same graph-guided navigation without being locked into the original agent framework.

### What We Preserved
- Dependency graph construction (Tree-sitter based)
- Graph traversal algorithms (BFS with depth control)
- BM25 semantic code search
- Fuzzy entity name matching
- Code snippet retrieval with line numbers

### What We Changed
- Removed agent loop logic (let the calling agent decide strategy)
- Added MCP protocol wrapper with clean tool definitions
- Implemented caching for graphs and indexes (`~/.cache/locagent/`)
- Simplified state management for single-repo focus
- Enhanced tool descriptions for agent self-discovery

### Experimental Validity & Baseline Fairness

#### Why Re-packaging Was Necessary

The original LocAgent implementation is a **complete agent harness**—it includes its own LLM orchestration loop, prompt templates, and multi-step reasoning logic. Using their full harness would be **invalid experimental design** because:

1. **Harness confounding:** Differences in performance could stem from their agent loop implementation, prompt engineering, or orchestration strategy—not from the graph-based tools themselves.

2. **Inconsistent comparison:** Our three experimental conditions must share the same agent harness:
   - **Text-only baseline:** Claude Code agent, no MCP tools
   - **CodeGraph baseline:** Claude Code agent + LocAgent tools (via MCP)
   - **CodeCanvas experiment:** Claude Code agent + CodeCanvas tools (via MCP)

   By extracting LocAgent's tools into MCP and running them under Claude Code, we isolate the **tool-level contribution** (graph-guided navigation) from harness-level variables.

3. **The tools ARE the contribution:** LocAgent's research contribution is the insight that dependency graphs help agents navigate code. Their specific agent loop is incidental. By preserving the exact graph construction, traversal algorithms, and search mechanisms, we preserve what makes LocAgent scientifically novel.

#### Agent-Facing Adaptations

We made two cosmetic adaptations to help agents effectively use the tools:

**1. Renamed MCP server from `locagent` to `codegraph`**

The internal module remains `locagent/`, but the agent-visible server name is `codegraph`. This change is purely semantic—the name "codegraph" provides stronger intuitive signal about the tool's purpose (navigating a code dependency graph) than the opaque project name "locagent."

This does not affect baseline validity because:
- Tool functionality is identical
- If anything, a clearer name *helps* LocAgent's performance by reducing agent confusion
- The original paper's agents also received descriptive context about tool purposes

**2. Added `USAGE.md` quick-reference documentation**

We added a concise guide (`locagent/USAGE.md`) showing recommended tool usage patterns. This is analogous to the prompt engineering in the original LocAgent paper, which provided agents with tool descriptions and usage examples.

This does not affect baseline validity because:
- The original paper included tool documentation in prompts
- All our experimental conditions receive equivalent documentation for their tools
- We document *how* to use tools, not *when*—strategic decisions remain with the agent

#### Equivalence Guarantee

Our MCP extraction is **functionally equivalent** to the original LocAgent tools:

| Component | Original | Our Extraction |
|-----------|----------|----------------|
| Graph construction | Tree-sitter → NetworkX | Identical (`build_graph.py`) |
| Graph traversal | BFS with depth/direction control | Identical (`traverse_graph.py`) |
| BM25 search | llama_index + PyStemmer | Identical (`bm25_retriever.py`) |
| Fuzzy matching | RapidFuzz | Identical (`fuzzy_retriever.py`) |
| Code retrieval | Line-numbered snippets | Identical (`repo_ops.py`) |

The only differences are in the **wrapper layer** (MCP protocol instead of direct function calls) and **state management** (simplified for single-repo focus). The core algorithms that define LocAgent's approach are preserved verbatim.

---

## Architecture

### Directory Structure
```
locagent/
├── server.py              # MCP server with 5 tool definitions
├── state.py               # Repository initialization and global state
├── USAGE.md               # Agent-facing quick reference
└── core/
    ├── dependency_graph/
    │   ├── build_graph.py     # Tree-sitter AST → NetworkX graph
    │   └── traverse_graph.py  # BFS traversal, DOT output formatting
    ├── repo_index/
    │   └── index/
    │       └── epic_split.py  # Semantic code chunking
    └── location_tools/
        ├── repo_ops/
        │   └── repo_ops.py    # Core operations (globals for state)
        └── retriever/
            ├── bm25_retriever.py   # Semantic code search
            └── fuzzy_retriever.py  # Entity name fuzzy matching
```

### Graph Data Model

#### Node Types
| Type | Description | Example Node ID |
|------|-------------|-----------------|
| `FILE` | Python source file | `src/utils.py` |
| `DIRECTORY` | Directory container | `src/` |
| `CLASS` | Class definition | `src/utils.py:ConfigLoader` |
| `FUNCTION` | Function/method | `src/utils.py:parse_config` |

#### Edge Types
| Type | Meaning | Example |
|------|---------|---------|
| `CONTAINS` | Parent contains child | `FILE` → `CLASS`, `CLASS` → `FUNCTION` |
| `CALLS` | Function calls function | `main.py:run` → `utils.py:parse_config` |
| `INHERITS` | Class extends class | `models.py:Dog` → `models.py:Animal` |
| `INSTANTIATES` | Code creates instance | `app.py:start` → `models.py:Config` |
| `USES` | General usage/reference | Various import relationships |

#### Node ID Format
```
file.py              # FILE node
file.py:ClassName    # CLASS node  
file.py:function     # FUNCTION node (top-level)
file.py:Class.method # FUNCTION node (method)
```

---

## MCP Tools

The server exposes **5 tools** under the `codegraph` server name:

### 1. `init_repository`
**Purpose:** Initialize the dependency graph and search indexes for a repository.

```python
init_repository(repo_path: str, force_rebuild: bool = False) -> str
```

**What it does:**
1. Parses all Python files using Tree-sitter
2. Builds NetworkX MultiDiGraph with code entities
3. Creates BM25 index over semantic code chunks
4. Caches both artifacts for future sessions

**Returns:** Summary with node/edge counts and next-step hint.

### 2. `get_dependencies`
**Purpose:** Traverse the dependency graph to find related code entities.

```python
get_dependencies(
    entities: List[str],      # Node IDs to start from
    direction: str = "both",  # "incoming" | "outgoing" | "both"
    depth: int = 2            # How many hops to traverse
) -> str
```

**Direction semantics:**
- `outgoing` (downstream): What does this entity call/use/contain?
- `incoming` (upstream): What calls/uses/references this entity?
- `both`: Bidirectional traversal

**Output format:** DOT graph notation for structured visualization.

### 3. `search_code`
**Purpose:** Semantic search over code content using BM25.

```python
search_code(query: List[str], top_k: int = 5) -> str
```

**How it works:**
1. Query terms are stemmed and tokenized
2. BM25 ranks code chunks by relevance
3. Returns matched snippets with file paths and line numbers

**Chunking strategy:** Uses `EpicSplitter` which respects semantic boundaries (functions, classes) rather than arbitrary token counts.

### 4. `search_entities`
**Purpose:** Fuzzy search over entity names (node IDs).

```python
search_entities(query: List[str], top_k: int = 10) -> str
```

**Use case:** When you know approximate name but not exact location.
- Query: `["config", "loader"]`
- Finds: `src/config.py:ConfigLoader`, `utils/load_config.py:load`

**Algorithm:** RapidFuzz with custom tokenizer (splits on `_`, `-`, `/`).

### 5. `get_code`
**Purpose:** Retrieve full source code for specific entities.

```python
get_code(entities: List[str]) -> str
```

**Returns:** Code snippets with line numbers for precise context.

---

## Graph Construction Deep Dive

### Tree-sitter Parsing (`build_graph.py`)

The graph is built in multiple passes:

#### Pass 1: File Discovery
```python
for file_path in glob("**/*.py"):
    G.add_node(file_path, type=NODE_TYPE_FILE, code=read(file_path))
```

#### Pass 2: Entity Extraction
For each file, Tree-sitter parses the AST to identify:
- Class definitions → `CLASS` nodes
- Function definitions → `FUNCTION` nodes
- Method definitions → `FUNCTION` nodes (nested under class)

```python
tree = parser.parse(source_code)
for node in tree.root_node.children:
    if node.type == "class_definition":
        class_name = get_name(node)
        G.add_node(f"{file}:{class_name}", type=NODE_TYPE_CLASS, ...)
        G.add_edge(file, f"{file}:{class_name}", type=EDGE_TYPE_CONTAINS)
```

#### Pass 3: Relationship Extraction
Analyzes AST for:
- **CALLS:** Function call expressions → resolve to target node
- **INHERITS:** Class base classes → inheritance edges
- **INSTANTIATES:** Constructor calls → instantiation edges
- **USES:** Import statements → usage edges

#### Pass 4: Cross-File Resolution
Uses `global_import=True` to resolve imports across files:
```python
# In file_a.py: from utils import parse_config
# Creates edge: file_a.py:caller -> utils.py:parse_config (CALLS)
```

### Caching Strategy
```
~/.cache/locagent/
├── graphs/
│   └── mcp_<repo>_<hash>.pkl    # Pickled NetworkX graph
└── bm25/
    └── mcp_<repo>_<hash>/
        └── corpus.jsonl          # BM25 index data
```

Rebuild triggered by:
- `force_rebuild=True` parameter
- Cache file not found
- Pickle load failure

---

## Graph Traversal Algorithm

### BFS with Depth Control (`traverse_graph.py`)

```python
def traverse_graph_structure(G, roots, direction, hops):
    frontiers = [(nid, 0) for nid in roots]
    visited = []
    subG = nx.MultiDiGraph()
    
    while frontiers:
        nid, level = frontiers.pop()
        if nid in visited or abs(level) >= hops:
            continue
        visited.append(nid)
        
        # Direction logic:
        # level > 0: forward (downstream)
        # level < 0: backward (upstream)
        # level == 0: both directions if direction="both"
        
        if should_go_forward(level, direction):
            neighbors = get_successors(nid)
            frontiers.extend([(n, level + 1) for n in neighbors])
            
        if should_go_backward(level, direction):
            neighbors = get_predecessors(nid)
            frontiers.extend([(n, level - 1) for n in neighbors])
    
    return format_as_dot(subG)
```

### Output Formats
The traversal supports multiple output encodings:
- **DOT (pydot):** Default, creates Graphviz-compatible visualization
- **raw:** Simple edge list
- **incident:** Relationship-focused text format

---

## BM25 Semantic Search

### EpicSplitter: Semantic Chunking (`epic_split.py`)

Unlike naive token-based splitting, EpicSplitter respects code structure:

```python
def split_code(source: str) -> List[Chunk]:
    # Parse with Tree-sitter
    tree = parser.parse(source)
    
    chunks = []
    for node in tree.root_node.children:
        if node.type in ["function_definition", "class_definition"]:
            # Each function/class becomes its own chunk
            chunks.append(Chunk(
                content=source[node.start_byte:node.end_byte],
                metadata={"entity": get_qualified_name(node)}
            ))
    
    return chunks
```

**Benefits:**
- Preserves complete function/class bodies
- Maintains semantic coherence for BM25 matching
- Excludes test files from indexing

### BM25 Configuration (`bm25_retriever.py`)

```python
from llama_index.retrievers.bm25 import BM25Retriever
from Stemmer import Stemmer

retriever = BM25Retriever.from_defaults(
    nodes=chunks,
    similarity_top_k=top_k,
    stemmer=Stemmer("english")  # Porter stemming
)
```

---

## State Management

### Global State Pattern (`repo_ops.py`)

The original LocAgent used module-level globals for state:

```python
# In repo_ops.py
DP_GRAPH = None                    # NetworkX graph
DP_GRAPH_ENTITY_SEARCHER = None    # RepoEntitySearcher instance
DP_GRAPH_DEPENDENCY_SEARCHER = None # RepoDependencySearcher instance
REPO_SAVE_DIR = None               # Current repository path
ALL_FILE = []                      # List of all file nodes
ALL_CLASS = []                     # List of all class nodes
ALL_FUNC = []                      # List of all function nodes
```

### MCP State Wrapper (`state.py`)

Our extraction wraps initialization to set these globals:

```python
def init_repository(repo_path: str, force_rebuild: bool = False) -> str:
    # Build or load cached graph
    G = load_or_build_graph(repo_path)
    
    # Set globals for downstream tools
    repo_ops.DP_GRAPH = G
    repo_ops.DP_GRAPH_ENTITY_SEARCHER = RepoEntitySearcher(G)
    repo_ops.DP_GRAPH_DEPENDENCY_SEARCHER = RepoDependencySearcher(G)
    repo_ops.REPO_SAVE_DIR = repo_path
    
    # Build BM25 index
    build_code_retriever(repo_path, persist_path=bm25_path)
    
    return f"Initialized: {repo_path} ({G.number_of_nodes()} nodes)"
```

---

## Comparison: LocAgent vs CodeCanvas

| Aspect | LocAgent (CodeGraph) | CodeCanvas |
|--------|---------------------|------------|
| **Primary abstraction** | Dependency graph | Visual canvas |
| **Navigation model** | Entity → relationships | Spatial → neighbors |
| **Search paradigm** | BM25 + fuzzy names | TBD |
| **Output format** | DOT graphs, text | Visual layout |
| **Initialization cost** | High (Tree-sitter + index) | TBD |
| **Best for** | Call-flow understanding | TBD |

---

## Usage Patterns

### Recommended Workflow
```
1. init_repository(repo_path="/path/to/repo")
   → Builds graph, indexes code

2. get_dependencies(entities=["/"], depth=2)
   → See high-level module structure

3. search_code(query=["config", "database"])
   → Find relevant code by content

4. get_dependencies(entities=["config.py:DatabaseConfig"], direction="incoming")
   → Who uses this configuration?

5. get_code(entities=["app.py:init_db", "config.py:DatabaseConfig"])
   → Retrieve full source for editing
```

### Entity Reference Patterns
```
# File level
"src/utils.py"

# Class level  
"src/models.py:User"

# Method level
"src/models.py:User.validate"

# Function level
"src/utils.py:parse_config"

# Root directory (special)
"/"
```

---

## Limitations

### Current Implementation
1. **Python only:** Tree-sitter queries are Python-specific
2. **Single repository:** Cannot traverse across repo boundaries
3. **No incremental updates:** Graph must be fully rebuilt on changes
4. **Global state:** Only one repository can be active at a time

### Fundamental Approach Limitations
1. **Graph explosion:** Large repos create overwhelming traversal results
2. **Missing dynamic relationships:** Cannot capture runtime dispatch
3. **No semantic similarity:** BM25 is keyword-based, not embedding-based
4. **Initialization latency:** First-time graph building is slow

---

## Implementation Notes

### Dependencies
```toml
[project.optional-dependencies]
locagent = [
    "tree-sitter>=0.24.0",
    "tree-sitter-python>=0.24.0", 
    "networkx>=3.4.2",
    "pydot>=3.0.4",
    "PyStemmer>=2.2.0.3",
    "rapidfuzz>=3.10.1",
    "llama-index-core>=0.12.2",
    "llama-index-retrievers-bm25>=0.4.0",
]
```

### Running the MCP Server
```bash
# Via uv
uv run python -m locagent.server

# In .mcp.json
{
  "mcpServers": {
    "codegraph": {
      "command": "uv",
      "args": ["run", "python", "-m", "locagent.server"]
    }
  }
}
```

---

## References

1. **Original Paper:** Chen, Z. et al. "LocAgent: Graph-Guided LLM Agents for Code Localization." arXiv:2503.09089v2 (2025)
2. **Tree-sitter:** https://tree-sitter.github.io/tree-sitter/
3. **NetworkX:** https://networkx.org/
4. **MCP Protocol:** https://modelcontextprotocol.io/
5. **BM25 Algorithm:** Robertson, S. & Zaragoza, H. "The Probabilistic Relevance Framework: BM25 and Beyond"

---

## Changelog

### MCP Extraction (2024)
- Extracted core tools from full agent framework
- Added MCP protocol wrapper
- Implemented graph/index caching
- Renamed agent-facing server to `codegraph` for semantic clarity
- Simplified state management for single-repo focus
