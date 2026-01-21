# DepViz Technical Review: Code Analysis & Porting Insights

**Date:** 2025-12-16  
**Analyzed Codebase:** `context/depviz/`  
**Purpose:** Extract key techniques for porting to CodeCanvas

---

## 1. Architecture Overview

DepViz is a VSCode extension that creates interactive call graphs for Python/TypeScript/JavaScript codebases. It uses a **dual parsing strategy** (LSP-first, regex-fallback) combined with **client-side edge inference** to build comprehensive dependency graphs.

**Key Components:**
- `src/services/parse/parseService.ts` - Main parsing orchestrator
- `src/services/parse/lspParser.ts` - LSP-based parsing (VS Code symbols)
- `src/services/parse/naiveParser.ts` - Regex-based fallback parser
- `src/services/import/importService.ts` - File importing & change detection
- `media/webview-data.js` - Client-side edge inference (`recomputeMissingEdges`)

**Data Model:**
```typescript
type EdgeType = 'import' | 'call';
type NodeKind = 'module' | 'class' | 'func';

interface GraphNode {
  id: string;           // hashed identifier
  kind: NodeKind;
  label: string;        // display name
  fsPath: string;       // file system path
  parent?: string;      // parent node id (module or class)
  docked?: boolean;     // attached to parent in UI
  source?: string;      // full source code (modules only)
  snippet?: string;     // code snippet (funcs/classes)
  range?: { line: number; col: number };
}

interface GraphEdge {
  from: string;
  to: string;
  type: EdgeType;       // 'import' or 'call'
}
```

---

## 2. Dual Parsing Approach: LSP First, Regex Fallback

### 2.1 Main Orchestration

**File:** `src/services/parse/parseService.ts`

```typescript
export class ParseService {
  async parseFile(uri: vscode.Uri, text: string): Promise<GraphArtifacts> {
    const lsp = await parseWithLsp(uri, text);
    if (lsp) {
      return lsp;  // LSP succeeded
    }
    return parseNaive(uri, text);  // Fallback to regex
  }
}
```

**Strategy:**
1. **Try LSP first** - Uses VSCode's `vscode.executeDocumentSymbolProvider`
2. **Fallback to regex** - If LSP returns no functions or fails entirely
3. **No hybrid** - It's all-or-nothing per file (LSP OR regex, not both)

**Why This Works:**
- LSP provides accurate symbol locations, ranges, and hierarchy
- Regex fallback ensures we still get *something* when LSP fails (unindexed files, large files, language server issues)
- Simple decision boundary: "Did LSP find functions? Yes → use it. No → regex."

---

## 3. Import Edge Detection for Python/JS/TS

Both parsers use **regex-based import detection** (even LSP parser!) because import statements are syntactically simple and regex is faster than LSP for this.

### 3.1 Import Detection in LSP Parser

**File:** `src/services/parse/lspParser.ts`

```typescript
// Python imports
const impPy = /(?:^|\n)\s*(?:from\s+([\w\.]+)\s+import\s+([A-Za-z0-9_\,\s\*\.]+)|import\s+([\w\.]+)(?:\s+as\s+\w+)?)/g;

// TypeScript/JavaScript imports
const impTs = /(?:^|\n)\s*(?:import\s+(?:[^'"]+)\s+from\s+['"]([^'"]+)['"]|import\s+['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\)|export\s+[^;]+?\s+from\s+['"]([^'"]+)['"])/g;

// Extract imports after stripping strings/comments
const importsSource = normalizeContinuations(stripStringsAndComments(text));

while ((match = impPy.exec(importsSource)) !== null) {
  const target = (match[1] ?? match[3] ?? '').trim();
  if (!target) continue;
  const label = resolveImportLabelByText(fileLabel, target, 'py');
  const to = makeModuleId(label ?? target);
  edges.push({ from: moduleId, to, type: 'import' });
}

while ((match = impTs.exec(importsSource)) !== null) {
  const target = (match[1] ?? match[2] ?? match[3] ?? match[4] ?? '').trim();
  if (!target) continue;
  const label = resolveImportLabelByText(fileLabel, target, 'ts');
  const to = makeModuleId(label ?? target);
  edges.push({ from: moduleId, to, type: 'import' });
}
```

**Key Techniques:**

