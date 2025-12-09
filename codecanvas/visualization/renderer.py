"""
Graph visualization using NetworkX and Matplotlib.

Renders the CodeCanvas dependency graph as a visual image with:
- Nodes sized by caller count (impact)
- Colors by file/module clustering
- Edges showing call relationships
- Highlights for impact analysis results
"""

import os
from pathlib import Path
from typing import Optional, List, Set, Dict, Tuple
from collections import defaultdict

try:
    import networkx as nx
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.colors import to_rgba
    HAS_VISUALIZATION = True
except ImportError:
    HAS_VISUALIZATION = False

from ..core.models import CodeGraph, Symbol, ImpactAnalysis


# Color palette for file/module clusters
CLUSTER_COLORS = [
    '#4E79A7',  # Blue
    '#F28E2B',  # Orange  
    '#E15759',  # Red
    '#76B7B2',  # Teal
    '#59A14F',  # Green
    '#EDC948',  # Yellow
    '#B07AA1',  # Purple
    '#FF9DA7',  # Pink
    '#9C755F',  # Brown
    '#BAB0AC',  # Gray
]

HIGHLIGHT_COLOR = '#FF0000'  # Red for target
CALLER_COLOR = '#FFA500'     # Orange for direct callers
TEST_COLOR = '#00FF00'       # Green for tests
ADDRESSED_COLOR = '#808080'  # Gray for addressed


