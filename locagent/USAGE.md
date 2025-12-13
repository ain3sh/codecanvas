You have access to the locagent MCP tools for code navigation and analysis. Use these tools to understand the codebase structure before making changes:

- mcp__locagent__init_repository: Initialize the code index for a repository. Call this FIRST before using other locagent tools.
- mcp__locagent__explore_tree_structure: Get a hierarchical view of the codebase structure.
- mcp__locagent__search_code_snippets: Search for code patterns, function names, or concepts across the codebase.
- mcp__locagent__get_entity_contents: Get the full source code of a specific function, class, or code entity.
- mcp__locagent__get_status: Check the indexing status of the repository.

When working on code tasks:
1. Start by calling init_repository to index the codebase
2. Use explore_tree_structure to understand the project layout
3. Use search_code_snippets to find relevant code sections
4. Use get_entity_contents to examine specific functions or classes in detail