1. **String/Comment Stripping** (`stripStringsAndComments`):
   ```typescript
   export function stripStringsAndComments(src: string): string {
     let s = src;
     s = s.replace(/\/\*[\s\S]*?\*\//g, '');           // /* ... */
     s = s.replace(/(^|[^:])\/\/.*$/gm, '$1');          // // ...
     s = s.replace(/^[ \t]*#.*$/gm, '');                // # ...
     s = s.replace(/("""|''')[\s\S]*?\1/g, '');         // """..."""
     s = s.replace(/'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"/g, '');  // '...' or "..."
     s = s.replace(/`(?:\\.|[^\\`$]|(\$\{[\s\S]*?\}))*`/g, (match) => {
       // Template literals: preserve ${...} expressions
       const parts: string[] = [];
       const re = /\$\{([\s\S]*?)\}/g;
       let k: RegExpExecArray | null;
       while ((k = re.exec(match))) {
         parts.push(k[1]);
       }
       return parts.join(' ');
     });
     return s;
   }
   ```

2. **Continuation Normalization** (Python line continuations):
   ```typescript
   export function normalizeContinuations(src: string): string {
     let s = src.replace(/\\\r?\n/g, ' ');  // backslash continuations
     // Multi-line import parentheses: from x import (a, b, c)
     s = s.replace(/from\s+[\w\.]+\s+import\s*\(([\s\S]*?)\)/g, 
       (match) => match.replace(/\r?\n/g, ' '));
     return s;
   }
   ```

3. **Import Path Resolution** (`resolveImportLabelByText`):
   - Relative imports (`.`, `..`) → resolved to absolute workspace paths
   - Absolute imports → kept as-is for external modules
   - File extension guessing (`.ts`, `.tsx`, `.js`, `.jsx`, `.py`, `__init__.py`)

   ```typescript
   export function resolveImportLabelByText(
     fromLabel: string, 
     spec: string, 
     lang: 'ts' | 'py'
   ): string | null {
     const posixFrom = fromLabel.replace(/\\/g, '/');
     const baseDir = posixFrom.includes('/') 
       ? posixFrom.slice(0, posixFrom.lastIndexOf('/')) 
       : '';
     const rel = (p: string) => normalizePosixPath((baseDir ? `${baseDir}/` : '') + p);

     if (lang === 'ts') {
       if (spec.startsWith('.')) {
         const core = rel(spec);
         if (/\.(ts|tsx|js|jsx)$/i.test(core)) return core;
         // Guess extension
         return `${core}.ts`;  // First candidate
       }
       if (spec.startsWith('/')) {
         const sansLeading = spec.replace(/^\/+/, '');
         const core = normalizePosixPath(sansLeading);
         return /\.(ts|tsx|js|jsx)$/i.test(core) ? core : `${core}.ts`;
       }
       return null;  // External module
     }

     // Python
     if (spec.startsWith('.')) {
       const dots = (spec.match(/^\.+/)?.[0]?.length) || 0;
       const rest = spec.slice(dots).replace(/^\./, '');
       const pops = Math.max(0, dots - 1);
       let parts = baseDir ? baseDir.split('/') : [];
       parts = parts.slice(0, Math.max(0, parts.length - pops));
       const core = normalizePosixPath(parts.join('/') + 
         (rest ? `/${rest.replace(/\./g, '/')}` : ''));
       return `${core}.py`;  // First candidate
     }

     // Absolute Python import: foo.bar.baz -> foo/bar/baz.py
     const core = normalizePosixPath(spec.replace(/\./g, '/'));
     return `${core}.py`;
   }
   ```

**Python Import Patterns Captured:**
- `from foo.bar import baz`
- `import foo.bar`
- `import foo as f`

**TypeScript/JavaScript Import Patterns Captured:**
- `import { x } from 'foo'`
- `import 'foo'`
- `require('foo')`
- `export { x } from 'foo'`

---

## 4. recomputeMissingEdges: Client-Side Call Edge Inference

**File:** `media/webview-data.js`

This is the **secret sauce** - a client-side algorithm that infers missing call edges when LSP/regex parsers miss them.

### 4.1 Full Implementation

```javascript
function recomputeMissingEdges() {
  const funcs = S.data.nodes.filter(n=>n.kind==='func');
  const modules = new Map(S.data.nodes.filter(n=>n.kind==='module').map(m=>[m.id, m]));
  
  // Build name -> functions map
  const nameToFns = new Map();
  for (const f of funcs){
    const nm = (f.label||'').replace(/^.*\s+([A-Za-z_][A-Za-z0-9_]*)\(\).*$/,'$1');
    if (!nm) continue;
    if (!nameToFns.has(nm)) nameToFns.set(nm, []);
    nameToFns.get(nm).push(f);
  }
  
  // Compute import preferences per module by re-parsing module.source
  const importPrefs = new Map(); // moduleId -> Set(moduleId)
  for (const [mid, m] of modules){
    const src = String(m.source || '');
    const targets = new Set();
    
    // Python imports
    src.replace(/^(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))/gm, 
      (_,a,b)=>{ 
        const t=a||b; 
        if (t) targets.add(`mod_${h(t)}`); 
        return ''; 
      });
    
    // TS/JS imports
    src.replace(/^\s*(?:import\s+(?:[^'"\n]+)\s+from\s+['"]([^'"\n]+)['"]|import\s+['"]([^'"\n]+)['"]|const\s+[^=]+=\s*require\(\s*['"]([^'"\n]+)['"]\s*\)|require\(\s*['"]([^'"\n]+)['"]\s*\))/gm, 
      (_,$1,$2,$3)=>{ 
        const t=$1||$2||$3; 
        if (t) targets.add(`mod_${h(t)}`); 
        return ''; 
      });
    
    // Filter to only modules that exist in graph
    const exist = new Set();
    for (const id of targets){ 
      if (modules.has(id)) exist.add(id); 
    }
    importPrefs.set(mid, exist);
  }
  
  const have = new Set(S.data.edges.map(e=>`${e.from}->${e.to}:${e.type}`));
  
  for (const f of funcs){
    const code = String(f.snippet||'');
    
    // Find caller's module (handle class parents)
    const p = D.indices?.nodeMap?.get(f.parent);
    const callerMod = (p && p.kind === 'class') ? p.parent : f.parent;
    const prefMods = importPrefs.get(callerMod) || new Set();
    
    // Extract function call names from snippet
    const names = new Set();
    const KW = /^(new|class|if|for|while|switch|return|function)$/;
    
    // Match: identifier followed by '(' but NOT preceded by '.'
    // This avoids matching obj.method() but captures bareFunction()
    code.replace(/(?<!\.)\b([A-Za-z_][A-Za-z0-9_]*)\s*\(/g, (_,$name)=>{
      const name = String($name);
      if (!KW.test(name)) names.add(name);
      return '';
    });
    
    for (const name of names){
      const cands = nameToFns.get(name) || [];
      if (!cands.length) continue;
      
      let best = null;
      
      // Prefer functions from imported modules
      for (const cand of cands){
        if (cand.id === f.id) continue;  // Skip self-calls
        
        const cp = D.indices?.nodeMap?.get(cand.parent);
        const candMod = (cp && cp.kind === 'class') ? cp.parent : cand.parent;
        
        if (prefMods.has(candMod)) { 
          best = cand; 
          break;  // Found imported function, use it
        }
      }
      
      // Fallback: pick first non-self candidate
      if (!best) best = cands.find(c=>c.id!==f.id) || null;
      
      if (best){ 
        const key = `${f.id}->${best.id}:call`;
        if (!have.has(key)) { 
          S.data.edges.push({ from: f.id, to: best.id, type: 'call' }); 
          have.add(key); 
        } 
      }
    }
  }
}
```

### 4.2 Key Techniques

**A. Import Preference Resolution:**
- For each module, re-parse `module.source` to extract import statements
- Build a `Set<moduleId>` of imported modules
- When multiple functions have the same name, **prefer** functions from imported modules
- This disambiguates `foo()` calls: if module A imports module B, `foo()` likely refers to B's `foo`, not some random `foo` from module C

**B. Negative Lookbehind for Method Calls:**
```javascript
// (?<!\.)\b([A-Za-z_][A-Za-z0-9_]*)\s*\(
//  ^^^^
//  Negative lookbehind: don't match if preceded by '.'
//
// Matches:   foo()  ✅
// Skips:     obj.foo()  ❌
```

**C. Keyword Filtering:**
```javascript
const KW = /^(new|class|if|for|while|switch|return|function)$/;
if (!KW.test(name)) names.add(name);
```
Avoids false positives from language keywords.

**D. Deduplication:**
```javascript
const have = new Set(S.data.edges.map(e=>`${e.from}->${e.to}:${e.type}`));
const key = `${f.id}->${best.id}:call`;
if (!have.has(key)) { /* ... */ }
```
Prevents duplicate edges.

**E. Hash Function:**
```javascript
function h(s){
  let h = 2166136261 >>> 0;  // FNV-1a offset basis
  for (let i=0;i<s.length;i++){ 
    h ^= s.charCodeAt(i); 
    h = Math.imul(h, 16777619);  // FNV-1a prime
  }
  return (h>>>0).toString(16);
}
```
FNV-1a hash for fast, collision-resistant IDs.

---

## 5. Import Preference Resolution Deep Dive

**Problem:** When multiple functions share the same name, which one does a call refer to?

**Solution:** Prefer functions from **imported modules**.

### 5.1 Algorithm

```
For each function call `foo()` in function `caller`:
  1. Find caller's module M
  2. Get all imported modules {M1, M2, ...} from M's source
  3. Find all functions named `foo` in graph
  4. If any `foo` is in M1, M2, ..., pick that one (first match)
  5. Otherwise, pick the first `foo` that isn't `caller` itself
