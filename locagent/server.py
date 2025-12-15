"""LocAgent MCP Server - Code navigation and dependency analysis tools."""
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from locagent.state import init_repository, is_initialized, get_status
from locagent.core.location_tools.repo_ops.repo_ops import (
    explore_tree_structure,
    search_code_snippets,
    get_entity_contents,
)

server = Server("locagent")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="init_repository",
            description="Initialize code index for a repository. MUST call first before other tools. Returns node/edge count on success.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Absolute path to repository root (e.g., '/home/user/myproject')"
                    }
                },
                "required": ["repo_path"]
            }
        ),
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
                "type": "object",
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
        ),
        Tool(
            name="search_code",
            description="""Search codebase by keywords or lookup specific lines.

EXAMPLES:
- Find function: search_code(query=["process_data"])
- Find in specific file: search_code(query=["handler"], files="src/api/*.py")
- Get lines 10-20: search_code(lines=[10,15,20], files="src/main.py")""",
            inputSchema={
                "type": "object",
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
        ),
        Tool(
            name="get_code",
            description="""Get complete source code for specific entities.

FORMAT: 'file_path' or 'file_path:ClassName' or 'file_path:ClassName.method'

EXAMPLES:
- Full file: get_code(entities=['src/config.py'])
- Specific class: get_code(entities=['src/models.py:User'])
- Specific method: get_code(entities=['src/models.py:User.save'])""",
            inputSchema={
                "type": "object",
                "properties": {
                    "entities": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Entity IDs to retrieve code for"
                    }
                },
                "required": ["entities"]
            }
        ),
        Tool(
            name="get_status",
            description="Check if repository is initialized and get index statistics.",
            inputSchema={"type": "object", "properties": {}}
        )
    ]


def _map_direction(direction: str) -> str:
    """Map user-friendly direction names to internal names."""
    return {"outgoing": "downstream", "incoming": "upstream", "both": "both"}.get(direction, "downstream")


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == "init_repository":
            result = init_repository(arguments["repo_path"])
        elif name == "get_status":
            result = get_status()
        elif not is_initialized():
            result = "Error: Repository not initialized. Call init_repository(repo_path='/absolute/path/to/repo') first."
        elif name == "get_dependencies":
            result = explore_tree_structure(
                start_entities=arguments["entities"],
                direction=_map_direction(arguments.get("direction", "outgoing")),
                traversal_depth=arguments.get("depth", 2),
            )
        elif name == "search_code":
            result = search_code_snippets(
                search_terms=arguments.get("query"),
                line_nums=arguments.get("lines"),
                file_path_or_pattern=arguments.get("files", "**/*.py"),
            )
        elif name == "get_code":
            result = get_entity_contents(arguments["entities"])
        else:
            result = f"Unknown tool: {name}"
        
        return [TextContent(type="text", text=str(result))]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
