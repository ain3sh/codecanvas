#!/usr/bin/env python3
"""
CodeCanvas CLI - Static Impact Analysis for LLM Agents

Usage:
    codecanvas analyze <path> <symbol>     Analyze impact of changing a symbol
    codecanvas callers <path> <symbol>     List callers of a symbol
    codecanvas tests <path> <symbol>       Find tests for a symbol
    codecanvas stats <path>                Show codebase statistics
    codecanvas find <path> <query>         Search for symbols
"""

import argparse
import sys
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="CodeCanvas: Static Impact Analysis for LLM Agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    codecanvas analyze ./myproject validate_token
    codecanvas callers ./myproject "auth.py:login"
    codecanvas tests ./myproject User
    codecanvas stats ./myproject
    codecanvas find ./myproject "config"
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze impact of changing a symbol")
    analyze_parser.add_argument("path", help="Path to repository or file")
    analyze_parser.add_argument("symbol", help="Symbol to analyze (name or file:name)")
    analyze_parser.add_argument("--depth", "-d", type=int, default=3, help="Max transitive depth")
    analyze_parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    analyze_parser.add_argument("--brief", "-b", action="store_true", help="Brief output")
    
    # callers command
    callers_parser = subparsers.add_parser("callers", help="List callers of a symbol")
    callers_parser.add_argument("path", help="Path to repository or file")
    callers_parser.add_argument("symbol", help="Symbol to find callers for")
    
    # tests command
    tests_parser = subparsers.add_parser("tests", help="Find tests for a symbol")
    tests_parser.add_argument("path", help="Path to repository or file")
    tests_parser.add_argument("symbol", help="Symbol to find tests for")
    
    # stats command
    stats_parser = subparsers.add_parser("stats", help="Show codebase statistics")
    stats_parser.add_argument("path", help="Path to repository")
    
    # find command
    find_parser = subparsers.add_parser("find", help="Search for symbols")
    find_parser.add_argument("path", help="Path to repository")
    find_parser.add_argument("query", help="Search query")
    
    # high-impact command
    high_parser = subparsers.add_parser("high-impact", help="Find high-impact symbols")
    high_parser.add_argument("path", help="Path to repository")
    high_parser.add_argument("--min-callers", "-m", type=int, default=5, help="Minimum caller count")
    
    # render command
    render_parser = subparsers.add_parser("render", help="Render dependency graph as image")
    render_parser.add_argument("path", help="Path to repository")
    render_parser.add_argument("--output", "-o", default="codecanvas.png", help="Output file path")
    render_parser.add_argument("--symbol", "-s", help="Center on specific symbol (renders impact view)")
    render_parser.add_argument("--layout", "-l", choices=["spring", "kamada_kawai", "circular"], default="spring")
    render_parser.add_argument("--figsize", default="16x12", help="Figure size as WxH (e.g., 16x12)")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Import here to avoid slow startup for --help
    from .scratchpad.canvas import CodeCanvas
    
    # Build canvas
    path = os.path.abspath(args.path)
    print(f"Building canvas from {path}...", file=sys.stderr)
    
    try:
        if os.path.isfile(path):
            canvas = CodeCanvas.from_files([path])
        else:
            canvas = CodeCanvas.from_directory(path)
    except Exception as e:
        print(f"Error building canvas: {e}", file=sys.stderr)
        return 1
    
    print(f"Loaded {canvas.stats()['total_symbols']} symbols", file=sys.stderr)
    print("", file=sys.stderr)
    
    # Execute command
    if args.command == "analyze":
        return cmd_analyze(canvas, args)
    elif args.command == "callers":
        return cmd_callers(canvas, args)
    elif args.command == "tests":
        return cmd_tests(canvas, args)
    elif args.command == "stats":
        return cmd_stats(canvas, args)
    elif args.command == "find":
        return cmd_find(canvas, args)
    elif args.command == "high-impact":
        return cmd_high_impact(canvas, args)
    elif args.command == "render":
        return cmd_render(canvas, args)
    
    return 0


