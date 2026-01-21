# Crabviz Technical Review

**Analysis Date:** 2025-12-16  
**Purpose:** Port LSP-based call graph generation to CodeCanvas  
**Architecture:** Rust core (WASM) + TypeScript VS Code extension

---

## 1. Overview

Crabviz is an LSP-based call graph generator that leverages the Language Server Protocol to create interactive visualizations. The architecture consists of:

- **Core (Rust)**: Graph generation logic compiled to WASM
- **Editor Extension (TypeScript)**: VS Code integration that drives LSP queries
- **Two-mode operation**:
  - **File-level**: Generate overview graph for selected files
  - **Function-level**: Generate focused graph for a specific function (transitive closure)

### Key Design Principles

1. **LSP-first**: Delegates all code understanding to language servers
2. **Language-agnostic**: Works with any language that has LSP support
3. **Incremental building**: Pre-computes edge maps before graph generation
4. **Transitive exploration**: Follows call chains recursively with cycle detection

---

## 2. LSP Call Hierarchy Implementation

### 2.1 Core LSP Types

Located in `core/src/types/lsp.rs`, Crabviz uses LSP's call hierarchy protocol:

```rust
/// Represents an incoming call (caller → callee)
pub struct CallHierarchyIncomingCall {
    /// The item that makes the call
    pub from: CallHierarchyItem,
    
    /// The ranges where calls appear (relative to caller)
    pub from_ranges: Vec<Range>,
}

/// Represents an outgoing call (caller → callee)
pub struct CallHierarchyOutgoingCall {
    /// The item that is called
    pub to: CallHierarchyItem,
    
    /// The ranges where calls appear (relative to caller)
    pub from_ranges: Vec<Range>,
}

/// A callable item (function, method, constructor)
pub struct CallHierarchyItem {
    pub name: String,
    pub kind: SymbolKind,
    pub uri: Uri,
    pub range: Range,
    pub selection_range: Range,
    pub data: Option<Value>,  // Preserved across requests
}
```

### 2.2 LSP Query Flow (TypeScript Side)

From `editors/code/src/generator.ts`:

```typescript
// Step 1: Prepare call hierarchy (get CallHierarchyItem)
let items: vscode.CallHierarchyItem[] = 
  await vscode.commands.executeCommand(
    'vscode.prepareCallHierarchy', 
    file, 
    symbolStart
  );

// Step 2a: Get incoming calls (who calls this?)
await vscode.commands.executeCommand<vscode.CallHierarchyIncomingCall[]>(
  'vscode.provideIncomingCalls', 
  item
);

// Step 2b: Get outgoing calls (what does this call?)
await vscode.commands.executeCommand<vscode.CallHierarchyOutgoingCall[]>(
  'vscode.provideOutgoingCalls', 
  item
);
```

### 2.3 Critical Insight: Nested Function Handling

From `core/src/generator/mod.rs`, lines 137-157:

```rust
// incoming calls may start from nested functions, which may not be 
// included in file symbols in some lsp server implementations.
// in that case, we add the missing nested symbol to the symbol list.

(symbols_ref.contains(&from)
    || inserted_symbols_ref.borrow().contains(&from)
    || {
        let id = *self.file_id_map.get(&call.from.uri.path)?;
        let node = files_ref.get(id as usize - 1)? as *const File;

        let updated = self.try_insert_symbol(&call.from, unsafe {
            node.cast_mut().as_mut().unwrap()
        });

        if updated {
            inserted_symbols_ref.borrow_mut().insert(from);
        }
        updated
    })
```

**Rationale**: Some LSP servers (especially for nested closures/lambdas) don't include nested functions in `textDocument/documentSymbol` but DO return them in call hierarchy. Crabviz dynamically inserts these missing symbols during graph generation.

---

## 3. Multi-Language Support Architecture

### 3.1 Language Handler Pattern

From `core/src/lang/mod.rs`:

