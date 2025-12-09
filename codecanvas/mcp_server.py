#!/usr/bin/env python3
"""
CodeCanvas MCP Server - Static Impact Analysis for LLM Agents

This MCP server provides tools to help LLM agents understand the ripple effects
of code changes, compensating for their blind spot in predicting side-effects.

Primary workflow:
1. Agent identifies target to modify
2. Query impact_of to see what breaks
3. Mark dependencies as addressed while working
4. Check remaining before declaring done
"""

import os
import json
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict

from mcp.server.fastmcp import FastMCP

from .scratchpad.canvas import CodeCanvas

# Initialize MCP server
mcp = FastMCP("codecanvas_mcp")

# Global canvas instance (initialized per-session)
_canvas: Optional[CodeCanvas] = None
_canvas_path: Optional[str] = None

# Constants
CHARACTER_LIMIT = 25000


class ResponseFormat(str, Enum):
    """Output format for tool responses."""
    MARKDOWN = "markdown"
    JSON = "json"
    BRIEF = "brief"


# ============================================================================
# Input Models
# ============================================================================

class InitCanvasInput(BaseModel):
    """Input for initializing the canvas from a directory."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    path: str = Field(
        ..., 
        description="Absolute path to the repository or directory to analyze",
        min_length=1
    )


class SymbolQueryInput(BaseModel):
    """Input for querying a symbol."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    symbol: str = Field(
        ...,
        description="Symbol to query - can be: name ('validate_token'), "
                    "file:name ('auth.py:validate_token'), or partial match",
        min_length=1,
        max_length=500
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' for readable checklist, 'json' for structured data, 'brief' for one-line summary"
    )


class ImpactQueryInput(BaseModel):
    """Input for impact analysis."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    symbol: str = Field(
        ...,
        description="Symbol to analyze impact for (function, method, or class name)",
        min_length=1,
        max_length=500
    )
    depth: int = Field(
        default=3,
        description="How many levels of transitive callers to include (1-10)",
        ge=1,
        le=10
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' for checklist, 'json' for structured, 'brief' for summary"
    )


class MarkAddressedInput(BaseModel):
    """Input for marking a symbol as addressed."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    symbol: str = Field(
        ...,
        description="Symbol ID or name to mark as addressed (handled by agent)",
        min_length=1
    )
    note: Optional[str] = Field(
        default=None,
        description="Optional note about how it was addressed",
        max_length=500
    )


class AddNoteInput(BaseModel):
    """Input for adding a note to a symbol."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    symbol: str = Field(..., description="Symbol to add note to", min_length=1)
    note: str = Field(..., description="Note content", min_length=1, max_length=1000)


class FindSymbolInput(BaseModel):
    """Input for searching symbols."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    query: str = Field(
        ...,
        description="Search query - matches against symbol names and file paths",
        min_length=1,
        max_length=200
    )
    limit: int = Field(
        default=20,
        description="Maximum number of results to return",
        ge=1,
        le=100
    )


class HighImpactInput(BaseModel):
    """Input for finding high-impact symbols."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    min_callers: int = Field(
        default=5,
        description="Minimum number of callers to be considered high-impact",
        ge=1,
        le=100
    )
    limit: int = Field(
        default=20,
        description="Maximum results to return",
        ge=1,
        le=100
    )


# ============================================================================
# Helper Functions
# ============================================================================

def _ensure_canvas(path: Optional[str] = None) -> str:
    """Ensure canvas is initialized, return error message if not."""
    global _canvas, _canvas_path
    
    if path:
        try:
            _canvas = CodeCanvas.from_directory(path)
            _canvas_path = path
            stats = _canvas.stats()
            return f"Canvas initialized: {stats['total_symbols']} symbols from {stats['files']} files"
        except Exception as e:
            return f"Error initializing canvas: {str(e)}"
    
    if _canvas is None:
        return "Error: Canvas not initialized. Call codecanvas_init first with the repository path."
    
    return ""


def _truncate_response(response: str, message: str = "") -> str:
    """Truncate response if too long."""
    if len(response) <= CHARACTER_LIMIT:
        return response
    
    truncated = response[:CHARACTER_LIMIT - 200]
    truncated += f"\n\n---\n**TRUNCATED**: Response exceeded {CHARACTER_LIMIT} characters. {message}"
    return truncated


# ============================================================================
# MCP Tools
# ============================================================================

@mcp.tool(
    name="codecanvas_init",
    annotations={
        "title": "Initialize CodeCanvas",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def codecanvas_init(params: InitCanvasInput) -> str:
    """
    Initialize CodeCanvas for a repository.
    
    This MUST be called first before using any other CodeCanvas tools.
    Parses the codebase and builds the dependency graph for impact analysis.
    
    Args:
        params: Contains path to the repository directory
    
    Returns:
        Success message with statistics, or error message
    
    Example:
        codecanvas_init(path="/home/user/myproject")
    """
    result = _ensure_canvas(params.path)
    
    if result.startswith("Error"):
        return result
    
    stats = _canvas.stats()
    return f"""# CodeCanvas Initialized