def cmd_analyze(canvas, args):
    """Handle analyze command."""
    impact = canvas.impact_of(args.symbol, depth=args.depth)
    
    if not impact:
        print(f"Symbol not found: {args.symbol}", file=sys.stderr)
        return 1
    
    if args.json:
        print(canvas.render(format="json"))
    elif args.brief:
        print(canvas.render(format="brief"))
    else:
        print(canvas.render(format="markdown"))
    
    return 0


def cmd_callers(canvas, args):
    """Handle callers command."""
    callers = canvas.callers_of(args.symbol)
    
    if not callers:
        print(f"No callers found for: {args.symbol}")
        return 0
    
    print(f"# Callers of `{args.symbol}` ({len(callers)})")
    print("")
    
    for caller in callers:
        print(f"- `{caller.short_id}` (line {caller.line_start})")
        print(f"    {caller.signature}")
    
    return 0


def cmd_tests(canvas, args):
    """Handle tests command."""
    tests = canvas.tests_for(args.symbol)
    
    if not tests:
        print(f"No tests found for: {args.symbol}")
        return 0
    
    print(f"# Tests for `{args.symbol}` ({len(tests)})")
    print("")
    
    for test in tests:
        test_file = os.path.basename(test.file_path)
        print(f"- `{test_file}::{test.name}`")
    
    return 0


def cmd_stats(canvas, args):
    """Handle stats command."""
    stats = canvas.stats()
    
    print("# CodeCanvas Statistics")
    print("")
    print(f"- **Total Symbols:** {stats['total_symbols']}")
    print(f"- **Functions/Methods:** {stats['functions']}")
    print(f"- **Classes:** {stats['classes']}")
    print(f"- **Files:** {stats['files']}")
    print(f"- **Call Edges:** {stats['total_edges']}")
    print(f"- **Test Functions:** {stats['tests']}")
    
    return 0


def cmd_find(canvas, args):
    """Handle find command."""
    results = canvas.find(args.query)
    
    if not results:
        print(f"No symbols matching: {args.query}")
        return 0
    
    print(f"# Symbols matching `{args.query}` ({len(results)})")
    print("")
    
    for symbol in results[:20]:  # Limit output
        print(f"- `{symbol.id}`")
        print(f"    {symbol.kind.value}: {symbol.signature}")
    
    if len(results) > 20:
        print(f"\n... and {len(results) - 20} more")
    
    return 0


def cmd_high_impact(canvas, args):
    """Handle high-impact command."""
    high_impact = canvas.analyzer.find_high_impact_symbols(min_callers=args.min_callers)
    
    if not high_impact:
        print(f"No symbols with {args.min_callers}+ callers found")
        return 0
    
    print(f"# High-Impact Symbols (>= {args.min_callers} callers)")
    print("")
    
    for symbol in high_impact[:20]:
        caller_count = len(canvas.graph.called_by.get(symbol.id, set()))
        print(f"- `{symbol.short_id}` ({caller_count} callers)")
    
    if len(high_impact) > 20:
        print(f"\n... and {len(high_impact) - 20} more")
    
    return 0


def cmd_render(canvas, args):
    """Handle render command."""
    try:
        from .visualization.renderer import GraphRenderer
    except ImportError:
        print("Error: Visualization requires networkx and matplotlib.", file=sys.stderr)
        print("Install with: pip install codecanvas[viz]", file=sys.stderr)
        return 1
    
    # Parse figsize
    try:
        w, h = args.figsize.split("x")
        figsize = (int(w), int(h))
    except ValueError:
        figsize = (16, 12)
    
    renderer = GraphRenderer(canvas.graph)
    
    if args.symbol:
        # Render impact view for specific symbol
        impact = canvas.impact_of(args.symbol)
        if not impact:
            print(f"Symbol not found: {args.symbol}", file=sys.stderr)
            return 1
        
        output_path = renderer.render_impact(impact, args.output, figsize=figsize)
        print(f"Impact visualization saved to: {output_path}")
    else:
        # Render full graph
        output_path = renderer.render(
            args.output,
            title="CodeCanvas Dependency Graph",
            layout=args.layout,
            figsize=figsize
        )
        print(f"Graph visualization saved to: {output_path}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
