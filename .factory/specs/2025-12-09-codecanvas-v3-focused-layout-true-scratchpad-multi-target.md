## Core Problems with v2

1. **Layout overwhelm**: 200 nodes in one image = noise, not signal
2. **Notes are boring**: Key-value labels != scratchpad
3. **Single-target limitation**: Real refactors touch multiple functions

---

## 1. Layout: Impact-Focused Subgraph

**Insight**: Agent doesn't need the whole codebase - just the **blast radius subgraph**.

### Current (v2)
```
[200 nodes crammed together, most irrelevant]
```

### Proposed (v3)
```
Only render:
├── Target (red, center)
├── Direct callers (cyan, inner ring)
├── Transitive callers depth 2 (lighter cyan, outer ring)
├── Related tests (green, bottom)
└── Context: parent module/class labels only
```

**Result**: 10-30 nodes instead of 200. Digestible by Claude Haiku, not just Opus.

### Layout Algorithm
```python
def impact_layout(target, affected, tests):
    # Radial layout centered on target
    # - Target at center
    # - Direct callers in first ring (sorted by importance)
    # - Transitive at second ring
    # - Tests in dedicated region below
    # - Module labels as background regions (no individual nodes)
```

### Filtering Knobs
```python
canvas("func", depth=2, max_nodes=25, show_tests=True)
```

---

## 2. Scratchpad: True Working Memory

**Kill the notes dict. Build a real scratchpad.**

### Design: Markdown Panel + Visual Annotations

```
┌─────────────────────────────────────────────────────┐
│  SCRATCHPAD: validate_token refactor                │
├─────────────────────────────────────────────────────┤
│  ## Plan                                            │
│  1. Add timeout param to validate_token             │
│  2. Update callers to pass timeout                  │
│  3. Run test_auth_flow                              │
│                                                     │
│  ## Observations                                    │
│  - @check_auth: also needs retry logic              │
│  - @refresh_token: SKIP - deprecated anyway         │
│                                                     │
│  ## Questions                                       │
│  - Should timeout be optional with default?         │
│                                                     │
│  ## Done                                            │
│  - [x] @login (added timeout=30)                    │
│  - [x] @verify (added timeout=30)                   │
└─────────────────────────────────────────────────────┘
```

### Implementation

```python
# State includes free-form scratchpad text
@dataclass  
class AnalysisState:
    target_id: str
    affected_ids: Set[str]
    addressed_ids: Set[str]
    scratchpad: str  # Free-form markdown
    
# Tool interface
canvas(write="## Plan\n1. Add timeout...")  # Append to scratchpad
canvas(read=True)  # Return scratchpad content
canvas(clear=True)  # Reset scratchpad
```

### Visual Integration

- Scratchpad renders as **side panel** in PNG (right 30%)
- `@symbol` mentions get **highlighted** in the graph
- Checked items `[x] @sym` automatically mark as addressed
- "SKIP" keyword grays out the node

### Agent Experience
```python
canvas("validate_token")
# -> Shows graph + empty scratchpad panel

canvas(write="""
## Plan
1. Add timeout param
2. Update @check_auth @login @verify  
3. Skip @refresh_token - deprecated
""")
# -> Re-renders with mentions highlighted, refresh grayed

# As agent works, scratchpad accumulates reasoning
canvas(write="- @check_auth done, needed retry too")
```

---

## 3. Multi-Target: Merged Blast Radius

### Scenario
Agent is refactoring auth module - needs to change `validate_token`, `refresh_token`, AND `revoke_token`.

### Current (v2)
Can only track one. Must manually switch. Loses progress.

### Proposed (v3): Compound Analysis

```python
canvas("validate_token")  # Start first
canvas("refresh_token", add=True)  # ADD to existing (not replace)
canvas("revoke_token", add=True)   # Now tracking 3 targets

canvas()  # Status shows ALL
# -> "3 targets: validate_token (2/5), refresh_token (1/3), revoke_token (0/4)"
# -> "Combined: 5/12 addressed"
```

### Merged Visualization
- Multiple targets shown with **different colors** (red, orange, yellow)
- Blast radii **merged** - shared callers shown once
- Progress bar shows **combined** completion

### State Structure
```python
@dataclass
class CanvasState:
    project_path: str
    analyses: Dict[str, AnalysisState]  # target_id -> state
    scratchpad: str  # Shared scratchpad across all targets
    
    def combined_remaining(self) -> Set[str]:
        """Union of all remaining across all analyses."""
```

---

## 4. Simplified Tool Interface

**One tool, smart parameters:**

```python
canvas(
    # Core
    target: str = None,      # Symbol or path
    add: bool = False,       # Add to existing (multi-target)
    
    # Scratchpad
    write: str = None,       # Append to scratchpad
    read: bool = False,      # Return scratchpad
    
    # Manual control
    mark: str = None,        # Mark symbol done
    skip: str = None,        # Mark symbol skipped
    
    # Rendering
    depth: int = 2,          # Max transitive depth
    max_nodes: int = 30,     # Cap for digestibility
)
```

### Example Flows

```python
# Simple single-target
canvas("/project")
canvas("my_func")
canvas(mark="caller1")
canvas()  # status

# Multi-target refactor  
canvas("func1")
canvas("func2", add=True)
canvas(write="Refactoring both for new API")
canvas(mark="shared_caller")  # Marks in BOTH analyses
canvas()  # Combined status

# Scratchpad-heavy workflow
canvas("complex_func")
canvas(write="## Analysis\n- Entry point for auth flow\n- @helper1 and @helper2 are internal")
canvas(write="## Decision\n- Only update public interface")
canvas(skip="helper1")
canvas(skip="helper2")
```

---

## 5. MCP + Plugin Packaging (Future)

```
codecanvas/
├── mcp_server.py      # Exposes canvas() as MCP tool
├── claude_plugin/
│   ├── manifest.json  # Plugin metadata
│   ├── hooks.json     # Pre/Post/Stop hooks
│   └── install.sh     # Node deps setup
```

Not in this PR - separate packaging task.

---

## Implementation Order

1. **Refactor state** for multi-target support
2. **Impact-focused layout** (subgraph extraction + radial layout)
3. **Scratchpad system** (markdown storage + @mention parsing)
4. **Visual integration** (side panel + highlight mentions)
5. **Update render.js** for new layout + scratchpad panel
6. **Tests**

---

## Token Budget (v3 vs v2)

| Metric | v2 | v3 |
|--------|----|----|
| Nodes rendered | 200 | 10-30 |
| PNG size | 200KB | ~80KB |
| Image tokens | ~1000 | ~600 |
| Text tokens | ~100 | ~150 (includes scratchpad summary) |
| **Total** | ~1100 | ~750 |

**30% more efficient** while being **more informative**.