**Path:** {params.path}
**Symbols:** {stats['total_symbols']} ({stats['functions']} functions, {stats['classes']} classes)
**Files:** {stats['files']}
**Call Edges:** {stats['total_edges']}
**Tests:** {stats['tests']}

Canvas is ready. Use `codecanvas_impact_of` to analyze change impact."""


@mcp.tool(
    name="codecanvas_impact_of",
    annotations={
        "title": "Analyze Change Impact",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def codecanvas_impact_of(params: ImpactQueryInput) -> str:
    """
    Analyze the impact of modifying a symbol.
    
    PRIMARY TOOL: Use this BEFORE making changes to understand side effects.
    Returns a checklist of:
    - Direct callers (MUST update if signature changes)
    - Tests (MUST run after changes)
    - Transitive callers (review for broader impact)
    
    Args:
        params: Symbol to analyze, depth, and response format
    
    Returns:
        Checklist of dependencies to address, or error message
    
    Example:
        codecanvas_impact_of(symbol="validate_token", depth=3)
    
    Workflow:
        1. Call this before modifying any function/class
        2. Review the checklist of affected code
        3. Use codecanvas_mark_addressed as you handle each item
        4. Call codecanvas_remaining to verify all addressed
    """
    error = _ensure_canvas()
    if error:
        return error
    
    impact = _canvas.impact_of(params.symbol, depth=params.depth)
    
    if not impact:
        # Try to find similar symbols
        similar = _canvas.find(params.symbol)
        if similar:
            suggestions = ", ".join([s.short_id for s in similar[:5]])
            return f"Error: Symbol '{params.symbol}' not found. Did you mean: {suggestions}?"
        return f"Error: Symbol '{params.symbol}' not found. Use codecanvas_find to search."
    
    response = _canvas.render(format=params.response_format.value)
    return _truncate_response(response, "Use more specific symbol query or reduce depth.")


@mcp.tool(
    name="codecanvas_callers_of",
    annotations={
        "title": "Get Symbol Callers",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def codecanvas_callers_of(params: SymbolQueryInput) -> str:
    """
    Get all direct callers of a symbol.
    
    Use this to understand what code depends on a function/method.
    Useful for quick lookups without full impact analysis.
    
    Args:
        params: Symbol to find callers for
    
    Returns:
        List of functions/methods that call this symbol
    """
    error = _ensure_canvas()
    if error:
        return error
    
    callers = _canvas.callers_of(params.symbol)
    
    if not callers:
        return f"No callers found for '{params.symbol}'. It may be unused or an entry point."
    
    if params.response_format == ResponseFormat.JSON:
        data = [{
            "id": c.id,
            "name": c.name,
            "file": c.file_path,
            "line": c.line_start,
            "signature": c.signature
        } for c in callers]
        return json.dumps({"callers": data, "count": len(data)}, indent=2)
    
    lines = [f"# Callers of `{params.symbol}` ({len(callers)})\n"]
    for caller in callers:
        lines.append(f"- `{caller.short_id}` (line {caller.line_start})")
        lines.append(f"    {caller.signature}")
    
    return "\n".join(lines)


@mcp.tool(
    name="codecanvas_tests_for",
    annotations={
        "title": "Find Tests for Symbol",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def codecanvas_tests_for(params: SymbolQueryInput) -> str:
    """
    Find test functions that cover a symbol.
    
    Use AFTER making changes to know which tests to run.
    Uses multiple strategies: naming conventions, imports, and call analysis.
    
    Args:
        params: Symbol to find tests for
    
    Returns:
        List of test functions that likely test this symbol
    """
    error = _ensure_canvas()
    if error:
        return error
    
    tests = _canvas.tests_for(params.symbol)
    
    if not tests:
        return f"No tests found for '{params.symbol}'. Consider adding test coverage."
    
    if params.response_format == ResponseFormat.JSON:
        data = [{"id": t.id, "name": t.name, "file": t.file_path} for t in tests]
        return json.dumps({"tests": data, "count": len(data)}, indent=2)
    
    lines = [f"# Tests for `{params.symbol}` ({len(tests)})\n"]
    for test in tests:
        test_file = os.path.basename(test.file_path)
        lines.append(f"- `{test_file}::{test.name}`")
    
    return "\n".join(lines)


@mcp.tool(
    name="codecanvas_mark_addressed",
    annotations={
        "title": "Mark Dependency Addressed",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def codecanvas_mark_addressed(params: MarkAddressedInput) -> str:
    """
    Mark a dependency as addressed (handled).
    
    SCRATCHPAD TOOL: Use this as you work through the impact checklist.
    Marks items as done so codecanvas_remaining shows what's left.
    
    Args:
        params: Symbol to mark and optional note
    
    Returns:
        Confirmation and remaining count
    
    Example:
        codecanvas_mark_addressed(symbol="api/routes.py:handler", note="Updated to pass new param")
    """
    error = _ensure_canvas()
    if error:
        return error
    
    success = _canvas.mark_addressed(params.symbol)
    
    if not success:
        return f"Error: Could not find symbol '{params.symbol}' to mark as addressed."
    
    if params.note:
        _canvas.add_note(params.symbol, params.note)
    
    remaining = _canvas.remaining()
    
    if remaining:
        return f"Marked `{params.symbol}` as addressed. **{len(remaining)} items remaining.**"
    else:
        return f"Marked `{params.symbol}` as addressed. **All dependencies addressed!**"


@mcp.tool(
    name="codecanvas_remaining",
    annotations={
        "title": "Show Remaining Dependencies",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def codecanvas_remaining(params: SymbolQueryInput) -> str:
    """
    Show dependencies that haven't been addressed yet.
    
    Use this to check progress and verify completion before finishing.
    
    Returns:
        List of unaddressed dependencies, or completion message
    """
    error = _ensure_canvas()
    if error:
        return error
    
    remaining = _canvas.remaining()
    
    if not remaining:
        return "**All dependencies addressed!** Safe to proceed."
    
    if params.response_format == ResponseFormat.JSON:
        data = [{"id": s.id, "name": s.name, "file": s.file_path} for s in remaining]
        return json.dumps({"remaining": data, "count": len(data)}, indent=2)
    
    lines = [f"# Remaining ({len(remaining)})\n"]
    for sym in remaining:
        lines.append(f"- [ ] `{sym.short_id}` (line {sym.line_start})")
    
    lines.append(f"\n**{len(remaining)} items still need attention.**")
    return "\n".join(lines)


@mcp.tool(
    name="codecanvas_find",
    annotations={
        "title": "Search Symbols",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def codecanvas_find(params: FindSymbolInput) -> str:
    """
    Search for symbols by name or pattern.
    
    Use this to discover symbols when you don't know the exact name.
    Matches against symbol names and file paths.
    
    Args:
        params: Search query and limit
    
    Returns:
        List of matching symbols
    """
    error = _ensure_canvas()
    if error:
        return error
    
    results = _canvas.find(params.query)
    
    if not results:
        return f"No symbols matching '{params.query}' found."
    
    results = results[:params.limit]
    
    lines = [f"# Symbols matching `{params.query}` ({len(results)})\n"]
    for sym in results:
        lines.append(f"- `{sym.id}`")
        lines.append(f"    {sym.kind.value}: {sym.signature}")
    
    return "\n".join(lines)


@mcp.tool(
    name="codecanvas_high_impact",
    annotations={
        "title": "Find High-Impact Symbols",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def codecanvas_high_impact(params: HighImpactInput) -> str:
    """
    Find symbols with many callers (high-impact if changed).
    
    Use this to identify "dangerous" code - functions that many other
    parts of the codebase depend on. Changes here have wide ripple effects.
    
    Args:
        params: Minimum caller count threshold
    
    Returns:
        List of high-impact symbols sorted by caller count
    """
    error = _ensure_canvas()
    if error:
        return error
    
    high_impact = _canvas.analyzer.find_high_impact_symbols(min_callers=params.min_callers)
    
    if not high_impact:
        return f"No symbols with {params.min_callers}+ callers found."
    
    high_impact = high_impact[:params.limit]
    
    lines = [f"# High-Impact Symbols (>= {params.min_callers} callers)\n"]
    lines.append("*Changing these affects many parts of the codebase.*\n")
    
    for sym in high_impact:
        caller_count = len(_canvas.graph.called_by.get(sym.id, set()))
        lines.append(f"- `{sym.short_id}` ({caller_count} callers)")
    
    return "\n".join(lines)


@mcp.tool(
    name="codecanvas_stats",
    annotations={
        "title": "Codebase Statistics",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def codecanvas_stats(params: SymbolQueryInput) -> str:
    """
    Get statistics about the analyzed codebase.
    
    Returns symbol counts, file counts, and dependency metrics.
    """
    error = _ensure_canvas()
    if error:
        return error
    
    stats = _canvas.stats()
    
    if params.response_format == ResponseFormat.JSON:
        return json.dumps(stats, indent=2)
    
    return f"""# CodeCanvas Statistics

**Repository:** {_canvas_path}

| Metric | Count |
|--------|-------|
| Total Symbols | {stats['total_symbols']} |
| Functions/Methods | {stats['functions']} |
| Classes | {stats['classes']} |
| Files | {stats['files']} |
| Call Edges | {stats['total_edges']} |
| Test Functions | {stats['tests']} |
"""


# Entry point for running the server
def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
