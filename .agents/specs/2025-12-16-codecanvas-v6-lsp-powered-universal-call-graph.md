## CodeCanvas V6: LSP-Powered Universal Call Graph

### Executive Summary
Port crabviz's LSP call hierarchy and depviz's dual-parsing fallback to replace 80% of parser.py's regex code. Adds support for Go, Rust, Java, Ruby via language server delegation instead of custom parsers.

---

### Phase 1: New LSP Infrastructure

#### 1.1 Create `codecanvas/lsp_client.py` (~200 lines)
```python
@dataclass
class GlobalPosition:
    """Compact hashable identity (crabviz pattern)."""
    file_id: int
    line: int
    character: int

class LSPClient:
    """Async JSON-RPC client for any language server."""
    
    async def document_symbols(self, uri: str) -> List[DocumentSymbol]
    async def prepare_call_hierarchy(self, uri: str, pos: Position) -> List[CallHierarchyItem]
    async def incoming_calls(self, item: CallHierarchyItem) -> List[CallHierarchyIncomingCall]
    async def outgoing_calls(self, item: CallHierarchyItem) -> List[CallHierarchyOutgoingCall]
    async def implementations(self, uri: str, pos: Position) -> List[Location]
```

#### 1.2 Create `codecanvas/languages.py` (~100 lines)
```python
LANGUAGE_SERVERS = {
    "py": {"cmd": ["pyright-langserver", "--stdio"], "init": {...}},
    "go": {"cmd": ["gopls", "serve"], "init": {...}},
    "rs": {"cmd": ["rust-analyzer"], "init": {...}},
    "java": {"cmd": ["jdtls"], "init": {...}},
    "rb": {"cmd": ["solargraph", "stdio"], "init": {...}},
    "ts": {"cmd": ["typescript-language-server", "--stdio"], "init": {...}},
}

SYMBOL_FILTERS = {
    "rs": lambda s: "test" not in s.detail,  # Filter test modules
    "go": lambda s: not s.uri.endswith("_test.go"),
    "ts": lambda s: s.name != "<anonymous>",  # Filter anonymous callbacks
}
```

---

### Phase 2: Model Extensions

#### 2.1 Extend `models.py`

**Add EdgeType values:**
```python
class EdgeType(Enum):
    IMPORT = "import"
    CALL = "call"
    IMPL = "impl"      # NEW: interface -> implementation
    INHERIT = "inherit" # NEW: class inheritance
```

**Add to Graph class:**
```python
# Pre-computed edge maps (crabviz pattern)
_incoming: Dict[str, List[GraphEdge]]   # node_id -> edges where to_id == node_id
_outgoing: Dict[str, List[GraphEdge]]   # node_id -> edges where from_id == node_id
_implementations: Dict[str, List[str]]  # interface_id -> [impl_ids]
```

---

### Phase 3: Parser Restructure

#### 3.1 Split `parser.py` into:

| File | Lines | Purpose |
|------|-------|---------|
| `parser.py` | ~150 | Orchestration: LSP first, fallback to naive |
| `naive_parser.py` | ~400 | Current regex code (extracted, cleaned) |

**New parser.py logic:**
```python
class Parser:
    async def parse_file(self, path: str) -> GraphArtifacts:
        lang = detect_language(path)
        
        # Try LSP first (crabviz approach)
        if lang in LANGUAGE_SERVERS:
            try:
                return await self._parse_with_lsp(path, lang)
            except LSPError:
                pass
        
        # Fallback to naive (depviz approach)
        return self._parse_naive(path, lang)
    
    async def _parse_with_lsp(self, path, lang):
        symbols = await self.lsp.document_symbols(path)
        if not symbols:
            raise LSPError("No symbols")
        
        # Build nodes from symbols
        # Get call edges via call hierarchy
        # Get impl edges via implementations
```

---

### Phase 4: Analysis Upgrades

#### 4.1 Add to `analysis.py`

**Transitive Focus (crabviz algorithm):**
```python
def transitive_focus(self, node_id: str, direction: Direction = Direction.BOTH) -> Set[str]:
    """Follow call chains transitively with direction tracking."""
    visited: Dict[str, Direction] = {}
    
    if direction & Direction.INCOMING:
        self._traverse_incoming(node_id, visited)
    if direction & Direction.OUTGOING:
        self._traverse_outgoing(node_id, visited)
    
    return set(visited.keys())
```

**Import Preference Resolution (depviz algorithm):**
```python
def resolve_call_target(self, caller_id: str, call_name: str, candidates: List[str]) -> str | None:
    """Prefer functions from imported modules."""
    caller_imports = self._get_imports(caller_id)
    
    for cand_id in candidates:
        cand_module = self._get_module(cand_id)
        if cand_module in caller_imports:
            return cand_id
    
    return candidates[0] if candidates else None
```

---

### Phase 5: Code Deletion (Cleanup)

#### 5.1 DELETE from `parser.py` (~350 lines removed):

| Code Block | Lines | Reason |
|------------|-------|--------|
| `_init_treesitter()` | 15 | LSP replaces tree-sitter |
| `_parse_python_treesitter()` | 80 | LSP documentSymbol replaces |
| `_parse_naive()` class detection | 60 | Moves to naive_parser.py |
| Tree-sitter imports & state | 20 | No longer needed |
| `_ts_parser`, `_ts_python` fields | 5 | No longer needed |
| Duplicate import detection in naive | 40 | Consolidated |

#### 5.2 KEEP in `naive_parser.py` (fallback):

| Code Block | Reason |
|------------|--------|
| `_strip_strings_and_comments()` | Needed for call inference |
| `_infer_calls()` | Deterministic fallback when no LSP |
| `_detect_imports_py/ts()` | Import edge detection |
| `_FuncMeta`, `_FuncDef` | Internal call inference |

---

### Phase 6: Dependency Changes

#### 6.1 Remove from `pyproject.toml`:
```toml
# DELETE
"tree-sitter>=0.20",
"tree-sitter-python>=0.20",
```

#### 6.2 Add to `pyproject.toml`:
```toml
# ADD
"pygls>=1.0",  # LSP protocol types
```

---

### Implementation Order

1. **Create `lsp_client.py`** - Core LSP communication
2. **Create `languages.py`** - Language server configs
3. **Extend `models.py`** - Add IMPL/INHERIT, edge maps
4. **Extract `naive_parser.py`** - Move regex code
5. **Rewrite `parser.py`** - LSP-first orchestration
6. **Extend `analysis.py`** - Transitive focus, import preference
7. **Delete tree-sitter deps** - Clean pyproject.toml
8. **Run tests** - Verify all 8 tests still pass

---

### Files Changed Summary

| File | Action | Net Lines |
|------|--------|-----------|
| `lsp_client.py` | CREATE | +200 |
| `languages.py` | CREATE | +100 |
| `naive_parser.py` | CREATE | +400 (extracted) |
| `parser.py` | REWRITE | -350 (700 -> 150) |
| `models.py` | EXTEND | +40 |
| `analysis.py` | EXTEND | +80 |
| `pyproject.toml` | MODIFY | -2, +1 |

**Net change:** ~470 new lines, ~350 deleted = **+120 lines total** for universal language support.

---

### Testing Strategy

1. **Unit tests** for LSP client mock responses
2. **Integration test** with pyright on codecanvas/ itself
3. **Fallback test** - disable LSP, verify naive parser works
4. **Edge type tests** - IMPL edges for Python ABCs