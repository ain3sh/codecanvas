## Backend Feature Comparison & Superset

### Unique to crabviz (MUST PORT)
| Feature | Description |
|---------|-------------|
| **3 relation types** | Call, Impl, Inherit (vs DepViz's import/call) |
| **LSP call hierarchy** | Uses CallHierarchyIncomingCall/OutgoingCall for accurate call detection |
| **Interface tracking** | Tracks interface→implementation relations |
| **Nested symbols** | Symbol.children for functions-inside-functions |
| **Transitive focus** | Follows call chains in focus mode (not just direct edges) |
| **Pre-computed edge maps** | incoming/outgoing Maps for O(1) traversal |

### Unique to DepViz (MUST PORT)
| Feature | Description |
|---------|-------------|
| **Import edges** | Tracks Python/JS/TS import relationships between modules |
| **recomputeMissingEdges** | Infers call edges from snippets when LSP fails |
| **Import preference** | Resolves ambiguous calls by preferring imported modules |
| **mergeArtifacts** | Merges multiple parse results with deduplication |
| **Source/snippet storage** | Stores module source + function snippets for later analysis |
| **Dual parsing** | LSP first, falls back to regex-based naive parser |
| **Docked/collapsed state** | Visual containment state per node |

### Both Have (Pick Better)
| Feature | Winner | Reason |
|---------|--------|--------|
| Class detection | DepViz | Handles indentation-based (Python) |
| Call detection | crabviz | LSP call hierarchy more accurate |
| File structure | DepViz | Module→Class→Func hierarchy cleaner |
| ID scheme | DepViz | `mod_hash`, `cls_file_name`, `fn_file_name_line` |

---

## Combined Data Model

```python
class EdgeType(Enum):
    IMPORT = "import"    # DepViz: module→module imports
    CALL = "call"        # Both: function calls
    IMPL = "impl"        # crabviz: interface implementations
    INHERIT = "inherit"  # crabviz: class inheritance

class GraphNode:
    id: str              # DepViz ID scheme
    kind: NodeKind       # module | class | func
    label: str
    fsPath: str
    parent: str          # containment (DepViz)
    children: List[str]  # nested symbols (crabviz)
    docked: bool         # visual state (DepViz)
    collapsed: bool      # module state (DepViz)
    source: str          # full source (DepViz)
    snippet: str         # first N lines (DepViz)
    range: Range         # line, col

class GraphEdge:
    from_id: str
    to_id: str
    type: EdgeType
```

---

## Implementation Files

### 1. models.py - Combined data model (above)

### 2. parser.py - Dual parsing (DepViz approach)
- Try tree-sitter first (like DepViz LSP)
- Fall back to regex naive parsing
- Detect: imports, calls, classes, inheritance
- Store: source, snippets, ranges
- Build: parent hierarchy + children list

### 3. analysis.py - Combined analysis
- **From crabviz:**
  - Pre-computed incoming/outgoing edge maps
  - Transitive focus traversal
  - Interface/inheritance tracking
- **From DepViz:**
  - recomputeMissingEdges (snippet-based inference)
  - Import preference resolution
  - Impact slice with ancestor inclusion

### 4. state.py - Graph state management
- **From DepViz:**
  - mergeArtifacts with deduplication
  - normalizeNodes (default docked/collapsed)
  - Edge key generation for dedup

### 5. layout.py - DepViz arrange algorithms
- autoArrangeByFolders
- autoArrangeBalanced  
- Geometry: anchorPoint, absTopLeftOf, bezier curves

### 6. render/render.js - DepViz visualization (frontend)
- Port webview.js rendering
- Port webview.css styling
- Port webview-geom.js edge routing
- Port computeSlice + applySliceOverlay

### 7. canvas.py - Unified API
- canvas('/path') → init + parse
- canvas(target='x') → focus + slice
- canvas(write='...') → scratchpad

---

## Key Algorithms to Port

### From crabviz: Transitive Focus
```javascript
// Follow call chains, not just direct edges
for (let newEdges = map.get(cellId); newEdges.length > 0; ) {
  newEdges = newEdges.flatMap((edge) => {
    highlightEdges.add(edge);
    const id = dir == 0 ? edge.from : edge.to;
    if (visited.has(id)) return [];
    visited.add(id);
    return map.get(id) ?? [];
  });
}
```

### From DepViz: Import Preference Resolution
```javascript
// When multiple functions match, prefer from imported modules
for (const cand of candidates) {
  const candMod = getModule(cand);
  if (importPrefs.has(candMod)) { best = cand; break; }
}
```

### From DepViz: Ancestor Inclusion in Slice
```javascript
// func → class → module all get included
if (n.kind === 'func') {
  add(n.parent);  // class
  add(parent.parent);  // module
}
```