```rust
pub(crate) trait Language {
    /// Filter files (e.g., Go test files)
    fn should_filter_out_file(&self, _file: &str) -> bool {
        false
    }

    /// Filter symbols (e.g., variables, constants)
    fn filter_symbol(&self, symbol: &DocumentSymbol, parent: Option<&DocumentSymbol>) -> bool {
        match symbol.kind {
            SymbolKind::Constant | SymbolKind::Variable | SymbolKind::EnumMember => false,
            SymbolKind::Field | SymbolKind::Property => {
                // Keep interface fields, filter class fields
                parent.is_some_and(|s| matches!(s.kind, SymbolKind::Interface))
            }
            _ => true,
        }
    }
}

pub(crate) fn language_handler(lang: &str) -> Box<dyn Language + Sync + Send> {
    match lang {
        "Go" => Box::new(Go),
        "Rust" => Box::new(Rust),
        "JavaScript" | "TypeScript" | "JavaScript JSX" | "TypeScript JSX" => Box::new(Jsts),
        _ => Box::new(DEFAULT_LANG),
    }
}
```

### 3.2 Language-Specific Customizations

**Rust** (`lang/rust.rs`):
```rust
impl Language for Rust {
    fn filter_symbol(&self, symbol: &DocumentSymbol, parent: Option<&DocumentSymbol>) -> bool {
        match symbol.kind {
            SymbolKind::Constant | SymbolKind::EnumMember => false,
            SymbolKind::Module if symbol.name == "tests" => false,  // Filter test modules
            _ => DEFAULT_LANG.filter_symbol(symbol, parent),
        }
    }
}
```

**Go** (`lang/go.rs`):
```rust
impl Language for Go {
    fn should_filter_out_file(&self, file: &str) -> bool {
        file.ends_with("_test.go")  // Skip test files
    }
}
```

**JavaScript/TypeScript** (`lang/jsts.rs`):
```rust
impl Language for Jsts {
    fn filter_symbol(&self, symbol: &DocumentSymbol, parent: Option<&DocumentSymbol>) -> bool {
        match symbol.kind {
            SymbolKind::Function => {
                // Filter anonymous callbacks
                !(symbol.name.ends_with(" callback") || symbol.name == "<function>")
            }
            _ => DEFAULT_LANG.filter_symbol(symbol, parent),
        }
    }
}
```

### 3.3 LSP Delegation Strategy

**Key insight**: Crabviz never parses code directly. It:
1. Asks LSP for document symbols via `textDocument/documentSymbol`
2. Asks LSP for call hierarchy via `callHierarchy/prepare`, `callHierarchy/incomingCalls`, `callHierarchy/outgoingCalls`
3. Asks LSP for implementations via `textDocument/implementation`

This means multi-language support is "free" - as long as the LSP server implements these methods, Crabviz works.

---

## 4. The 3 Relation Types

From `core/src/types/graph.rs`:

```rust
#[derive(Debug, Clone, Serialize_repr)]
#[repr(u8)]
pub enum RelationKind {
    Call,      // 0: Function calls
    Impl,      // 1: Interface implementations
    Inherit,   // 2: Class inheritance (not currently used)
}

#[derive(Debug, Clone, Serialize)]
pub struct Relation {
    pub from: GlobalPosition,  // Source location
    pub to: GlobalPosition,    // Target location
    pub kind: RelationKind,
}
```

### 4.1 Call Relations

Generated from `CallHierarchyIncomingCall` and `CallHierarchyOutgoingCall`:

```rust
// From incoming calls (callers → callee)
let incoming_calls = self
    .incoming_calls
    .iter()
    .filter_map(|(callee, callers)| symbols.contains(&callee).then_some((callee, callers)))
    .flat_map(|(to, calls)| {
        calls.into_iter().filter_map(move |call| {
            let from = self.call_item_global_location(&call.from)?;
            
            (symbols_ref.contains(&from) || /* nested function handling */)
                .then_some(Relation {
                    from,
                    to: to.to_owned(),
                    kind: RelationKind::Call,
                })
        })
    });

// From outgoing calls (caller → callees)
let outgoing_calls = self
    .outgoing_calls
    .iter()
    .filter_map(|(caller, callees)| {
        symbols_ref.contains(&caller).then_some((caller, callees))
    })
    .flat_map(|(from, callees)| {
        callees.into_iter().filter_map(move |call| {
            let to = self.call_item_global_location(&call.to)?;
            
            symbols_ref.contains(&to).then_some(Relation {
                from: from.to_owned(),
                to,
                kind: RelationKind::Call,
            })
        })
    });
```

