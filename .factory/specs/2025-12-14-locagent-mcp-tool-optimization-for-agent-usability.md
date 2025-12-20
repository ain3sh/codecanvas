## Analysis Summary

### Current Architecture
- **Graph-based code navigation** using NetworkX MultiDiGraph
- **Node types**: `directory`, `file`, `class`, `function`  
- **Edge types**: `contains`, `imports`, `invokes`, `inherits`
- **Entity ID format**: `file_path:QualifiedName` (e.g., `src/utils.py:Helper.process`)
- **BM25 + fuzzy search** for keyword-based code retrieval

### Key Problems for Small Agents (Haiku 4.5)

1. **`init_repository`**: Unclear that `repo_path` must be absolute; `force_rebuild` confusing on first use
2. **`explore_tree_structure`**: Too many parameters; confusing terminology ("upstream/downstream"); entity ID format not intuitive
3. **`search_code_snippets`**: Optional params without clear defaults; examples buried in description
4. **USAGE.md**: Too brief; no concrete examples; no error recovery guidance

---

## Proposed Changes

### 1. Tool Definition Improvements (server.py)

#### `init_repository` - Simplify description
```python
Tool(
    name="init_repository",
    description="Initialize code index for a repository. MUST call first before other tools. Returns node/edge count on success.",
    inputSchema={
        "properties": {
            "repo_path": {
                "type": "string",
                "description": "Absolute path to repository root (e.g., '/home/user/myproject')"
            }
        },
        "required": ["repo_path"]
    }
)
# Remove force_rebuild from schema - rarely needed, confuses agents
```

#### `explore_tree_structure` -> Rename to `get_dependencies`
```python
Tool(
    name="get_dependencies",
    description="""Find what code depends on or is depended by given entities.

ENTITY FORMAT:
- File: 'src/utils.py'
- Class: 'src/utils.py:MyClass'
- Function: 'src/utils.py:MyClass.method' or 'src/utils.py:helper_func'
- Root dir: '/'

EXAMPLES:
- See project structure: get_dependencies(entities=['/'], depth=2)
- What calls MyClass?: get_dependencies(entities=['src/core.py:MyClass'], direction='incoming')
- What does func call?: get_dependencies(entities=['src/app.py:main'], direction='outgoing')""",
    inputSchema={
        "properties": {
            "entities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Entity IDs to analyze (file paths or 'file:name' format)"
            },
            "direction": {
                "type": "string",
                "enum": ["outgoing", "incoming", "both"],
                "default": "outgoing",
                "description": "outgoing=what this calls, incoming=what calls this"
            },
            "depth": {
                "type": "integer",
                "default": 2,
                "description": "How many levels deep to traverse (1-5 recommended)"
            }
        },
        "required": ["entities"]
    }
)
# Remove entity_type_filter and dependency_type_filter - rarely useful, confuses agents
```

#### `search_code_snippets` -> Rename to `search_code`
```python
Tool(
    name="search_code",
    description="""Search codebase by keywords or lookup specific lines.

EXAMPLES:
- Find function: search_code(query=["process_data"])
- Find in specific file: search_code(query=["handler"], files="src/api/*.py")  
- Get lines 10-20: search_code(lines=[10,15,20], files="src/main.py")""",
    inputSchema={
        "properties": {
            "query": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keywords, function names, or class names to search"
            },
            "lines": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Line numbers to retrieve (requires 'files' to be a single file)"
            },
            "files": {
                "type": "string",
                "default": "**/*.py",
                "description": "Glob pattern or file path (e.g., 'src/**/*.py' or 'src/main.py')"
            }
        }
    }
)
```

#### `get_entity_contents` -> Rename to `get_code`
```python
Tool(
    name="get_code",
    description="""Get complete source code for specific entities.

FORMAT: 'file_path' or 'file_path:ClassName' or 'file_path:ClassName.method'

EXAMPLES:
- Full file: get_code(entities=['src/config.py'])
- Specific class: get_code(entities=['src/models.py:User'])
- Specific method: get_code(entities=['src/models.py:User.save'])""",
    inputSchema={
        "properties": {
            "entities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Entity IDs to retrieve code for"
            }
        },
        "required": ["entities"]
    }
)
```

### 2. Rewrite USAGE.md

```markdown
# LocAgent MCP - Code Navigation Tools

## Quick Start

**Step 1: Initialize (required first)**
```
init_repository(repo_path="/absolute/path/to/repo")
```

**Step 2: Explore structure**
```
get_dependencies(entities=["/"], depth=2)
```

**Step 3: Search for code**
```
search_code(query=["MyClass", "handler"])
```

**Step 4: Get full code**
```
get_code(entities=["src/utils.py:MyClass.process"])
```

## Common Patterns

### Find where a function is called from
```
get_dependencies(entities=["src/api.py:handle_request"], direction="incoming")
```

### Find what a class depends on
```
get_dependencies(entities=["src/models.py:User"], direction="outgoing")
```

### Search then get details
```
search_code(query=["authenticate"])  # Find matches
get_code(entities=["src/auth.py:authenticate"])  # Get full code
```

## Entity ID Format
- **Files**: `path/to/file.py`
- **Classes**: `path/to/file.py:ClassName`  
- **Methods**: `path/to/file.py:ClassName.method_name`
- **Functions**: `path/to/file.py:function_name`
- **Root dir**: `/`

## Troubleshooting
- **"Repository not initialized"**: Call `init_repository` first
- **"Invalid entity"**: Check entity ID format matches examples above
- **No results**: Try broader search terms or check `get_status()`
```

### 3. State.py Update - Better Error Messages

Add user-friendly error messages that guide recovery:
```python
def init_repository(repo_path: str, force_rebuild: bool = False) -> str:
    if not os.path.isabs(repo_path):
        return f"Error: repo_path must be absolute. Got '{repo_path}'. Use full path like '/home/user/project'"
    # ... rest
```

---

## Summary of Changes

| Current Name | New Name | Key Improvement |
|-------------|----------|-----------------|
| `init_repository` | (keep) | Remove `force_rebuild` param, clarify absolute path |
| `explore_tree_structure` | `get_dependencies` | Rename direction values, remove advanced filters |
| `search_code_snippets` | `search_code` | Simpler param names, clearer examples |
| `get_entity_contents` | `get_code` | Shorter name, inline examples |
| `get_status` | (keep) | No changes needed |

**USAGE.md**: Complete rewrite with concrete examples, common patterns, and troubleshooting.