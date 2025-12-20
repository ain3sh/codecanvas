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
┌─────────────────────────────────────────────────────────────────┐
│                         MCP Server                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │   canvas    │  │   canvas    │  │   canvas    │             │
│  │ action=init │  │action=impact│  │ action=...  │             │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘             │
│         │                │                │                     │
│         ▼                ▼                ▼                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    State Manager                         │   │
│  │  - CanvasState (evidence, claims, decisions, focus)     │   │
│  │  - Persistence to .codecanvas/state.json                │   │
│  └─────────────────────────────────────────────────────────┘   │
│         │                │                │                     │
│         ▼                ▼                ▼                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │   Parser    │  │  Analyzer   │  │    Views    │             │
│  │  (LSP/TS)   │  │ (Slicing)   │  │  (SVG/PNG)  │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└─────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Responsibility |
|-----------|----------------|
| **MCP Server** | Tool registration, request routing, response formatting |
| **State Manager** | Evidence board state, persistence, focus tracking |
| **Parser** | Code parsing, graph construction, call edge inference |
| **Analyzer** | Impact slicing, neighborhood extraction, symbol search |
| **Views** | SVG rendering, PNG conversion, layout algorithms |

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
| `CALL` | Function calls function | LSP references |
| `CONTAINS` | Parent contains child | AST structure |

### Node Properties

```python
@dataclass
class GraphNode:
    id: str           # Unique identifier (file:line:col or hash)
    label: str        # Display name
    kind: NodeKind    # MODULE, CLASS, FUNC
    file: str         # Source file path
    line: int         # Line number (1-indexed)
    parent: str       # Parent node ID (for containment)
```

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

### Phase 1: LSP Parsing

The Language Server Protocol provides accurate symbol information:

```
1. Start language server (pylsp, typescript-language-server, etc.)
2. Initialize with workspace root
3. Request textDocument/documentSymbol for each file
4. Build nodes from symbol hierarchy
5. Infer CONTAINS edges from parent-child relationships
```

**Advantages:**
- Semantically accurate (understands imports, types, scopes)
- Language-agnostic (any LSP server works)
- Handles complex patterns (decorators, metaclasses, generics)

**Limitations:**
- Slower startup (server initialization)
- May fail on malformed code
- Requires language server installation

### Phase 2: Tree-Sitter Fallback

When LSP fails or is unavailable, tree-sitter provides AST-based parsing:

```
1. Load tree-sitter grammar for language
2. Parse file into syntax tree
3. Walk tree for class/function definitions
4. Build nodes from AST positions
5. Infer containment from tree structure
```

**Advantages:**
- Fast (native parsing)
- Robust (handles partial/broken code)
- No external dependencies

**Limitations:**
- Less semantic accuracy
- No cross-file analysis
- Pattern-based (may miss edge cases)

### Call Graph Construction

After initial parsing, CodeCanvas builds call edges using LSP references:

```
For each FUNC node:
  1. Get definition location
  2. Request textDocument/references from LSP
  3. For each reference location:
     a. Find containing function (by position)
     b. Add CALL edge: containing_func -> defined_func
```

This produces accurate call graphs by leveraging the language server's semantic understanding.

### Supported Languages

| Language | LSP Server | Tree-Sitter |
|----------|------------|-------------|
| Python | pylsp | tree-sitter-python |
| TypeScript/JavaScript | typescript-language-server | tree-sitter-typescript |
| Rust | rust-analyzer | tree-sitter-rust |
| Go | gopls | tree-sitter-go |

Additional languages work via tree-sitter fallback.

---

## Impact Analysis

Impact analysis answers: "What might break if I change X?"

### Slice Computation

A **slice** is the transitive closure of dependencies from a starting node.

```python
def compute_slice(start_id, direction="in"):
    """
    direction="in":  What calls this? (callers, upstream)
    direction="out": What does this call? (callees, downstream)
    """
    visited = {start_id}
    queue = deque([start_id])
    
    while queue:
        node = queue.popleft()
        edges = get_edges_to(node) if direction == "in" else get_edges_from(node)
        for edge in edges:
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

### Neighborhood Extraction

For visualization, we extract a bounded **neighborhood** around the target:

```python
def neighborhood(node_id, hops=2, max_nodes=20):
    """
    Extract k-hop neighborhood for focused visualization.
    Includes both callers and callees within hop distance.
    Caps at max_nodes to prevent visual overload.
    """
