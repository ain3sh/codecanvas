# CodeCanvas: Visual Impact Analysis for Agentic Workflows

CodeCanvas is an MCP (Model Context Protocol) tool that provides LLM agents with visual codebase analysis, impact tracking, and persistent reasoning state. It addresses the fundamental problem of "side-effect blindness" in code-editing agents by making blast radius explicit and trackable.

## Table of Contents

1. [Motivation](#motivation)
2. [Core Concepts](#core-concepts)
3. [Architecture](#architecture)
4. [Graph Model](#graph-model)
5. [Parsing Pipeline](#parsing-pipeline)
6. [Impact Analysis](#impact-analysis)
7. [Views](#views)
8. [MCP Tool Reference](#mcp-tool-reference)
9. [Agent UX Design](#agent-ux-design)
10. [Hooks](#hooks)
11. [Integration](#integration)
12. [Key Design Decisions](#key-design-decisions)

---

## Motivation

### The Side-Effect Blindness Problem

LLM agents editing code face a critical limitation: they cannot see the consequences of their changes. When an agent modifies function `foo()`, it has no way to know:

- What other functions call `foo()`?
- What will break if `foo()`'s signature changes?
- How many tests depend on `foo()`'s current behavior?

This "side-effect blindness" leads to:
- Cascading bugs from untracked dependencies
- Incomplete refactors that break callers
- Wasted iterations fixing downstream failures

### The Small Model Problem

Large models (Opus, GPT-4) can sometimes infer workflow patterns from context. Small models (Haiku, smaller fine-tunes) cannot. They need explicit guidance:

- What action should I take next?
- What information is relevant right now?
- How do I know when I'm done?

Without this guidance, small models thrash, repeat actions, or miss critical steps.

### The Context Window Problem

Multi-step tasks often exceed context windows. When context compacts:
- Prior analysis is lost
- Reasoning chains break
- The agent "forgets" what it already figured out

Agents need persistent external memory that survives compaction.

### CodeCanvas Solution

CodeCanvas addresses all three problems:

1. **Blast Radius Visualization**: `impact` action shows callers/callees before changes
2. **Explicit Workflow Guidance**: Response texts include next-step hints
3. **Evidence Board**: Persistent scratchpad for claims, evidence, and decisions

---

## Core Concepts

### Evidence

Visual artifacts capturing analysis state. Each evidence item has:
- **ID**: Sequential identifier (E1, E2, ...)
- **Kind**: `architecture` (init) or `impact` (analysis)
- **PNG**: Rendered visualization
- **Symbol**: Target of analysis (for impact evidence)
- **Metrics**: Node count, edge count, depth
- **Metrics**: Depth plus view-specific counts (e.g., callers/callees, nodes/edges shown)
### Claims

Agent assertions linked to evidence:
- **Hypothesis**: "Changing X may break Y"
- **Finding**: "X depends on Y via Z"
- **Question**: "Does X handle null inputs?"

Claims auto-link to the most recent evidence, creating an audit trail.

### Decisions

Committed plans or verified outcomes:
- **Plan**: "Will refactor X, then update Y's tests"
- **Test**: "Verify X with unit tests"
- **Edit**: "Change X's signature from A to B"
- **Mark**: "X verified via tests" (verification complete)
- **Skip**: "X out of scope" (intentionally ignored)

### Focus

The current symbol being analyzed. Set automatically by `impact`, used to track which symbol's blast radius is active. Enables progress tracking ("3/7 affected nodes addressed").

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              MCP Server                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                     │
│  │   canvas    │  │   canvas    │  │   canvas    │                     │
│  │ action=init │  │action=impact│  │ action=...  │                     │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                     │
│         │                │                │                             │
│         ▼                ▼                ▼                             │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                       State Manager                              │   │
│  │  - CanvasState (evidence, claims, decisions, focus)             │   │
│  │  - Persistence to .codecanvas/state.json                        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│         │                │                │                             │
│         ▼                ▼                ▼                             │
│  ┌────────────────────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │          Parser            │  │  Analyzer   │  │    Views    │      │
│  │  ┌───────────────────────┐ │  │ (Slicing)   │  │  (SVG/PNG)  │      │
│  │  │      LspSession       │ │  └─────────────┘  └─────────────┘      │
│  │  │  ┌─────────────────┐  │ │                                        │
│  │  │  │ MultilspyBackend│  │ │  (10 languages, auto-download)        │
│  │  │  └─────────────────┘  │ │                                        │
│  │  │  ┌─────────────────┐  │ │                                        │
│  │  │  │ CustomLspBackend│  │ │  (extensible via LANGUAGE_SERVERS)    │
│  │  │  └─────────────────┘  │ │                                        │
│  │  └───────────────────────┘ │                                        │
│  │  ┌───────────────────────┐ │                                        │
│  │  │   treesitter.py +     │ │  (declarative .scm queries)           │
│  │  │   schemas/*.scm       │ │                                        │
│  │  └───────────────────────┘ │                                        │
│  └────────────────────────────┘                                        │
└─────────────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Responsibility |
|-----------|----------------|
| **MCP Server** | Tool registration, request routing, response formatting |
| **State Manager** | Evidence board state, persistence, focus tracking |
| **Parser** | Code parsing (multilspy LSP + tree-sitter fallback), graph construction, call edge inference |
| **Analyzer** | Impact slicing, neighborhood extraction, symbol search |
| **Views** | SVG rendering, PNG conversion, layout algorithms |
| **Schemas** | Declarative `.scm` query files for tree-sitter extraction |

---

## Graph Model

CodeCanvas builds an in-memory graph representing codebase structure.

### Node Types

| Kind | Description | Example |
|------|-------------|---------|
| `MODULE` | File/module | `utils.py`, `src/lib.ts` |
| `CLASS` | Class definition | `class Parser`, `interface Config` |
| `FUNC` | Function/method | `def parse()`, `async function fetch()` |

### Edge Types

| Type | Meaning | Source |
|------|---------|--------|
| `IMPORT` | Module imports module | Static analysis |
| `CALL` | Function calls function | Tree-sitter call sites + LSP definitions |
| `CONTAINS` | Parent contains child | AST structure |

### Node Properties

```python
@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: NodeKind          # MODULE, CLASS, FUNC
    label: str              # Display name
    fsPath: str             # Absolute path
    snippet: str | None
    start_line: int | None  # 0-indexed (LSP/tree-sitter)
    start_char: int | None
    end_line: int | None
    end_char: int | None
```

Containment is modeled exclusively via `CONTAINS` edges (nodes do not store a `parent` field).

### Edge Properties

```python
@dataclass  
class GraphEdge:
    from_id: str      # Source node ID
    to_id: str        # Target node ID
    type: EdgeType    # IMPORT, CALL, CONTAINS
```

---

## Parsing Pipeline

CodeCanvas uses a two-phase parsing strategy: LSP-first with tree-sitter fallback.

### Phase 1: LSP Parsing (Dual-Backend Architecture)

The Language Server Protocol provides accurate symbol information. CodeCanvas uses a **dual-backend architecture** that routes requests to the appropriate LSP implementation:

```python
# LspSession routes to appropriate backend based on language
if lang in MULTILSPY_LANGUAGES:
    backend = MultilspyBackend(lang, workspace_root)    # 10 languages, auto-download
elif lang in LANGUAGE_SERVERS:
    backend = CustomLspBackend(lang, workspace_root, cmd)  # Extensible fallback
```

**Backend 1: MultilspyBackend (Primary)**
- Uses Microsoft's `multilspy` library for 10 languages
- Auto-downloads and manages LSP binaries (first run only)
- Languages: Python, TypeScript, Go, Rust, Java, Ruby, C/C++, C#, Kotlin, Dart

**Backend 2: CustomLspBackend (Fallback/Extension)**
- Full JSON-RPC LSP client for languages not in multilspy
- Configured via `LANGUAGE_SERVERS` dict in `parser/config.py`
- Currently configured: Bash (`bash-language-server`), R (`languageserver`)
- **Extensible**: Add any LSP server by adding to `LANGUAGE_SERVERS`

```python
# parser/config.py - Extension point for custom LSP servers
LANGUAGE_SERVERS: Dict[str, Dict[str, Any]] = {
    "sh": {"cmd": ["bash-language-server", "start"]},
    "r": {"cmd": ["R", "--slave", "-e", "languageserver::run()"]},
    # Add more languages here...
}
```

**Both backends implement the same protocol:**
```
1. Initialize with workspace root
2. Request textDocument/documentSymbol for each file
3. Build nodes from symbol hierarchy
4. Infer CONTAINS edges from parent-child relationships
```

**Advantages:**
- Semantically accurate (understands imports, types, scopes)
- Zero-config for multilspy languages (auto-download)
- Extensible to any language with an LSP server
- Handles complex patterns (decorators, metaclasses, generics)

**Limitations:**
- Slower startup (server initialization)
- May fail on malformed code

### Phase 2: Tree-Sitter Fallback (Three-Tier Extraction)

When LSP fails or is unavailable, tree-sitter provides AST-based parsing with a **three-tier extraction strategy**:

**Tier 1: Custom Schemas (Full Extraction)**
For languages with `.scm` schema files, full extraction of definitions, imports, and call sites:

```
1. Load tree-sitter grammar via tree-sitter-language-pack
2. Parse file into syntax tree
3. Execute .scm query against AST (declarative pattern matching)
4. Extract captures: @cc.def.class.*, @cc.def.func.*, @cc.import.*, @cc.call.*
5. Build nodes from captured positions
```

**Tier 2: Generic Fallback (Basic Definitions)**
For ANY language in tree-sitter-language-pack (~50+ languages) without a custom schema:

```python
_GENERIC_DEF_QUERY = "(_ name: (_) @name) @node"
# Matches any AST node with a "name" field, then classifies:
# - Node type contains "class/struct/interface/enum/trait/module" → class
# - Node type contains "function/method/constructor" → func
```

This provides basic definition extraction for languages like Scala, Elixir, Haskell, OCaml, Lua, etc. - no schema required!

**Tier 3: Unsupported**
Languages not in tree-sitter-language-pack return no tree-sitter results (LSP-only or skip).

**Architecture:**
```
codecanvas/parser/
  treesitter.py          # Unified extraction engine (~500 lines)
  schemas/               # Custom query schemas (Tier 1)
    python.scm
    typescript.scm
    tsx.scm
    javascript.scm
    go.scm
    rust.scm
    java.scm
    ruby.scm
    c.scm
    cpp.scm
    bash.scm
```

**Query Capture Names (standardized across custom schemas):**
- `@cc.def.class.node` / `@cc.def.class.name` - Class definitions
- `@cc.def.func.node` / `@cc.def.func.name` - Function definitions
- `@cc.import.spec` - Import paths
- `@cc.call.target` - Call site targets

**Extraction Capabilities by Tier:**
| Tier | Definitions | Imports | Call Sites | Languages |
|------|-------------|---------|------------|-----------|
| Custom Schema | ✓ Full | ✓ | ✓ | 8 lang keys (11 schema files) |
| Generic Fallback | ✓ Basic | ✗ | ✗ | ~50+ (any in tree-sitter-language-pack) |
| Unsupported | ✗ | ✗ | ✗ | Others |

**Advantages:**
- Fast (native parsing via tree-sitter-language-pack)
- Robust (handles partial/broken code)
- Declarative (language variation is data, not code)
- Easy to extend (add a `.scm` file for full support)
- Wide coverage (generic fallback works for ~50+ languages)

**Language-Specific Helpers:**
Some languages require minimal post-processing:
- Go: `_extract_go_receiver_type()` for method receivers
- Rust: `_rust_impl_target_for()` for impl block targets
- C/C++: `_c_func_name_for()` for declarator unwrapping

### Call Graph Construction

After initial parsing, CodeCanvas builds call edges using tree-sitter call sites + LSP definition resolution:

```
For each MODULE file:
  1. Extract call sites using tree-sitter (fast, syntax-based)
  2. Resolve each call site's definition location via LSP (semantic)
  3. Map call site → enclosing caller FUNC (by range)
  4. Map definition location → enclosing callee FUNC (by range)
  5. Add CALL edge: caller_func -> callee_func
```

This produces accurate call graphs by leveraging the language server's semantic understanding.

### Supported Languages

| Language | LSP Backend | LSP Server | Tree-Sitter Schema |
|----------|-------------|------------|-------------------|
| Python | multilspy | jedi-language-server | python.scm |
| TypeScript | multilspy | tsserver | typescript.scm |
| TSX/JSX | multilspy | tsserver | tsx.scm |
| JavaScript | multilspy | tsserver | javascript.scm |
| Go | multilspy | gopls | go.scm |
| Rust | multilspy | rust-analyzer | rust.scm |
| Java | multilspy | Eclipse JDTLS | java.scm |
| Ruby | multilspy | Solargraph | ruby.scm |
| C/C++ | multilspy | clangd | c.scm / cpp.scm |
| C# | multilspy | OmniSharp | - |
| Kotlin | multilspy | kotlin-language-server | - |
| Dart | multilspy | dart analysis_server | - |
| Shell | custom | bash-language-server | bash.scm |
| R | custom | languageserver | - |

**Language Configuration** (`parser/config.py`):
- `MULTILSPY_LANGUAGES`: Maps lang key → multilspy code_language (10 languages, auto-download)
- `LANGUAGE_SERVERS`: Extension point for custom LSP servers (currently `sh`, `r`)
- `TREESITTER_LANGUAGES`: Set of lang keys with `.scm` schemas (8 languages)
- `EXTENSION_TO_LANG`: File extension → lang key mapping

**Adding a new language:**
1. For multilspy-supported languages: Add to `MULTILSPY_LANGUAGES` with the multilspy code_language
2. For custom LSP: Add to `LANGUAGE_SERVERS` with the server command
3. For tree-sitter: Add a `.scm` schema to `parser/schemas/` and update `TREESITTER_LANGUAGES`

Tree-sitter parsing uses `tree-sitter-language-pack` which bundles grammars for all supported languages.

---

## Impact Analysis

Impact analysis answers: "What might break if I change X?"

### Slice Computation

A **slice** is the transitive closure of dependencies from a starting node.

Slices traverse only `CALL` and/or `IMPORT` edges (never `CONTAINS`). For `CLASS` and `MODULE` targets, we seed traversal from all descendant `FUNC` nodes so impact reflects behavior.

```python
def compute_slice(start_id, direction="in"):
    """
    direction="in":  What calls this? (callers, upstream)
    direction="out": What does this call? (callees, downstream)
    """
    seed = {start_id}
    if kind(start_id) in {CLASS, MODULE}:
        seed |= descendant_funcs(start_id)  # via CONTAINS

    visited = set(seed)
    queue = deque(seed)
    
    while queue:
        node = queue.popleft()
        edges = get_edges_to(node) if direction == "in" else get_edges_from(node)
        for edge in edges:
            if edge.type not in {CALL, IMPORT}:
                continue
            neighbor = edge.from_id if direction == "in" else edge.to_id
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    
    return visited
```

### Blast Radius

The **blast radius** is the inbound slice: all nodes that depend on the target.

```
Target: process_data()

Blast Radius (callers):
  - validate_input() calls process_data()
  - handle_request() calls validate_input()
  - main() calls handle_request()
  
  → 3 nodes may be affected by changes to process_data()
```

### Impact View Aggregation

For impact visualization, callers/callees are computed as **1-hop call edges** incident to the target's effective call participants:
- `FUNC` target: the function itself
- `CLASS` target: all descendant methods
- `MODULE` target: all descendant functions

Neighbors are aggregated for readability (e.g., calls from `OtherClass.other()` count toward `OtherClass` when the center is a class).

---

## Views

CodeCanvas renders three view types as PNG images.

### Architecture View

Generated by `canvas(action="init")`.

Shows module-level structure:
- Boxes: Modules (files)
- Nested boxes: Classes and functions
- Arrows: Import relationships

Rendering notes:
- C/C++ import edges are derived from `#include` statements (quoted or angle-bracket)
- Single-module districts annotate contained symbol counts (classes/functions) and sample symbol names
- Highly connected hub modules are visually emphasized

Layout: Hierarchical top-down, grouped by directory.

### Impact View

Generated by `canvas(action="impact", symbol="...")`.

Shows blast radius around target:
- Center: Target symbol (highlighted)
- Above: Callers (aggregated)
- Below: Callees (aggregated)
- Edges: Call relationships (counts)

Center card content:
- `MODULE`: file path + contains counts (classes/functions) + sample contained symbols
- `CLASS` / `FUNC`: signature + file location (`path:line`)

For `CLASS` and `MODULE` targets, the view represents the aggregated behavior of descendant functions/methods.

Layout: Radial/hierarchical from center node.

### Evidence Board (Task View)

Generated by all actions that modify state.

Shows reasoning state:
- Left column: Claims (hypothesis, finding, question)
- Center: Evidence thumbnails (clickable in UI)
- Right column: Decisions (plan, test, edit, mark, skip)
- Header: Current focus, progress indicator

Layout: Three-column dashboard.

### Rendering Pipeline

```
1. Build SVG using view-specific layout
2. Apply styling (colors, fonts, stroke widths)
3. Convert SVG to PNG via cairosvg
4. Return PNG bytes + save to .codecanvas/
```

---

## MCP Tool Reference

CodeCanvas exposes a single MCP tool: `canvas`.

### Tool Description

The tool description is a 280-word mini-tutorial embedded in the MCP schema:

```
CodeCanvas: Visual codebase analysis for agentic workflows.

WORKFLOW (recommended pattern):
1. init → Parse repo, get architecture overview
2. impact symbol="target" → See blast radius before changing
3. claim text="..." → Record hypotheses/findings
4. decide text="..." → Record plans/commitments
5. mark/skip symbol="..." → Track verification progress

ACTIONS:
• init: Parse repo into graph, render architecture map
• impact: Analyze symbol's callers/callees (blast radius)
• claim: Record hypothesis|finding|question
• decide: Record plan|test|edit commitment
• mark: Mark symbol as verified
• skip: Mark symbol as out-of-scope
• status: Refresh Evidence Board
• read: Text-only state dump

EVIDENCE BOARD:
Your persistent working memory showing Claims, Evidence, Decisions.
Check it to stay oriented on multi-step tasks.

TIPS:
• Use impact BEFORE making changes
• Claims/decisions auto-link to recent evidence
• The board shows progress—check when resuming
```

### Actions

| Action | Parameters | Returns | Purpose |
|--------|------------|---------|---------|
| `init` | `repo_path` | architecture.png, task.png | Parse codebase, create initial evidence |
| `impact` | `symbol`, `depth`, `max_nodes` | impact_*.png, task.png | Analyze blast radius |
| `claim` | `text`, `kind` | task.png | Record hypothesis/finding/question |
| `decide` | `text`, `kind` | task.png | Record plan/test/edit |
| `mark` | `symbol`, `text` | task.png | Mark symbol verified |
| `skip` | `symbol`, `text` | task.png | Mark symbol out-of-scope |
| `task_select` | `task_id` | task.png | Select task from tasks.yaml |
| `status` | (none) | task.png | Refresh board without reparsing |
| `read` | (none) | text only | Text dump for non-multimodal |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | (required) | Action to perform |
| `repo_path` | string | "." | Repository root (init only) |
| `symbol` | string | - | Target symbol name |
| `text` | string | - | Claim/decision text |
| `kind` | string | varies | hypothesis\|finding\|question\|plan\|test\|edit |
| `depth` | int | 2 | Included in evidence metadata; callers/callees are computed from 1-hop call edges |
| `max_nodes` | int | 20 | Max nodes to display (used to derive caller/callee box budget; capped at 8 per side) |
| `task_id` | string | - | Task ID from tasks.yaml |

### Response Format

Every response follows a structured format:

```
[Action Result]
- What happened (evidence created, symbol marked, etc.)
- Quantitative details (callers, callees, node counts)

[Board Summary]
Board: {N} evidence, {M} claims, {K} decisions | Focus: {symbol}

[Next Hint]
Next: {context-appropriate suggestion}
```

Example response from `impact`:

```
Created E2 (impact "process_data"): 3 callers, 2 callees.
Blast radius: 6 nodes may be affected by changes.

Board: 2 evidence, 0 claims, 0 decisions | Focus: process_data
Next: Record your analysis with claim(text="...") or plan with decide(text="...").
```

### Image Delivery

Images are returned inline via MCP's ImageContent:

```python
ImageContent(
    type="image",
    data=base64.b64encode(png_bytes).decode("ascii"),
    mimeType="image/png",
)
```

This ensures agents receive images directly without needing to read files.

---

## Agent UX Design

CodeCanvas is designed to maximize effectiveness for small models (Haiku 4.5) on complex tasks.

### Design Principle

> "Don't require the model to be smart. Make the tool smart."

### Tool Description as Tutorial

The 280-word tool description serves as inline documentation:
- Workflow pattern (numbered steps)
- Action reference (bullet list)
- Evidence Board explanation
- Example session
- Tips

This ensures agents understand the tool without external docs.

### Structured Response Texts

Every response includes three components:

1. **Action Result**: What happened, with quantitative details
2. **Board Summary**: One-line orientation (counts + focus)
3. **Next Hint**: Context-aware suggestion

This eliminates "what now?" confusion and guides workflow.

### Fuzzy Symbol Matching

When a symbol isn't found, CodeCanvas suggests alternatives:

```
Symbol not found: "proces_data"
Similar symbols:
  - process_data (func)
  - process_request (func)
  - DataProcessor (class)
Hint: Use exact function/class names from the suggestions above.
```

Scoring: exact match > substring > prefix > character overlap.

### Progress Tracking

When an analysis is active, responses include progress:

```
Board: 3 evidence, 2 claims, 1 decisions | Focus: process_data | Progress: 4/7 addressed
```

This helps agents know when they're done.

### Error Recovery

Error messages include actionable hints:

```
Not initialized.
Hint: Run canvas(action="init", repo_path=".") first, or this may auto-trigger via hooks.
```

---

## Hooks

CodeCanvas uses Claude Code hooks to automatically provide “always-on” context at key lifecycle points.

Design intent:
- **AUTO-INIT** provides architecture context once the real workspace is detected (clone-first workflows).
- **Post-edit impact summaries** help the agent understand side-effects of changes it already made.
- If the agent wants to **preview** blast radius before editing, it should explicitly call `canvas(action="impact", ...)`.

### Hook 1: SessionStart - Arm AutoContext (Deferred Init)

**Trigger**: Session starts (matcher: `startup`)

**Action**: Records an “active root” hint but does **not** run init.

Rationale: in TerminalBench/Harbor, sessions often start in a generic working directory (e.g. `/app`) before the task repo is cloned. An unconditional init at SessionStart can produce an empty graph (`parsed_files=0`) that then “sticks”.

**Output**: A short “armed” message in `additionalContext`.

### Hook 2: PreToolUse - Auto Init (Architecture) Once Workspace Is Clear

**Trigger**: Before any tool (matcher: `*`)

**Action**: Attempts `canvas(action="init")` once the workspace root is confidently detected (marker-backed root or a real file path).

**Output**: `additionalContext` injected into Claude's context (once per workspace root):
```
[CodeCanvas AUTO-INIT] root=/path/to/repo parse: parsed=... lsp=... tree_sitter=... call_graph: phase=... edges=...
```

### Hook 3: PostToolUse - Impact Summary After Mutations

**Trigger**: After `Edit` or `Write` completes successfully (matcher: `Edit|Write`)

**Action**: Selects a “best” symbol from the edited file, runs `canvas(action="impact")`, and injects a short summary of callers/callees.

**Output**: `additionalContext` injected into Claude's context:
```
[CodeCanvas IMPACT] root=/path/to/repo
symbol=... callers=... callees=...
```

### Hook Configuration

`codecanvas/hooks/hooks.json`:
```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [{
          "type": "command",
          "command": "uv run python -c \"from codecanvas.hooks.session_init import main; main()\"",
          "timeout": 60
        }]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [{
          "type": "command",
          "command": "uv run python -c \"from codecanvas.hooks.post_read import main; main()\"",
          "timeout": 30
        }]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{
          "type": "command",
          "command": "uv run python -c \"from codecanvas.hooks.post_read import main; main()\"",
          "timeout": 30
        }]
      }
    ]
  }
}
```

### Why additionalContext (not systemMessage)?

- `systemMessage`: Shown to user only. Claude doesn't see it. **Useless.**
- `additionalContext`: Injected into Claude's context. Claude sees it. **Useful.**

### Why Module Import?

Hook commands use `uv run python -c "from codecanvas.hooks.X import main; main()"` because:
1. `uv run` ensures the correct virtual environment and dependencies are available
2. In Harbor containers, source files are deleted after pip install
3. Module import works with installed packages regardless of location

---

## Integration

### MCP Configuration

`.mcp.json` entry:
```json
{
  "mcpServers": {
    "codecanvas": {
      "command": "uv",
      "args": ["run", "python", "-m", "codecanvas.server"],
      "env": {"PYTHONUNBUFFERED": "1"}
    }
  }
}
```

### System Prompt (USAGE.md)

`codecanvas/USAGE.md` is auto-discovered and injected as system prompt:

```markdown
# CodeCanvas Usage Guide (for Agents)

CodeCanvas helps you analyze code before changing it...

## Quick Start
canvas(action="init", repo_path=".")
canvas(action="impact", symbol="foo")
...
```

### TerminalBench Usage

```bash
python -m terminalbench.ui.cli \
  --mcp-server codecanvas \
  --mcp-git-source https://github.com/ain3sh/codecanvas \
  --hooks codecanvas/hooks/hooks.json \
  --tasks <task-id>
```

This:
1. Clones and pip-installs codecanvas in Harbor container
2. Configures MCP server
3. Loads hooks into Claude Code settings
4. Injects USAGE.md as system prompt

### State Persistence

CodeCanvas writes state and images to `.codecanvas/` under `CANVAS_PROJECT_DIR`.

In TerminalBench/Harbor runs, the task workspace is not persisted, so hooks also mirror artifacts into the session directory (`$CLAUDE_CONFIG_DIR/codecanvas/`, i.e. `agent/sessions/codecanvas/`). This includes:
- `state.json`, `architecture.png`, `impact_*.png`, `task.png`
- `hook_debug.jsonl` (hook instrumentation)

---

## Key Design Decisions

### 1. No Progress Notifications

**Decision**: Don't use MCP progress notifications.

**Rationale**: The backend is fast enough (<2s for most repos) that progress notifications add complexity without benefit. The synchronous response model is simpler and sufficient.

### 2. Hide `use_lsp` Parameter

**Decision**: Remove `use_lsp` from MCP schema, default to `True` internally.

**Rationale**: This is an implementation detail. LSP-first with tree-sitter fallback is always the right choice. Exposing it confuses agents and invites suboptimal usage.

### 3. Dual-Backend LSP Architecture

**Decision**: Use a dual-backend LSP architecture: multilspy (primary) for 10 languages with auto-download, plus CustomLspBackend (extension point) for additional languages.

**Rationale**: 
- **multilspy** provides zero-config LSP for Python, TypeScript, Go, Rust, Java, Ruby, C/C++, C#, Kotlin, and Dart via auto-download binaries.
- **CustomLspBackend** enables extending to any language with an LSP server by adding to `LANGUAGE_SERVERS` in `parser/config.py`.
- Both backends implement the same `LspBackend` protocol; `LspSession` routes based on language.
- This architecture balances convenience (auto-download for common languages) with extensibility (any LSP server for edge cases).

### 3a. Declarative Tree-Sitter Queries

**Decision**: Use tree-sitter's native query system with `.scm` schema files for extraction patterns.

**Rationale**: Tree-sitter queries (`Query` + `QueryCursor`) express "definitions/imports/calls" declaratively. Language-specific patterns are data (`.scm` files), not code. Adding a language with full extraction = add a schema file. Languages without schemas still get basic definition extraction via the generic fallback query.

### 4. Inline Image Delivery

**Decision**: Return images as base64 ImageContent, not file paths.

**Rationale**: Agents may not read files unprompted. Inline delivery guarantees the agent receives the visualization. File persistence is for debugging, not primary delivery.

### 5. Evidence Board as External Memory

**Decision**: Persist claims/evidence/decisions to disk, render as visual board.

**Rationale**: Context compaction loses in-context reasoning. The Evidence Board survives compaction, providing continuity across long tasks. Visual rendering makes state inspectable.

### 6. Single MCP Tool with Actions

**Decision**: One tool (`canvas`) with action parameter, not multiple tools.

**Rationale**: Reduces tool discovery overhead. The action parameter naturally guides workflow. Tool description can document all actions in one place.

### 7. Next-Step Hints in Responses

**Decision**: Every response includes a context-aware next-step suggestion.

**Rationale**: Small models need explicit guidance. Hints encode workflow knowledge ("after impact, make a claim or decision"). This reduces thrashing and improves task completion.

### 8. Fuzzy Symbol Matching

**Decision**: When symbol not found, suggest similar symbols.

**Rationale**: Typos and partial names are common. Suggestions enable recovery without agent frustration. Scoring prioritizes likely matches (substring > prefix > overlap).

### 9. Hooks That Actually Do Things

**Decision**: SessionStart runs init, PostToolUse:Read runs impact. Both output `additionalContext`.

**Rationale**: `systemMessage` is shown to user only - Claude doesn't see it (useless). `additionalContext` is injected into Claude's context (useful). Auto-running actions means small models don't need to be smart enough to invoke them manually.

### 10. Output to `.codecanvas/`

**Decision**: Save state and images to `.codecanvas/` in task repo.

**Rationale**: Standard hidden directory convention. Keeps task repo clean. Easy to gitignore. Works in any repository context.

---

## Summary

CodeCanvas transforms code editing from blind modification to informed analysis:

| Without CodeCanvas | With CodeCanvas |
|-------------------|-----------------|
| Edit blindly, hope nothing breaks | See blast radius before editing |
| Lose reasoning on context compact | Evidence Board persists |
| Guess what to do next | Next-step hints guide workflow |
| Typo in symbol = failure | Fuzzy matching suggests alternatives |
| Manual init required | Hooks auto-run init and impact |

The result: higher task completion rates, fewer cascading bugs, better reasoning traces.