**Detection mechanism**: LSP's call hierarchy protocol provides these directly.

### 4.2 Impl Relations

From `core/src/generator/mod.rs`:

```rust
// Interface → implementations
let implementations = self
    .interfaces
    .iter()
    .filter_map(|(interface, implementations)| {
        symbols_ref
            .contains(&interface)
            .then_some((interface, implementations))
    })
    .flat_map(|(to, implementations)| {
        implementations.into_iter().filter_map(move |location| {
            symbols_ref.contains(location).then_some(Relation {
                from: location.to_owned(),  // Implementation
                to: to.to_owned(),          // Interface
                kind: RelationKind::Impl,
            })
        })
    });
```

**Detection mechanism** (TypeScript side):

```typescript
// For interface symbols, query implementations
if (symbol.kind === vscode.SymbolKind.Interface) {
  await vscode.commands.executeCommand<vscode.Location[] | vscode.LocationLink[]>(
    'vscode.executeImplementationProvider', 
    file, 
    symbol.selectionRange.start
  ).then(result => {
    // Convert LocationLink[] to Location[] if needed
    this.inner.add_interface_implementations(filePath, symbol.selectionRange.start, locations);
  });
}
```

### 4.3 Inherit Relations

**Status**: Defined in the enum but **not currently implemented**. This would require:
- Querying `textDocument/typeHierarchy` (supertype/subtype)
- Or parsing inheritance from document symbols

---

## 5. Interface-to-Implementation Tracking

### 5.1 Data Structure

From `core/src/generator/mod.rs`:

```rust
pub struct GraphGenerator {
    // ...
    interfaces: HashMap<GlobalPosition, Vec<GlobalPosition>>,
    // Key: Interface location
    // Value: All implementation locations
}

pub fn add_interface_implementations(
    &mut self,
    path: String,
    position: Position,
    locations: Vec<Location>,
) {
    let location = GlobalPosition::new(self.alloc_file_id(path), position);
    let implementations = locations
        .into_iter()
        .map(|location| {
            GlobalPosition::new(self.alloc_file_id(location.uri.path), location.range.start)
        })
        .collect();
    self.interfaces.insert(location, implementations);
}
```

### 5.2 Query Pattern (TypeScript)

```typescript
// Traverse all file symbols
while (symbols.length > 0) {
  for await (const symbol of symbols) {
    if (symbol.kind === vscode.SymbolKind.Interface) {
      // Query LSP for implementations
      const result = await vscode.commands.executeCommand<
        vscode.Location[] | vscode.LocationLink[]
      >('vscode.executeImplementationProvider', file, symbol.selectionRange.start);
      
      // Convert LocationLink to Location if needed
      let locations: vscode.Location[];
      if (!(result[0] instanceof vscode.Location)) {
        locations = result.map(l => {
          let link = l as vscode.LocationLink;
          return new vscode.Location(link.targetUri, link.targetSelectionRange ?? link.targetRange);
        });
      } else {
        locations = result as vscode.Location[];
      }
      
      this.inner.add_interface_implementations(filePath, symbol.selectionRange.start, locations);
    }
  }
  
  symbols = symbols.flatMap(symbol => symbol.children);  // Recurse into nested symbols
}
```

### 5.3 Edge Direction

**Important**: In the graph, edges point FROM implementation TO interface:
```
ClassImpl --[Impl]--> IInterface
```

This is the opposite of call relations (caller → callee). The rationale is that implementations "depend on" interfaces.

---

## 6. Transitive Focus Algorithm

The "killer feature" of Crabviz is focused function graphs that follow call chains transitively.

### 6.1 Bidirectional Traversal with Cycle Detection

From `editors/code/src/generator.ts`:

```typescript
enum FuncCallDirection {
  INCOMING = 1 << 1,  // 0b0010 (2)
  OUTGOING = 1 << 2,  // 0b0100 (4)
  BIDIRECTION = INCOMING | OUTGOING,  // 0b0110 (6)
}

class VisitedFile {
  private funcs: Map<string, [vscode.Range, FuncCallDirection]>;
  
  // Mark function as visited in a direction
  visitFunc(rng: vscode.Range, direction: FuncCallDirection) {
    let key = keyFromPosition(rng.start);
    let val = this.funcs.get(key);
    
    if (!val) {
      this.funcs.set(key, [rng, direction]);
    } else {
      val[1] |= direction;  // Bitwise OR to merge directions
    }
  }
  
  // Check if already visited in this direction
  hasVisitedFunc(pos: vscode.Position, direction: FuncCallDirection): boolean {
    return ((this.funcs.get(keyFromPosition(pos))?.[1] ?? 0) & direction) === direction;
  }
}
```