```

The neighborhood is rendered as the Impact View.

---

## Views

CodeCanvas renders three view types as PNG images.

### Architecture View

Generated by `canvas(action="init")`.

Shows module-level structure:
- Boxes: Modules (files)
- Nested boxes: Classes and functions
- Arrows: Import relationships

Layout: Hierarchical top-down, grouped by directory.

### Impact View

Generated by `canvas(action="impact", symbol="...")`.

Shows blast radius around target:
- Center: Target symbol (highlighted)
- Above: Callers (what calls this)
- Below: Callees (what this calls)
- Edges: Call relationships

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
| `init` | `repo_path` | architecture.png, board.png | Parse codebase, create initial evidence |
| `impact` | `symbol`, `depth`, `max_nodes` | impact.png, board.png | Analyze blast radius |
| `claim` | `text`, `kind` | board.png | Record hypothesis/finding/question |
| `decide` | `text`, `kind` | board.png | Record plan/test/edit |
| `mark` | `symbol`, `text` | board.png | Mark symbol verified |
| `skip` | `symbol`, `text` | board.png | Mark symbol out-of-scope |
| `task_select` | `task_id` | board.png | Select task from tasks.yaml |
| `status` | (none) | board.png | Refresh board without reparsing |
| `read` | (none) | text only | Text dump for non-multimodal |

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | (required) | Action to perform |
| `repo_path` | string | "." | Repository root (init only) |
| `symbol` | string | - | Target symbol name |
| `text` | string | - | Claim/decision text |
| `kind` | string | varies | hypothesis\|finding\|question\|plan\|test\|edit |
| `depth` | int | 2 | Impact neighborhood depth (1-3 recommended) |
| `max_nodes` | int | 20 | Max nodes in impact view |
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

CodeCanvas includes a PreToolUse hook for auto-initialization.

### Purpose

When an agent starts working on a code repository, it should initialize CodeCanvas. The hook detects this situation and suggests init.

### Trigger Conditions

The hook fires on: `Read | Edit | Write | Grep | Glob`

It suggests init when ALL of:
1. Current directory is a code repo (.git, pyproject.toml, package.json, etc.)
2. Contains ≥5 code files
3. No existing `.codecanvas/state.json`

### Hook Configuration

`codecanvas/hooks/hooks.json`:
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read|Edit|Write|Grep|Glob",
        "hooks": [
          {
            "type": "command",
            "command": "python3 -c \"from codecanvas.hooks.auto_init import main; main()\"",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

### Hook Output

When conditions are met, outputs:
```json
{
  "systemMessage": "[CodeCanvas] Code repository detected without canvas state. Consider: canvas(action=\"init\", repo_path=\".\") for impact analysis."
}
```

The `systemMessage` is shown to the user (in Claude Code UI) without blocking the tool.

### Why Module Import?

The hook command uses `python3 -c "from codecanvas.hooks.auto_init import main; main()"` instead of a file path because:

1. In terminalbench/Harbor, the source repo is deleted after pip install
2. The installed package is available via Python's import system
3. This works regardless of installation location

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

All state is saved to `.codecanvas/` in the task repository:
- `state.json` - Evidence, claims, decisions, focus
- `architecture.png` - Init visualization
- `impact_*.png` - Impact visualizations
- `task.png` - Evidence Board

---

## Key Design Decisions

### 1. No Progress Notifications

**Decision**: Don't use MCP progress notifications.

**Rationale**: The backend is fast enough (<2s for most repos) that progress notifications add complexity without benefit. The synchronous response model is simpler and sufficient.

### 2. Hide `use_lsp` Parameter

**Decision**: Remove `use_lsp` from MCP schema, default to `True` internally.

**Rationale**: This is an implementation detail. LSP-first with tree-sitter fallback is always the right choice. Exposing it confuses agents and invites suboptimal usage.

### 3. LSP-First Parsing

**Decision**: Use LSP as primary parser, tree-sitter as fallback.

**Rationale**: LSP provides semantic accuracy (correct call edges, proper scoping). The speed cost (1-2s) is acceptable for the accuracy gain. Fallback ensures robustness on malformed code.

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

### 9. Hook via Module Import

**Decision**: Hook command uses `python -c "from codecanvas.hooks.auto_init import main; main()"`.

**Rationale**: In Harbor, source files are deleted after pip install. Module import works with installed packages. This is more robust than file paths.

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
| Manual init required | Hooks auto-suggest init |

The result: higher task completion rates, fewer cascading bugs, better reasoning traces.
