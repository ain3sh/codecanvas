"""LocAgent MCP Server - wraps original LocAgent tools."""
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
            description="Initialize LocAgent for a repository. Must be called before other tools.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Absolute path to the repository root directory"
                    },
                    "force_rebuild": {
                        "type": "boolean",
                        "description": "Force rebuild the graph even if cached",
                        "default": False
                    }
                },
                "required": ["repo_path"]
            }
        ),
        Tool(
            name="explore_tree_structure",
            description="""Traverse a pre-built code graph to retrieve dependency structure around specified entities.

Entity Types: 'directory', 'file', 'class', 'function'
Dependency Types: 'contains', 'imports', 'invokes', 'inherits'

Entity ID format: 'file_path:QualifiedName' (e.g., 'src/module.py:MyClass.method')
For files/directories: just the path (e.g., 'src/module.py' or 'src/')

Example - explore repository structure:
  explore_tree_structure(start_entities=['/'], traversal_depth=2, dependency_type_filter=['contains'])

Example - find what depends on a class:
  explore_tree_structure(start_entities=['src/core.py:Engine'], direction='upstream', traversal_depth=2)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_entities": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of entity IDs to start traversal from"
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["upstream", "downstream", "both"],
                        "default": "downstream",
                        "description": "Traversal direction"
                    },
                    "traversal_depth": {
                        "type": "integer",
                        "default": 2,
                        "description": "Max depth (-1 for unlimited)"
                    },
                    "entity_type_filter": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by entity types"
                    },
                    "dependency_type_filter": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by dependency types"
                    }
                },
                "required": ["start_entities"]
            }
        ),
        Tool(
            name="search_code_snippets",
            description="""Search codebase for code snippets by keywords or line numbers.

Supports:
- Keyword search: search_code_snippets(search_terms=["MyClass", "handler"])
- Line lookup: search_code_snippets(line_nums=[10, 15], file_path_or_pattern='src/file.py')
- Pattern filter: search_code_snippets(search_terms=["auth"], file_path_or_pattern='src/**/*.py')""",
            inputSchema={
                "type": "object",
                "properties": {
                    "search_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keywords, function/class names, or code fragments to search"
                    },
                    "line_nums": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Line numbers to look up (requires file_path_or_pattern)"
                    },
                    "file_path_or_pattern": {
                        "type": "string",
                        "default": "**/*.py",
                        "description": "Glob pattern or file path to filter search"
                    }
                }
            }
        ),
        Tool(
            name="get_entity_contents",
            description="""Retrieve complete code content for specific entities.

Entity format: 'file_path:QualifiedName' or just 'file_path'
Example: get_entity_contents(['src/utils.py:Helper.process', 'src/config.py'])""",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of entity IDs to retrieve"
                    }
                },
                "required": ["entity_names"]
            }
        ),
        Tool(
            name="get_status",
            description="Get current LocAgent status and repository info",
            inputSchema={"type": "object", "properties": {}}
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == "init_repository":
            result = init_repository(
                arguments["repo_path"],
                arguments.get("force_rebuild", False)
            )
        elif name == "get_status":
            result = get_status()
        elif not is_initialized():
            result = "Error: Repository not initialized. Call init_repository first."
        elif name == "explore_tree_structure":
            result = explore_tree_structure(
                start_entities=arguments["start_entities"],
                direction=arguments.get("direction", "downstream"),
                traversal_depth=arguments.get("traversal_depth", 2),
                entity_type_filter=arguments.get("entity_type_filter"),
                dependency_type_filter=arguments.get("dependency_type_filter"),
            )
        elif name == "search_code_snippets":
            result = search_code_snippets(
                search_terms=arguments.get("search_terms"),
                line_nums=arguments.get("line_nums"),
                file_path_or_pattern=arguments.get("file_path_or_pattern", "**/*.py"),
            )
        elif name == "get_entity_contents":
            result = get_entity_contents(arguments["entity_names"])
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
