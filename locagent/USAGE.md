## LocAgent MCP Tools

**USE FIRST AND OFTEN.** Build your mental model before acting.

**Start EVERY task:**
```
init_repository(repo_path="/absolute/path")           # 1. Initialize
get_dependencies(entities=["/"], depth=2)             # 2. See structure
```

**Then explore what's relevant to your task:**

| To understand... | Use |
|------------------|-----|
| Overall structure | `get_dependencies(entities=["/"], depth=2)` |
| What calls X | `get_dependencies(entities=["file.py:X"], direction="incoming")` |
| What X depends on | `get_dependencies(entities=["file.py:X"], direction="outgoing")` |
| Find code by name | `search_code(query=["keyword"])` |
| Get full source | `get_code(entities=["file.py:X"])` |

**Entity format:** `file.py` | `file.py:Class` | `file.py:method`

**Example - sanitizing secrets:**
```
init_repository(repo_path="/project")
get_dependencies(entities=["/"], depth=2)                    # what modules exist?
search_code(query=["config", "settings", "env"])             # where might secrets live?
get_dependencies(entities=["config.py"], direction="incoming") # what uses config?
get_code(entities=["config.py:Settings"])                    # examine implementation
# NOW use Grep for specific patterns like API keys
```

**The more you explore, the better you understand. Don't skip steps.**