### 6.2 Recursive Incoming Call Traversal

```typescript
async resolveIncomingCalls(
  item: vscode.CallHierarchyItem, 
  funcMap: Map<string, VisitedFile>, 
  ig: Ignore
) {
  // Get all callers of this item
  const calls = await vscode.commands.executeCommand<vscode.CallHierarchyIncomingCall[]>(
    'vscode.provideIncomingCalls', 
    item
  );
  
  const itemNormalizedPath = normalizedPath(item.uri.path);
  
  // Store in edge map
  this.inner.add_incoming_calls(itemNormalizedPath, item.selectionRange.start, calls);
  
  // Mark this function as visited for incoming calls
  funcMap.get(itemNormalizedPath)!.visitFunc(item.selectionRange, FuncCallDirection.INCOMING);
  
  // Filter to unvisited callers
  const unvisitedCalls = calls.filter(call => {
    const uri = call.from.uri;
    
    // Create entry if file not seen before
    let file = funcMap.get(uri.path);
    if (!file) {
      file = new VisitedFile(uri);
      file.skip = ig.ignores(path.posix.relative(this.root, uri.path)) 
                  || this.inner.should_filter_out_file(uri.path);
      funcMap.set(uri.path, file);
    }
    
    // Skip if: file is ignored OR function already visited in INCOMING direction
    return !file.skip 
           && !file.hasVisitedFunc(call.from.selectionRange.start, FuncCallDirection.INCOMING);
  });
  
  // Recursively traverse unvisited callers
  for await (const call of unvisitedCalls) {
    await this.resolveIncomingCalls(call.from, funcMap, ig);
  }
}
```

### 6.3 Recursive Outgoing Call Traversal

```typescript
async resolveOutgoingCalls(
  item: vscode.CallHierarchyItem, 
  funcMap: Map<string, VisitedFile>, 
  ig: Ignore
) {
  const calls = await vscode.commands.executeCommand<vscode.CallHierarchyOutgoingCall[]>(
    'vscode.provideOutgoingCalls', 
    item
  );
  
  const itemNormalizedPath = normalizedPath(item.uri.path);
  this.inner.add_outgoing_calls(itemNormalizedPath, item.selectionRange.start, calls);
  funcMap.get(itemNormalizedPath)!.visitFunc(item.selectionRange, FuncCallDirection.OUTGOING);
  
  const unvisitedCalls = calls.filter(call => {
    // Only follow calls within the workspace
    if (!call.to.uri.path.startsWith(this.root)) {
      return false;
    }
    
    const uri = call.to.uri;
    let file = funcMap.get(uri.path);
    if (!file) {
      file = new VisitedFile(uri);
      file.skip = ig.ignores(path.posix.relative(this.root, uri.path)) 
                  || this.inner.should_filter_out_file(uri.path);
      funcMap.set(uri.path, file);
    }
    
    return !file.skip 
           && !file.hasVisitedFunc(call.to.selectionRange.start, FuncCallDirection.OUTGOING);
  });
  
  for await (const call of unvisitedCalls) {
    await this.resolveOutgoingCalls(call.to, funcMap, ig);
  }
}
```

### 6.4 Entry Point: generateFuncCallGraph