```

### 5.2 Example

```python
# module_a.py
from module_b import helper

def main():
    helper()  # Which helper()?
```

```python
# module_b.py
def helper():
    pass
```

```python
# module_c.py
def helper():
    pass
```

**Without import preference:** Ambiguous - could link `main` → `module_b.helper` OR `module_c.helper`

**With import preference:** 
1. `module_a` imports `module_b`
2. `helper()` call in `main` → prefer `module_b.helper`
3. Edge: `main` → `module_b.helper` ✅

**Fallback:** If `module_a` didn't import anything, we'd still create an edge to *some* `helper`, just picking the first one found (better than nothing).

---

## 6. Naive Parser Fallback Implementation

**File:** `src/services/parse/naiveParser.ts`

The naive parser uses **pure regex** to extract functions, classes, and imports when LSP fails.

### 6.1 Function Detection

```typescript
const pyDef = /^\s*def\s+([a-zA-Z_\d]+)\s*\(/;
const tsDef = /^\s*(?:export\s+)?function\s+([a-zA-Z_\d]+)\s*\(/;
const tsVarFn = /^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_\d]+)\s*=\s*(?:async\s*)?(?:function\s*\(|\([^)]*\)\s*=>)/;

for (let i = 0; i < lines.length; i++) {
  const line = lines[i];
  const indent = (line.match(/^\s*/)?.[0]?.length) || 0;

  const fnMatch = pyDef.exec(line) || tsDef.exec(line) || tsVarFn.exec(line);
  if (fnMatch) {
    const name = fnMatch[1] || fnMatch[2] || fnMatch[3];
    const id = makeFuncId(fileLabel, name, i);
    // ... add to functions list
  }
}
```

**Patterns Matched:**
- Python: `def foo():`
- TypeScript: `function foo()`, `export function foo()`
- JavaScript: `const foo = () => {}`, `const foo = async function() {}`

### 6.2 Class Detection with Indentation Tracking

```typescript
const pyClass = /^\s*class\s+([A-Za-z_\d]+)\s*[:(]/;
const classStack: Array<{ name: string; indent: number; id: string }> = [];

for (let i = 0; i < lines.length; i++) {
  const line = lines[i];
  const indent = (line.match(/^\s*/)?.[0]?.length) || 0;

  // Pop classes from stack when indent decreases
  while (classStack.length && indent <= classStack[classStack.length - 1].indent) {
    classStack.pop();
  }

  const classMatch = pyClass.exec(line);
  if (classMatch) {
    const className = classMatch[1];
    const classId = makeClassId(fileLabel, className);
    classStack.push({ name: className, indent, id: classId });
    // ... add class node
    continue;
  }

  const fnMatch = /* ... */;
  if (fnMatch) {
    let parent: string | undefined;
    let labelName = name;
    if (classStack.length) {
      // Function is inside a class
      const top = classStack[classStack.length - 1];
      parent = top.id;
      labelName = `${top.name}.${name}`;
    }
    // ... add function with parent
  }
}
```

**Indentation-Based Scope Tracking:**
- Python uses indentation for scope
- Maintain a stack of classes based on indent level
- When indent decreases, pop classes from stack
- Functions inherit the current class as parent

### 6.3 Function Body Range Estimation

```typescript
for (let i = 0; i < fns.length - 1; i++) {
  fns[i].end = fns[i + 1].start - 1;
}
```

**Heuristic:** A function's body ends where the next function starts.

**Limitation:** Last function in file gets `end = lines.length`, which is fine.

### 6.4 Call Edge Detection (Naive)

```typescript
const nameToId = new Map<string, string>();
const callRegex = new Map<string, RegExp>();
const wcr = (token: string) => new RegExp(String.raw`\b${escapeReg(token)}\s*\(`);
const bareTokOf = (value: string) => 
  (value.includes('.') ? value.split('.').pop() || value : value);

for (const fn of fns) {
  nameToId.set(fn.name, fn.id);
  callRegex.set(fn.name, wcr(fn.name));
}

for (const fn of fns) {
  const body = stripStringsAndComments(lines.slice(fn.start, fn.end + 1).join('\n'));
  for (const [calleeName, calleeId] of nameToId) {
    if (calleeName === fn.name) continue;
    
    const full = callRegex.get(calleeName) ?? wcr(calleeName);
    const bare = wcr(bareTokOf(calleeName));
    
    if (full.test(body) || bare.test(body)) {
      edges.push({ from: fn.id, to: calleeId, type: 'call' });
    }
  }
}
```

**Approach:**
1. Strip strings/comments from function body
2. For each other function name, check if it appears as a call: `name(`
3. Also check "bare" name (e.g., for `Class.method`, check both `Class.method(` and `method(`)
4. Create call edge if match found

**Limitation:** No import preference resolution in naive parser - just name matching.

---

## 7. Edge Type Handling: Import vs. Call

### 7.1 Edge Type Semantics

```typescript
type EdgeType = 'import' | 'call';
```

**Import edges:**
- Module → Module
- Created from `import`/`from...import`/`require` statements
- Represents static dependencies (visible in AST/source text)

**Call edges:**
- Function → Function
- Created from function call detection (regex-based)
- Represents dynamic runtime dependencies (approximate, best-effort)

### 7.2 Special Case: Module → Function Import Filtering

**File:** `media/webview-data.js`, in `mergeArtifacts`:

```javascript
for (const e of (payload.edges || [])) {
  const key = `${e.from}->${e.to}:${e.type}`;
  const from = S.data.nodes.find(n=>n.id===e.from);
  const to = S.data.nodes.find(n=>n.id===e.to);
  
  // Skip module → function import edges where function is in that module
  if (from && to && 
      from.kind==='module' && 
      to.kind==='func' && 
      to.parent===from.id && 
      e.type==='import') {
    continue;  // Don't add this edge
  }
  
  if (!ekeys.has(key)) { 
    S.data.edges.push(e); 
    ekeys.add(key); 
  }
}
```

**Why:** Prevents redundant edges like `module_a` → `func_in_module_a` of type `import`. The `func.parent` relationship already captures this hierarchy.

### 7.3 Edge Visibility Toggle

Users can toggle edge types on/off in the UI:
- `typeVisibility.import` - Show/hide import edges
- `typeVisibility.call` - Show/hide call edges

This is useful for reducing visual clutter (e.g., hide imports to see only call graph).

---

## 8. Key Insights for Porting to CodeCanvas

### 8.1 Architectural Patterns to Adopt

#### A. Dual Parsing Strategy
```python
# CodeCanvas implementation suggestion
class Parser:
    async def parse_file(self, path: str, text: str) -> GraphArtifacts:
        # Try LSP first (via tree-sitter or language server)
        artifacts = await self.parse_with_lsp(path, text)
        if artifacts and artifacts.functions:
            return artifacts
        
        # Fallback to regex
        return self.parse_naive(path, text)
```

**Decision criterion:** If LSP finds ≥1 function, use it. Otherwise, regex fallback.

#### B. Import Preference Resolver
```python
class ImportResolver:
    def resolve_call_target(
        self, 
        caller_func: FuncNode, 
        call_name: str, 
        candidates: List[FuncNode],
        graph: Graph
    ) -> FuncNode | None:
        """Prefer functions from imported modules."""
        caller_module = self.get_module(caller_func, graph)
        imported_modules = self.get_imports(caller_module, graph)
        
        # First pass: prefer imported modules
        for candidate in candidates:
            if candidate == caller_func:
                continue
            cand_module = self.get_module(candidate, graph)
            if cand_module in imported_modules:
                return candidate
        
        # Fallback: pick first non-self candidate
        for candidate in candidates:
            if candidate != caller_func:
                return candidate
        
        return None
```

#### C. Client-Side Edge Inference (Optional)

If CodeCanvas has a web UI, consider deferring `recomputeMissingEdges` to client-side:
- Keeps server-side parsing fast
- Allows UI to progressively enhance edges
- User can toggle "inferred edges" on/off

For MCP server (headless), this should be server-side:
```python
def recompute_missing_edges(graph: Graph) -> None:
    """Server-side implementation of edge inference."""
    # ... similar logic to webview-data.js
```

### 8.2 String/Comment Stripping

**Critical for accurate parsing.** Port this logic to Python:

```python
import re

def strip_strings_and_comments(source: str) -> str:
    """Remove strings, comments, and template literals."""
    s = source
    
    # Block comments: /* ... */
    s = re.sub(r'/\*[\s\S]*?\*/', '', s)
    
    # Line comments: // ...  (but not http://)
    s = re.sub(r'(^|[^:])//.*$', r'\1', s, flags=re.MULTILINE)
    
    # Python comments: # ...
    s = re.sub(r'^[ \t]*#.*$', '', s, flags=re.MULTILINE)
    
    # Triple-quoted strings: """...""" or '''...'''
    s = re.sub(r'("""|\'\'\'[\s\S]*?\1', '', s)
    
    # Regular strings: "..." or '...'
    s = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", '', s)
    
    # Template literals: `...` (extract ${...} expressions)
    def template_handler(match):
        parts = re.findall(r'\$\{([\s\S]*?)\}', match.group(0))
        return ' '.join(parts)
    
    s = re.sub(r'`(?:\\.|[^\\`$]|(\$\{[\s\S]*?\}))*`', template_handler, s)
    
    return s
```

### 8.3 Import Path Resolution

**Key insight:** File path resolution is **approximate** - we guess the first candidate.

```python
def resolve_import_path(
    from_path: str, 
    import_spec: str, 
    lang: Literal['py', 'ts']
) -> str | None:
    """Resolve import to a file path."""
    if lang == 'ts':
        if import_spec.startswith('.'):
            # Relative: ./foo, ../bar
            resolved = resolve_relative(from_path, import_spec)
            candidates = [
                f"{resolved}.ts",
                f"{resolved}.tsx",
                f"{resolved}.js",
                f"{resolved}.jsx",
                f"{resolved}/index.ts",
            ]
            return candidates[0]  # Guess first
        if import_spec.startswith('/'):
            # Absolute: /foo/bar
            return f"{import_spec.lstrip('/')}.ts"
        return None  # External module (node_modules)
    
    # Python
    if import_spec.startswith('.'):
        # Relative: .foo, ..bar
        resolved = resolve_relative_python(from_path, import_spec)
        return f"{resolved}.py"
    
    # Absolute: foo.bar.baz -> foo/bar/baz.py
    return f"{import_spec.replace('.', '/')}.py"
```

**Trade-off:** We don't check if files exist (filesystem I/O). We just create edges to *probable* paths. If the target file is imported later, the edge will connect. If not, it's a dangling edge (acceptable - shows external dependency).

### 8.4 Function Call Detection Regex

**Key pattern:** Word boundary + identifier + optional whitespace + `(`

```python
# Python/TypeScript/JavaScript universal pattern
CALL_PATTERN = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\(')

# Exclude method calls (negative lookbehind for '.')
BARE_CALL_PATTERN = re.compile(r'(?<!\.)b([A-Za-z_][A-Za-z0-9_]*)\s*\(')

# Keyword exclusion
KEYWORDS = {'new', 'class', 'if', 'for', 'while', 'switch', 'return', 'function', 
            'def', 'async', 'await', 'import', 'from', 'export'}

def extract_calls(code: str) -> Set[str]:
    """Extract function call names from code."""
    stripped = strip_strings_and_comments(code)
    calls = set()
    
    for match in BARE_CALL_PATTERN.finditer(stripped):
        name = match.group(1)
        if name not in KEYWORDS:
            calls.add(name)
    
    return calls
```

### 8.5 Indentation-Based Scope Tracking (Python)

```python
class ClassScope:
    def __init__(self, name: str, indent: int, id: str):
        self.name = name
        self.indent = indent
        self.id = id

def parse_python_classes(lines: List[str]) -> List[ClassNode]:
    """Parse Python classes using indentation."""
    class_stack: List[ClassScope] = []
    classes = []
    
    CLASS_RE = re.compile(r'^\s*class\s+([A-Za-z_\d]+)\s*[:(]')
    
    for i, line in enumerate(lines):
        indent = len(line) - len(line.lstrip())
        
        # Pop classes when indent decreases
        while class_stack and indent <= class_stack[-1].indent:
            class_stack.pop()
        
        match = CLASS_RE.match(line)
        if match:
            name = match.group(1)
            id = make_class_id(name, i)
            scope = ClassScope(name, indent, id)
            class_stack.append(scope)
            classes.append(ClassNode(id=id, name=name, line=i))
    
    return classes
```

### 8.6 Hash-Based ID Generation

```python
def fnv1a_hash(s: str) -> str:
    """FNV-1a hash (same as DepViz)."""
    h = 2166136261  # offset basis
    for c in s:
        h ^= ord(c)
        h = (h * 16777619) & 0xFFFFFFFF  # 32-bit
    return format(h, 'x')  # hex string

def make_func_id(file_path: str, func_name: str, line: int) -> str:
    return f"fn_{fnv1a_hash(f'{file_path}:{func_name}:{line}')}"

def make_class_id(file_path: str, class_name: str) -> str:
    return f"cls_{fnv1a_hash(f'{file_path}:{class_name}')}"

def make_module_id(file_path: str) -> str:
    return f"mod_{fnv1a_hash(file_path)}"
```

**Why FNV-1a:** Fast, simple, good distribution for short strings.

### 8.7 Edge Deduplication

```python
class Graph:
    def __init__(self):
        self.nodes: List[Node] = []
        self.edges: List[Edge] = []
        self._edge_keys: Set[str] = set()
    
    def add_edge(self, from_id: str, to_id: str, edge_type: EdgeType) -> bool:
        """Add edge if not duplicate. Returns True if added."""
        key = f"{from_id}->{to_id}:{edge_type}"
        if key in self._edge_keys:
            return False
        
        self.edges.append(Edge(from_id=from_id, to_id=to_id, type=edge_type))
        self._edge_keys.add(key)
        return True
```

### 8.8 Performance Considerations

**File Size Limits:**
```python
MAX_FILE_SIZE_MB = 1.5  # Skip files larger than this
MAX_FILES = 2000        # Hard cap on imports

def should_skip_file(path: str, size: int) -> bool:
    if size > MAX_FILE_SIZE_MB * 1_000_000:
        return True
    
    # Skip binary/build artifacts
    SKIP_EXTS = {'.min.js', '.map', '.pyc', '.so', '.dll', '.class'}
    if any(path.endswith(ext) for ext in SKIP_EXTS):
        return True
    
    return False
```

**Batch Processing:**
```python
async def import_files(paths: List[str]) -> Graph:
    """Import files in parallel batches."""
    graph = Graph()
    batch_size = 8
    
    for i in range(0, len(paths), batch_size):
        batch = paths[i:i+batch_size]
        results = await asyncio.gather(*[parse_file(p) for p in batch])
        
        for artifacts in results:
            graph.merge(artifacts)
    
    # Post-processing: infer missing edges
    recompute_missing_edges(graph)
    
    return graph
```

### 8.9 Testing Strategy

**Unit tests for each component:**
```python
def test_strip_strings_and_comments():
    source = '''
    def foo():
        # This is a comment
        s = "string with # not a comment"
        return bar()  // another comment
    '''
    
    stripped = strip_strings_and_comments(source)
    
    assert '# This is a comment' not in stripped
    assert '// another comment' not in stripped
    assert '"string' not in stripped
    assert 'bar()' in stripped  # Actual code preserved

def test_import_preference():
    graph = Graph()
    graph.add_node(module('mod_a', source='from mod_b import helper'))
    graph.add_node(module('mod_b'))
    graph.add_node(module('mod_c'))
    graph.add_node(func('helper_b', parent='mod_b'))
    graph.add_node(func('helper_c', parent='mod_c'))
    graph.add_node(func('main', parent='mod_a', snippet='helper()'))
    
    resolver = ImportResolver()
    candidates = [graph.get_node('helper_b'), graph.get_node('helper_c')]
    
    result = resolver.resolve_call_target(
        caller_func=graph.get_node('main'),
        call_name='helper',
        candidates=candidates,
        graph=graph
    )
    
    assert result.id == 'helper_b'  # Prefer imported module
```

---

## 9. Limitations & Trade-offs

### 9.1 DepViz Limitations

1. **Name-based call resolution** - No type checking
   - If two modules have `def foo()`, calls to `foo()` are ambiguous
   - Import preference helps but isn't perfect
   - **CodeCanvas impact:** Same limitation applies. Consider LSP `findReferences` for precise call graph (slower).

2. **Regex fragility** - Language syntax changes break parsers
   - **Mitigation:** Use tree-sitter for robust parsing (CodeCanvas already does this)

3. **No cross-language edges** - Python → TypeScript calls not detected
   - **CodeCanvas impact:** If supporting polyglot repos, need special handling (e.g., HTTP API calls, FFI)

4. **Template literals / f-strings** - Code inside templates may be missed
   - DepViz extracts `${...}` expressions but doesn't parse them
   - **CodeCanvas:** tree-sitter handles this better

5. **Dynamic imports** - `import(foo)`, `__import__(bar)` not detected
   - **CodeCanvas:** Accept this limitation for now, or add special cases

### 9.2 Trade-offs to Consider

| Aspect | DepViz Approach | CodeCanvas Alternative |
|--------|----------------|----------------------|
| **Parsing** | LSP → regex fallback | tree-sitter → LSP fallback? |
| **Call edges** | Regex + import prefs | LSP `findReferences` (slow but accurate) |
| **Import resolution** | Guess first candidate | Stat filesystem? (slower) |
| **Edge inference** | Client-side JS | Server-side Python (MCP) |
| **Scope tracking** | Indentation (Python) | tree-sitter CST |

**Recommendation:** Start with DepViz's approach (fast, good enough), then optimize hot paths with tree-sitter/LSP.

---

## 10. Implementation Checklist for CodeCanvas

- [ ] **Parser infrastructure**
  - [ ] Dual parsing: LSP first, regex fallback
  - [ ] String/comment stripping utility
  - [ ] Import path resolver (Python + TS/JS)
  - [ ] Function call extractor (regex-based)

- [ ] **Graph building**
  - [ ] Node ID generation (FNV-1a hash)
  - [ ] Edge deduplication
  - [ ] Import edge detection
  - [ ] Call edge detection
  - [ ] `recomputeMissingEdges` implementation

- [ ] **Import preference resolver**
  - [ ] Module import map builder
  - [ ] Call target disambiguation

- [ ] **Naive parser (regex fallback)**
  - [ ] Python: `def`, `class` detection
  - [ ] TypeScript: `function`, `const x = () => {}` detection
  - [ ] Indentation-based scope tracking (Python)
  - [ ] Function body range estimation

- [ ] **Testing**
  - [ ] Unit tests for string stripping
  - [ ] Unit tests for import resolution
  - [ ] Integration tests: small repo → full graph
  - [ ] Edge case tests: name collisions, circular imports

- [ ] **Performance**
  - [ ] File size limits
  - [ ] Batch processing
  - [ ] Skip binary/build artifacts

- [ ] **Edge types**
  - [ ] Import edges (module → module)
  - [ ] Call edges (function → function)
  - [ ] Filter redundant module → function import edges

---

## 11. Code Snippets for Quick Reference

### String Stripping (Python)
```python
import re

def strip_strings_and_comments(src: str) -> str:
    s = src
    s = re.sub(r'/\*[\s\S]*?\*/', '', s)
    s = re.sub(r'(^|[^:])//.*$', r'\1', s, flags=re.MULTILINE)
    s = re.sub(r'^[ \t]*#.*$', '', s, flags=re.MULTILINE)
    s = re.sub(r'("""|\'\'\'[\s\S]*?\1', '', s)
    s = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", '', s)
    return s
```

### Function Call Extraction
```python
CALL_RE = re.compile(r'(?<!\.)b([A-Za-z_][A-Za-z0-9_]*)\s*\(')
KEYWORDS = {'new', 'if', 'for', 'while', 'return', 'function', 'def'}

def extract_calls(code: str) -> Set[str]:
    stripped = strip_strings_and_comments(code)
    return {m.group(1) for m in CALL_RE.finditer(stripped) 
            if m.group(1) not in KEYWORDS}
```

### Import Preference Resolver
```python
def resolve_with_import_pref(
    caller_module: str,
    call_name: str,
    candidates: List[FuncNode],
    graph: Graph
) -> FuncNode | None:
    imports = get_imported_modules(caller_module, graph)
    
    for cand in candidates:
        if get_module(cand, graph) in imports:
            return cand
    
    return candidates[0] if candidates else None
```

### FNV-1a Hash
```python
def fnv1a(s: str) -> str:
    h = 2166136261
    for c in s:
        h = ((h ^ ord(c)) * 16777619) & 0xFFFFFFFF
    return format(h, 'x')
```

---

## 12. Final Recommendations

1. **Start simple:** Implement regex-based parsing first (faster to build, easier to debug)
2. **Add LSP later:** Once regex works, add LSP as an enhancement (better accuracy)
3. **Test incrementally:** Parse single file → small repo → large repo
4. **Profile performance:** Track parse time per file, identify bottlenecks
5. **Handle failures gracefully:** If a file fails to parse, log error and continue (don't crash entire graph build)
6. **Import preference is key:** This is what makes call edge disambiguation actually useful
7. **Deduplicate edges:** Essential to avoid graph bloat
8. **Skip large files:** 1.5 MB limit is reasonable (large files are usually generated/minified)

---

**End of Review**

This review captures the essential techniques from DepViz. The client-side `recomputeMissingEdges` function is particularly clever - it's a post-processing step that fixes gaps left by the initial parse. For CodeCanvas, we can implement this server-side in Python, using the same algorithms.

The import preference resolution is the secret sauce that makes name-based call detection viable. Without it, function name collisions would create too many false edges. With it, the graph is surprisingly accurate for a regex-based approach.

**Next steps:** Port the string stripping, import resolution, and call extraction logic to CodeCanvas's Python backend. Start with naive parser (pure regex), then add tree-sitter/LSP enhancements once the baseline works.