class GraphRenderer:
    """
    Renders CodeCanvas graphs as visual images.
    
    Usage:
        renderer = GraphRenderer(graph)
        renderer.render("output.png")
        
        # With impact analysis highlighting
        renderer.render_impact(impact, "impact.png")
    """
    
    def __init__(self, graph: CodeGraph):
        if not HAS_VISUALIZATION:
            raise ImportError(
                "Visualization requires networkx and matplotlib. "
                "Install with: pip install networkx matplotlib"
            )
        
        self.code_graph = graph
        self.nx_graph = self._build_networkx_graph()
        self._file_colors = self._assign_file_colors()
    
    def _build_networkx_graph(self) -> "nx.DiGraph":
        """Convert CodeGraph to NetworkX DiGraph."""
        G = nx.DiGraph()
        
        # Add nodes
        for symbol_id, symbol in self.code_graph.symbols.items():
            G.add_node(
                symbol_id,
                name=symbol.name,
                kind=symbol.kind.value,
                file=symbol.file_path,
                line=symbol.line_start,
                short_id=symbol.short_id
            )
        
        # Add edges from call relationships
        for caller_id, callees in self.code_graph.calls.items():
            for callee_id in callees:
                if caller_id in G and callee_id in G:
                    G.add_edge(caller_id, callee_id)
        
        return G
    
    def _assign_file_colors(self) -> Dict[str, str]:
        """Assign colors to files for clustering visualization."""
        files = set()
        for symbol in self.code_graph.symbols.values():
            files.add(os.path.basename(symbol.file_path))
        
        file_list = sorted(files)
        colors = {}
        for i, f in enumerate(file_list):
            colors[f] = CLUSTER_COLORS[i % len(CLUSTER_COLORS)]
        
        return colors
    
    def _get_node_color(self, node_id: str, highlights: Optional[Dict[str, str]] = None) -> str:
        """Get color for a node, considering highlights."""
        if highlights and node_id in highlights:
            return highlights[node_id]
        
        if node_id in self.code_graph.symbols:
            file_name = os.path.basename(self.code_graph.symbols[node_id].file_path)
            return self._file_colors.get(file_name, CLUSTER_COLORS[0])
        
        return CLUSTER_COLORS[0]
    
    def _get_node_size(self, node_id: str, base_size: int = 300) -> int:
        """Get node size based on caller count (impact)."""
        caller_count = len(self.code_graph.called_by.get(node_id, set()))
        # Scale: base_size for 0 callers, up to 5x for high-impact nodes
        scale = 1 + min(caller_count / 5, 4)
        return int(base_size * scale)
    
    def render(
        self,
        output_path: str,
        title: str = "CodeCanvas Dependency Graph",
        figsize: Tuple[int, int] = (16, 12),
        layout: str = "spring",
        show_labels: bool = True,
        highlights: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Render the full graph to an image file.
        
        Args:
            output_path: Path to save the image (PNG, PDF, SVG supported)
            title: Title for the graph
            figsize: Figure size in inches (width, height)
            layout: Layout algorithm ('spring', 'kamada_kawai', 'circular', 'shell')
            show_labels: Whether to show node labels
            highlights: Dict of node_id -> color for highlighting specific nodes
        
        Returns:
            Path to the saved image
        """
        if len(self.nx_graph) == 0:
            raise ValueError("Graph is empty, nothing to render")
        
        fig, ax = plt.subplots(figsize=figsize)
        
        # Compute layout
        if layout == "spring":
            pos = nx.spring_layout(self.nx_graph, k=2, iterations=50, seed=42)
        elif layout == "kamada_kawai":
            pos = nx.kamada_kawai_layout(self.nx_graph)
        elif layout == "circular":
            pos = nx.circular_layout(self.nx_graph)
        elif layout == "shell":
            pos = nx.shell_layout(self.nx_graph)
        else:
            pos = nx.spring_layout(self.nx_graph, seed=42)
        
        # Prepare node attributes
        node_colors = [self._get_node_color(n, highlights) for n in self.nx_graph.nodes()]
        node_sizes = [self._get_node_size(n) for n in self.nx_graph.nodes()]
        
        # Draw edges first (so nodes are on top)
        nx.draw_networkx_edges(
            self.nx_graph, pos,
            edge_color='#cccccc',
            alpha=0.5,
            arrows=True,
            arrowsize=10,
            connectionstyle="arc3,rad=0.1",
            ax=ax
        )
        
        # Draw nodes
        nx.draw_networkx_nodes(
            self.nx_graph, pos,
            node_color=node_colors,
            node_size=node_sizes,
            alpha=0.8,
            ax=ax
        )
        
        # Draw labels
        if show_labels:
            labels = {n: self.nx_graph.nodes[n].get('name', n.split(':')[-1]) 
                     for n in self.nx_graph.nodes()}
            nx.draw_networkx_labels(
                self.nx_graph, pos,
                labels=labels,
                font_size=8,
                font_weight='bold',
                ax=ax
            )
        
        # Add legend for file colors
        legend_patches = []
        for file_name, color in sorted(self._file_colors.items()):
            patch = mpatches.Patch(color=color, label=file_name)
            legend_patches.append(patch)
        
        if legend_patches:
            ax.legend(handles=legend_patches, loc='upper left', fontsize=8)
        
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.axis('off')
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        
        return output_path
    
    def render_impact(
        self,
        impact: ImpactAnalysis,
        output_path: str,
        addressed: Optional[Set[str]] = None,
        figsize: Tuple[int, int] = (16, 12)
    ) -> str:
        """
        Render graph with impact analysis highlighting.
        
        Highlights:
        - Target symbol in red
        - Direct callers in orange
        - Tests in green
        - Addressed items in gray
        
        Args:
            impact: ImpactAnalysis result to visualize
            output_path: Path to save the image
            addressed: Set of symbol IDs that have been addressed
            figsize: Figure size
        
        Returns:
            Path to the saved image
        """
        addressed = addressed or impact.addressed
        
        # Build highlights dict
        highlights = {}
        
        # Target in red
        highlights[impact.target.id] = HIGHLIGHT_COLOR
        
        # Direct callers in orange (unless addressed)
        for caller in impact.direct_callers:
            if caller.id in addressed:
                highlights[caller.id] = ADDRESSED_COLOR
            else:
                highlights[caller.id] = CALLER_COLOR
        
        # Tests in green (unless addressed)
        for test in impact.tests:
            if test.id in addressed:
                highlights[test.id] = ADDRESSED_COLOR
            else:
                highlights[test.id] = TEST_COLOR
        
        # Create subgraph with only relevant nodes
        relevant_nodes = {impact.target.id}
        relevant_nodes.update(c.id for c in impact.direct_callers)
        relevant_nodes.update(c.id for c in impact.transitive_callers[:20])  # Limit transitive
        relevant_nodes.update(t.id for t in impact.tests)
        
        subgraph = self.nx_graph.subgraph(
            [n for n in relevant_nodes if n in self.nx_graph]
        ).copy()
        
        if len(subgraph) == 0:
            # Fallback to full graph if subgraph is empty
            return self.render(
                output_path,
                title=f"Impact of {impact.target.short_id}",
                highlights=highlights,
                figsize=figsize
            )
        
        # Temporarily swap graph for rendering
        original_graph = self.nx_graph
        self.nx_graph = subgraph
        
        # Add legend info to title
        remaining = len(impact.remaining())
        total = len(impact.direct_callers) + len(impact.tests)
        status = f"({total - remaining}/{total} addressed)" if total > 0 else ""
        
        result = self.render(
            output_path,
            title=f"Impact Analysis: {impact.target.short_id} {status}",
            highlights=highlights,
            figsize=figsize
        )
        
        # Restore original graph
        self.nx_graph = original_graph
        
        return result
    
    def render_subgraph(
        self,
        center_node: str,
        depth: int = 2,
        output_path: str = "subgraph.png",
        direction: str = "both",
        figsize: Tuple[int, int] = (12, 10)
    ) -> str:
        """
        Render a subgraph centered on a specific node.
        
        Args:
            center_node: Node ID to center on
            depth: How many hops from center to include
            output_path: Path to save image
            direction: 'callers', 'callees', or 'both'
            figsize: Figure size
        
        Returns:
            Path to saved image
        """
        if center_node not in self.nx_graph:
            raise ValueError(f"Node {center_node} not in graph")
        
        # Collect nodes within depth
        nodes = {center_node}
        frontier = {center_node}
        
        for _ in range(depth):
            new_frontier = set()
            for node in frontier:
                if direction in ('callers', 'both'):
                    # Predecessors = callers
                    new_frontier.update(self.nx_graph.predecessors(node))
                if direction in ('callees', 'both'):
                    # Successors = callees
                    new_frontier.update(self.nx_graph.successors(node))
            nodes.update(new_frontier)
            frontier = new_frontier
        
        subgraph = self.nx_graph.subgraph(nodes).copy()
        
        # Temporarily swap
        original = self.nx_graph
        self.nx_graph = subgraph
        
        highlights = {center_node: HIGHLIGHT_COLOR}
        
        result = self.render(
            output_path,
            title=f"Subgraph: {center_node.split(':')[-1]} (depth={depth})",
            highlights=highlights,
            figsize=figsize
        )
        
        self.nx_graph = original
        return result