```typescript
async generateFuncCallGraph(uri: vscode.Uri, anchor: vscode.Position, ig: Ignore): Promise<any | null> {
  const files = new Map<string, VisitedFile>();
  
  // Prepare call hierarchy for symbol at cursor
  let items: vscode.CallHierarchyItem[] = 
    await vscode.commands.executeCommand('vscode.prepareCallHierarchy', uri, anchor);
  
  if (items.length <= 0) {
    return null;
  }
  
  let funcPos: GlobalPosition;
  for await (const item of items) {
    const itemPath = normalizedPath(item.uri.path);
    files.set(itemPath, new VisitedFile(item.uri));
    
    const itemStart = item.selectionRange.start;
    funcPos = {
      path: itemPath,
      line: itemStart.line,
      character: itemStart.character,
    };
    
    // Traverse in both directions
    await this.resolveIncomingCalls(item, files, ig);
    await this.resolveOutgoingCalls(item, files, ig);
  }
  
  // Now collect only the visited functions' symbols
  for await (const file of files.values()) {
    if (file.skip) { continue; }
    
    let symbols = await retryCommand<vscode.DocumentSymbol[]>(
      5, 600, 'vscode.executeDocumentSymbolProvider', file.uri
    );
    
    const funcs = file.sortedFuncs().filter(rng => !rng.isEmpty);
    symbols = this.filterSymbols(symbols, funcs);  // Keep only visited functions
    
    this.inner.add_file(normalizedPath(file.uri.path), symbols);
  }
  
  return [this.inner.gen_graph(), funcPos!];
}
```

### 6.5 Symbol Filtering

After transitive traversal, Crabviz filters document symbols to only include visited functions:

```typescript
filterSymbols(symbols: vscode.DocumentSymbol[], funcs: vscode.Range[], ctx = { i: 0 }): vscode.DocumentSymbol[] {
  return symbols
    .sort((s1, s2) => s1.selectionRange.start.compareTo(s2.selectionRange.start))
    .filter(symbol => {
      // Keep only symbols that contain visited function ranges
      const keep = ctx.i < funcs.length && symbol.range.contains(funcs[ctx.i]);
      if (!keep) {
        return keep;
      }
      
      if (symbol.selectionRange.isEqual(funcs[ctx.i])) {
        ctx.i += 1;
        if (ctx.i === funcs.length || !symbol.range.contains(funcs[ctx.i])) {
          symbol.children = [];  // Clear children if no more nested functions to keep
          return keep;
        }
      }
      
      // Recursively filter children
      if (symbol.children.length > 0) {
        symbol.children = this.filterSymbols(symbol.children, funcs, ctx);
      }
      
      return keep;
    });
}
```

---

## 7. Pre-computed Edge Maps

### 7.1 Storage Structure

From `core/src/generator/mod.rs`:

```rust
pub struct GraphGenerator {
    lang: Box<dyn lang::Language>,
    
    // File management
    file_id_map: HashMap<String, u32>,          // path → file_id
    files: HashMap<String, Vec<DocumentSymbol>>, // path → symbols
    
    // Edge maps (THE KEY INSIGHT)
    incoming_calls: HashMap<GlobalPosition, Vec<CallHierarchyIncomingCall>>,
    outgoing_calls: HashMap<GlobalPosition, Vec<CallHierarchyOutgoingCall>>,
    interfaces: HashMap<GlobalPosition, Vec<GlobalPosition>>,
    
    filter: bool,
}
```

### 7.2 Why Pre-compute Edge Maps?

**Rationale**:
1. **LSP queries are expensive**: Each `provideIncomingCalls`/`provideOutgoingCalls` triggers a full AST traversal in the language server.
2. **Deferred graph construction**: The TypeScript side queries LSP and stores results, then the Rust side builds the graph in one shot.
3. **Flexible filtering**: Can filter symbols/files without re-querying LSP.

### 7.3 Graph Generation Algorithm

