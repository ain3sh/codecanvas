## Core Problem: LLM Jagged Intelligence on Side-Effects

LLM agents consistently fail to predict/track ripple effects of code changes:
- Agent modifies `validate_token()` to add a parameter
- Doesn't realize 5 callers now break
- User must remind: "you broke the callers" or "re-run the tests"
- Agent then greps/searches reactively instead of proactively

**CodeCanvas compensates for this blind spot via pre-computed reverse dependency tracking.**

---

## Reframed Purpose

| Windsurf Codemaps | CodeCanvas |
|-------------------|------------|
| "Help me understand how auth works" | "What breaks if I change `validate_token()`?" |
| Exploration/onboarding | **Change impact prediction** |
| Forward tracing (what does X call?) | **Reverse tracing (what calls X?)** |
| LLM-generated groupings | Static dependency checklist |

---

## Core Data Structure: Impact Analysis Result

```python
@dataclass
class ImpactAnalysis:
    target: Symbol                      # The symbol being modified
    direct_callers: List[Symbol]        # Functions that call this directly
    transitive_callers: List[Symbol]    # Full reverse call tree
    tests: List[Symbol]                 # Test functions that exercise this
    interface_dependents: List[Symbol]  # Things that depend on signature/types
    
    # Scratchpad state (agent marks as addressed)
    addressed: Set[str]                 # Symbol IDs agent has handled
    
    def remaining(self) -> List[Symbol]:
        """What hasn't been addressed yet?"""
```

---

## Agent Workflow Integration

```
1. Agent identifies target: "I need to modify db/models.py:User.save()"

2. Agent queries canvas BEFORE changing:
   canvas.impact_of("User.save") -> ImpactAnalysis

3. Canvas returns checklist:
   ## Direct Callers (MUST UPDATE)
   - [ ] api/users.py:create_user:45
   - [ ] api/users.py:update_user:78  
   - [ ] auth/register.py:register:23

   ## Tests (MUST RUN)
   - [ ] tests/test_users.py::test_create_user
   - [ ] tests/test_auth.py::test_register

   ## Transitive Impact (REVIEW)
   - 3 API routes ultimately depend on this

4. Agent makes change, marks items as addressed:
   canvas.mark_addressed("api/users.py:create_user")

5. Agent queries canvas.remaining() before declaring "done"
```

---

## Implementation Architecture

```
codecanvas/
├── core/
│   ├── parser.py           # Tree-sitter: extract symbols + call sites
│   ├── graph.py            # Bidirectional adjacency (calls + called_by)
│   └── lsp_resolver.py     # LSP go-to-def for accurate resolution
│
├── analysis/
│   ├── reverse_deps.py     # Build reverse dependency index (critical)
│   ├── test_mapper.py      # Map symbols -> tests that cover them
│   ├── impact.py           # impact_of(symbol) -> ImpactAnalysis
│   └── interface.py        # Signature/type dependency tracking
│
├── scratchpad/
│   ├── canvas.py           # Mutable state: addressed, notes, flags
│   └── checklist.py        # Render as markdown checklist for LLM
│
└── output/
    ├── text.py             # Hierarchical checklist (LLM consumption)
    └── json.py             # Structured output (programmatic)
```

---

## Phase 1: Reverse Dependency Index (Critical Path)

**Tree-sitter Pass:**
```python
# For each file, extract:
symbols: {
    "db/models.py:User.save": Symbol(line=45, signature="def save(self) -> None")
}
call_sites: [
    CallSite(caller="api/users.py:create_user", callee_name="save", line=67, col=12)
]
```

**LSP Resolution Pass:**
```python
# For ambiguous calls, use LSP go-to-definition
for call_site in unresolved_calls:
    resolved = lsp.goto_definition(call_site.file, call_site.line, call_site.col)
    call_site.resolved_target = resolved
```

**Build Reverse Index:**
```python
called_by: Dict[str, List[str]] = {
    "db/models.py:User.save": [
        "api/users.py:create_user",
        "api/users.py:update_user",
        "auth/register.py:register"
    ]
}
```

---

## Phase 2: Test Mapping

```python
def find_tests_for(symbol: str) -> List[Symbol]:
    """Find test functions that reference this symbol."""
    
    # 1. Convention-based: foo.py -> test_foo.py, tests/test_foo.py
    # 2. Import-based: tests that import the module
    # 3. Call-based: test functions that call the symbol (from reverse index)
    
    return [t for t in test_functions if symbol in t.references]
```

---

## Phase 3: Query Interface

```python
class CodeCanvas:
    def impact_of(self, symbol: str, depth: int = 3) -> ImpactAnalysis:
        """Primary query: what's affected if I change this symbol?"""
        
    def mark_addressed(self, symbol: str) -> None:
        """Agent marks a dependency as handled."""
        
    def remaining(self) -> List[Symbol]:
        """What impact items haven't been addressed?"""
        
    def render_checklist(self) -> str:
        """Output markdown checklist for LLM context."""
```

---

## Output Format (LLM-Optimized)

```markdown
# Impact Analysis: Modifying `db/models.py:User.save()`

## Direct Callers (3) - MUST UPDATE
- [ ] `api/users.py:create_user` (line 67) - calls save() after validation
- [ ] `api/users.py:update_user` (line 89) - calls save() with modified fields
- [x] `auth/register.py:register` (line 34) - ADDRESSED

## Tests (2) - MUST RUN  
- [ ] `tests/test_users.py::test_create_user`
- [ ] `tests/test_auth.py::test_register`

## Transitive Impact (depth=2)
- `api/routes.py:user_routes` -> `api/users.py:create_user` -> `User.save`
- 3 HTTP endpoints ultimately affected

## Remaining: 4 items unchecked
```

---

## Why This Works Without LLM Direction

| LLM Weakness | Static Analysis Strength |
|--------------|-------------------------|
| Forgets callers exist | Complete reverse index |
| Doesn't know what tests to run | Test mapping is deterministic |
| Misses transitive effects | Graph traversal is exhaustive |
| Loses track mid-task | Scratchpad persists state |

We use static analysis for what it's **provably good at** (dependency completeness) to compensate for what LLMs are **provably bad at** (side-effect prediction).

---

## Terminal Bench Applicability

| Task Type | CodeCanvas Query |
|-----------|-----------------|
| Debugging | `impact_of(failing_test)` -> trace what it depends on |
| Refactoring | `impact_of(target)` -> checklist before renaming |
| Feature addition | `impact_of(modified_function)` -> update callers |
| Bug fix verification | `tests_for(changed_code)` -> what to run |

---

## Key Differentiators from Existing Tools

1. **Bidirectional by default** - reverse deps as primary, not afterthought
2. **Scratchpad state** - agent marks progress, canvas tracks remaining
3. **Test integration** - maps code to tests automatically  
4. **LLM-optimized output** - checklist format, not raw graph dump
5. **LSP-accurate** - uses go-to-def, not just textual grep