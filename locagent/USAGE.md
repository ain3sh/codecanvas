## LocAgent MCP Tools

Use these MCP tools for code navigation. Call `init_repository` first before other tools.

**Tools:**
- `init_repository(repo_path="/abs/path")` - Initialize index (required first)
- `get_dependencies(entities=["path.py:Name"], direction="outgoing|incoming", depth=2)` - Find relationships
- `search_code(query=["keyword"], files="**/*.py")` - Search by keywords
- `search_code(lines=[10,20], files="src/main.py")` - Get specific lines
- `get_code(entities=["path.py:ClassName"])` - Get full source

**Entity format:** `file.py` | `file.py:Class` | `file.py:Class.method` | `/` (root)

**Examples:**
```
init_repository(repo_path="/home/user/myproject")
get_dependencies(entities=["/"], depth=2)  # explore structure
get_dependencies(entities=["src/api.py:handler"], direction="incoming")  # find callers
search_code(query=["MyClass"])  # then get_code for full source
```

If errors occur, verify `init_repository` was called with an absolute path.