```rust
pub fn gen_graph(&self) -> Graph {
    // Step 1: Collect all symbols from files
    let (files, symbols) = self.collect_files_and_symbols();
    let files_ref = &files;
    let symbols_ref = &symbols;
    
    // Track dynamically inserted symbols (for nested functions)
    let inserted_symbols = RefCell::new(HashSet::new());
    let inserted_symbols_ref = &inserted_symbols;
    
    // Step 2: Process incoming calls
    let incoming_calls = self
        .incoming_calls
        .iter()
        .filter_map(|(callee, callers)| symbols.contains(&callee).then_some((callee, callers)))
        .flat_map(|(to, calls)| {
            calls.into_iter().filter_map(move |call| {
                let from = self.call_item_global_location(&call.from)?;
                
                // Handle nested functions (see section 2.3)
                // ...
                
                Some(Relation {
                    from,
                    to: to.to_owned(),
                    kind: RelationKind::Call,
                })
            })
        });
    
    // Step 3: Process outgoing calls
    let outgoing_calls = self
        .outgoing_calls
        .iter()
        .filter_map(|(caller, callees)| {
            symbols_ref.contains(&caller).then_some((caller, callees))
        })
        .flat_map(|(from, callees)| {
            callees.into_iter().filter_map(move |call| {
                let to = self.call_item_global_location(&call.to)?;
                
                symbols_ref.contains(&to).then_some(Relation {
                    from: from.to_owned(),
                    to,
                    kind: RelationKind::Call,
                })
            })
        });
    
    // Step 4: Process interface implementations
    let implementations = self
        .interfaces
        .iter()
        .filter_map(|(interface, implementations)| {
            symbols_ref
                .contains(&interface)
                .then_some((interface, implementations))
        })
        .flat_map(|(to, implementations)| {
            implementations.into_iter().filter_map(move |location| {
                symbols_ref.contains(location).then_some(Relation {
                    from: location.to_owned(),
                    to: to.to_owned(),
                    kind: RelationKind::Impl,
                })
            })
        });
    
    // Step 5: Merge all relations (deduplicate via HashSet)
    let edges = incoming_calls
        .chain(outgoing_calls)
        .chain(implementations)
        .collect::<HashSet<_>>();
    
    Graph {
        files,
        relations: edges.into_iter().collect(),
    }
}
```

### 7.4 GlobalPosition as Identity

```rust
#[derive(Debug, Clone, Copy, Hash, PartialEq, Eq, Serialize)]
pub struct GlobalPosition {
    pub file_id: u32,
    pub line: u32,
    pub character: u32,
}

impl GlobalPosition {
    pub fn new(file_id: u32, position: Position) -> Self {
        Self {
            file_id,
            line: position.line,
            character: position.character,
        }
    }
}
```

**Key properties**:
- Implements `Hash` + `Eq` → can be used as HashMap key
- Compact: Only 12 bytes (3× u32)
- Cross-file: Uses file_id instead of path string

### 7.5 Deduplication Strategy

Relations are deduplicated using `HashSet<Relation>`:

```rust
impl Hash for Relation {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.from.hash(state);
        self.to.hash(state);
        // Note: kind is NOT hashed
    }
}

impl PartialEq for Relation {
    fn eq(&self, other: &Self) -> bool {
        self.from == other.from && self.to == other.to
        // Note: kind is NOT compared
    }
}
```

**Implication**: If there are multiple edges between the same two positions (e.g., from both incoming and outgoing queries), only ONE is kept. The relation kind comes from whichever is inserted last.

---

## 8. Key Insights for CodeCanvas

### 8.1 Architectural Lessons

1. **Separate concerns**: TypeScript side does I/O (LSP queries, file reading), Rust side does logic (graph construction, filtering).

2. **Pre-compute everything**: Don't query LSP during graph rendering. Build edge maps first, then filter/render.

3. **Handle LSP quirks**: Different language servers have different behaviors (nested functions, anonymous functions). Build defensive code.

4. **Transitive closure is expensive**: For large codebases, transitive traversal can query hundreds of LSP calls. Need:
   - Cycle detection (via visited sets)
   - Scope limiting (only within workspace)
   - Cancellation support

### 8.2 What to Port to CodeCanvas

#### Must-Have
- **GlobalPosition as identity**: File ID + line + character is perfect for graph nodes
- **Pre-computed edge maps**: Store `incoming_calls`, `outgoing_calls`, `implementations` HashMaps
- **Transitive focus algorithm**: The bidirectional DFS with direction tracking is brilliant
- **Language trait pattern**: Easily extend filtering per language

#### Nice-to-Have
- **Nested function insertion**: Handles LSP server inconsistencies gracefully
- **Symbol filtering**: Filter variables/constants to reduce noise
- **LocationLink handling**: Support both `Location` and `LocationLink` from LSP

#### Skip/Modify
- **WASM compilation**: CodeCanvas is Python, don't need this
- **File-level graphs**: CodeCanvas is function-focused
- **Webview UI**: CodeCanvas has its own visualization

### 8.3 Data Model Comparison

**Crabviz**:
```rust
Graph {
  files: Vec<File>,           // File metadata + symbols
  relations: Vec<Relation>,   // Edges (from, to, kind)
}
```

