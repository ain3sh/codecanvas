## LocAgent MCP Tools

**FIRST: Match your task to the right tool:**

| Your task says... | Do this |
|-------------------|---------|
| "what calls X" / "find callers" / "who uses" | `get_dependencies(direction="incoming")` |
| "what does X use" / "dependencies" / "imports" | `get_dependencies(direction="outgoing")` |
| "show code" / "implementation of" | `search_code` → `get_code` |
| "find pattern" / "secrets" / "API keys" / "text" | **USE GREP NOT THESE TOOLS** |

**REQUIRED FIRST:** `init_repository(repo_path="/absolute/path")`

**Tools:**
- `get_dependencies(entities=["file.py:Func"], direction="incoming|outgoing")` - relationships
- `search_code(query=["keyword"])` - find by name
- `get_code(entities=["file.py:Class"])` - get source

**Entity format:** `file.py` | `file.py:Class` | `file.py:Class.method`

```
init_repository(repo_path="/project")
get_dependencies(entities=["api.py:save"], direction="incoming")   # who calls save()?
get_dependencies(entities=["db.py:Database"], direction="outgoing") # what does Database use?
search_code(query=["Config"]) → get_code(entities=["config.py:Config"])
```