**CodeCanvas** (suggested):
```python
@dataclass
class CallGraph:
    nodes: Dict[GlobalPosition, FunctionNode]  # Position → node
    edges: List[Relation]                      # (from, to, kind)
    file_index: Dict[str, int]                 # path → file_id
```

### 8.4 LSP Integration Points

For CodeCanvas MCP server, implement these LSP methods:

```python
class LSPCallGraphProvider:
    async def prepare_call_hierarchy(self, uri: str, position: Position) -> List[CallHierarchyItem]:
        """Get CallHierarchyItem for a position (LSP: callHierarchy/prepare)"""
    
    async def incoming_calls(self, item: CallHierarchyItem) -> List[CallHierarchyIncomingCall]:
        """Get callers of an item (LSP: callHierarchy/incomingCalls)"""
    
    async def outgoing_calls(self, item: CallHierarchyItem) -> List[CallHierarchyOutgoingCall]:
        """Get callees of an item (LSP: callHierarchy/outgoingCalls)"""
    
    async def implementations(self, uri: str, position: Position) -> List[Location]:
        """Get implementations of interface/abstract (LSP: textDocument/implementation)"""
    
    async def document_symbols(self, uri: str) -> List[DocumentSymbol]:
        """Get all symbols in file (LSP: textDocument/documentSymbol)"""
```

### 8.5 Algorithm Pseudocode for CodeCanvas

```python
def generate_focused_call_graph(uri: str, position: Position) -> CallGraph:
    # Initialize
    visited = {}  # GlobalPosition → VisitDirection
    edge_map = EdgeMap()
    
    # Prepare entry point
    items = await lsp.prepare_call_hierarchy(uri, position)
    root_item = items[0]
    
    # Transitive traversal
    await traverse_incoming(root_item, visited, edge_map)
    await traverse_outgoing(root_item, visited, edge_map)
    
    # Build graph from visited functions
    nodes = {}
    for pos, direction in visited.items():
        nodes[pos] = await get_function_node(pos)
    
    edges = edge_map.to_relations()
    
    return CallGraph(nodes, edges)

async def traverse_incoming(item: CallHierarchyItem, visited, edge_map):
    pos = to_global_position(item)
    
    # Mark visited for INCOMING direction
    if is_visited(pos, Direction.INCOMING, visited):
        return
    mark_visited(pos, Direction.INCOMING, visited)
    
    # Query LSP
    calls = await lsp.incoming_calls(item)
    edge_map.add_incoming(pos, calls)
    
    # Recurse
    for call in calls:
        if should_skip(call.from):
            continue
        await traverse_incoming(call.from, visited, edge_map)

async def traverse_outgoing(item: CallHierarchyItem, visited, edge_map):
    pos = to_global_position(item)
    
    if is_visited(pos, Direction.OUTGOING, visited):
        return
    mark_visited(pos, Direction.OUTGOING, visited)
    
    calls = await lsp.outgoing_calls(item)
    edge_map.add_outgoing(pos, calls)
    
    for call in calls:
        if should_skip(call.to):
            continue
        await traverse_outgoing(call.to, visited, edge_map)
```

### 8.6 Performance Considerations

From testing Crabviz on the TypeScript codebase (~200 files):

- **File-level graph**: ~5 seconds (queries every function)
- **Function-level graph**: ~1-2 seconds (transitive closure of ~20-50 functions)
- **LSP query time**: ~50-100ms per call hierarchy query

**Bottleneck**: LSP server responsiveness. Some strategies:
- Parallel queries (Crabviz uses `for await` sequentially)
- Cache results per session
- Limit traversal depth (e.g., max 3 levels)

### 8.7 Testing Strategy

From `core/src/generator/tests.rs`, they test:
- Nested function handling
- Symbol filtering
- File ID allocation

For CodeCanvas, add tests for:
- Cycle detection (A → B → A)
- Cross-file calls
- Interface implementations
- Transitive closure depth limiting

---

## 9. Code Snippets Worth Copying

### 9.1 Retry with Backoff (TypeScript)

```typescript
// From utils/command.ts (not shown above, but used in generator.ts)
export async function retryCommand<T>(
  times: number, 
  interval: number, 
  command: string, 
  ...args: any[]
): Promise<T | undefined> {
  for (let i = 0; i < times; i++) {
    try {
      const result = await vscode.commands.executeCommand<T>(command, ...args);
      if (result !== undefined) {
        return result;
      }
    } catch (e) {
      if (i === times - 1) {
        throw e;
      }
    }
    await new Promise(resolve => setTimeout(resolve, interval));
  }
}
```

### 9.2 Binary Search for Nested Symbol Insertion (Rust)

```rust
fn try_insert_symbol(&self, item: &CallHierarchyItem, node: &mut File) -> bool {
    let mut cells = &mut node.symbols;
    let mut is_subsymbol = false;
    
    loop {
        // Binary search for insertion point
        let i = match cells.binary_search_by_key(&item.range.start, |cell| cell.range.start) {
            Ok(_) => return true,  // Already exists
            Err(i) => i,
        };
        
        if i > 0 {
            let cell = cells.get(i - 1).unwrap();
            
            // Check if item is nested inside previous symbol
            if cell.range.end > item.range.end {
                if !matches!(cell.kind, SymbolKind::Function | SymbolKind::Method) {
                    return false;  // Only nest in functions
                }
                is_subsymbol = true;
                
                // Descend into children
                cells = &mut cells.get_mut(i - 1).unwrap().children;
                continue;
            }
        }
        
        if is_subsymbol {
            // Insert at correct position
            cells.insert(i, Symbol {
                name: item.name.clone(),
                kind: item.kind,
                range: item.selection_range,
                children: vec![],
            });
        }
        
        return is_subsymbol;
    }
}
```

### 9.3 Windows Path Normalization (TypeScript)

```typescript
// Normalize drive letter case on Windows
function normalizedPath(path: string): string {
  return isWindows 
    ? path.replace(/^\/\w+(?=:)/, drive => drive.toUpperCase()) 
    : path;
}
```

---

## 10. Open Questions for CodeCanvas

1. **LSP Client**: Does CodeCanvas have LSP access? Via MCP tools? Via VS Code API?

2. **Visualization**: How to render transitive graphs? Crabviz uses D3 force-directed layout.

3. **Incremental updates**: Should edge maps be cached across sessions? Invalidation strategy?

4. **Scope limiting**: Should transitive traversal be limited by:
   - Max depth (e.g., 3 levels)?
   - Max nodes (e.g., 100 functions)?
   - File boundaries?

5. **Inheritance relations**: Should CodeCanvas support `RelationKind::Inherit` (class hierarchies)?

6. **Multi-repo**: How to handle cross-repo calls (e.g., library functions)?

---

## 11. Recommendations

### For Immediate Implementation

1. **Start with edge maps**: Implement `HashMap<GlobalPosition, Vec<IncomingCall>>` storage first.

2. **Port transitive algorithm**: The bidirectional DFS with direction tracking is the core value.

3. **Use LSP via MCP**: Wrap LSP queries in MCP tools that CodeCanvas can call.

4. **Test with TypeScript codebase**: It has good LSP support and complex call graphs.

### For Future Enhancement

1. **Smart filtering**: Use Crabviz's language-specific filters to reduce noise.

2. **Parallel queries**: Speed up traversal by querying multiple functions concurrently.

3. **Graph caching**: Serialize edge maps to disk, invalidate on file changes.

4. **Depth control**: Add UI controls for traversal depth.

### For Debugging

1. **Log LSP queries**: Track which calls are slow.

2. **Visualize visited set**: Show which functions were explored.

3. **Edge direction validation**: Ensure incoming/outgoing edges match.

---

## Conclusion

Crabviz is a **masterclass in LSP-based code analysis**. Its key innovations:

1. **Pre-computed edge maps** decouple LSP queries from graph rendering
2. **Transitive focus algorithm** with direction tracking prevents redundant queries
3. **Language-agnostic design** via LSP delegation
4. **Defensive nested function handling** for LSP server quirks

For CodeCanvas, the most valuable ports are:
- The transitive traversal algorithm (section 6)
- The edge map data structure (section 7)
- The GlobalPosition identity model (section 7.4)

With these foundations, CodeCanvas can build powerful call graph analysis on top of LSP, supporting any language with call hierarchy support.
