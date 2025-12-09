"""
Impact analysis: the core query interface for CodeCanvas.

Answers: "What breaks if I change X?"
"""

from typing import List, Dict, Optional, Set
from dataclasses import dataclass, field

from ..core.models import Symbol, CodeGraph, ImpactAnalysis, SymbolKind
from .test_mapper import TestMapper


class ImpactAnalyzer:
    """
    Main interface for impact analysis queries.
    
    Usage:
        analyzer = ImpactAnalyzer(graph)
        impact = analyzer.analyze("mymodule.py:my_function")
        print(impact.render_checklist())
    """
    
    def __init__(self, graph: CodeGraph):
        self.graph = graph
        self.test_mapper = TestMapper(graph)
    
    def analyze(
        self, 
        symbol_query: str, 
        max_depth: int = 3,
        include_tests: bool = True
    ) -> Optional[ImpactAnalysis]:
        """
        Analyze the impact of changing a symbol.
        
        Args:
            symbol_query: Symbol ID or search query (e.g., "validate_token", "auth.py:validate")
            max_depth: How many levels of transitive callers to include
            include_tests: Whether to find related tests
        
        Returns:
            ImpactAnalysis object with all dependencies
        """
        # Find the target symbol
        target = self._resolve_symbol(symbol_query)
        if not target:
            return None
        
        # Get direct callers
        direct_callers = self.graph.get_direct_callers(target.id)
        
        # Get transitive callers
        transitive_callers = self.graph.get_transitive_callers(target.id, max_depth)
        
        # Remove direct callers from transitive (they're already listed)
        direct_ids = {s.id for s in direct_callers}
        transitive_callers = [s for s in transitive_callers if s.id not in direct_ids]
        
        # Find tests
        tests = []
        if include_tests:
            tests = self.test_mapper.find_tests_for(target.id)
        
        return ImpactAnalysis(
            target=target,
            direct_callers=direct_callers,
            transitive_callers=transitive_callers,
            tests=tests,
            interface_dependents=[],  # TODO: implement signature analysis
        )
    
    def _resolve_symbol(self, query: str) -> Optional[Symbol]:
        """Resolve a query to a single symbol."""
        
        # Try exact ID match first
        if query in self.graph.symbols:
            return self.graph.symbols[query]
        
        # Try name-based search
        candidates = []
        query_lower = query.lower()
        
        for symbol_id, symbol in self.graph.symbols.items():
            # Exact name match
            if symbol.name == query:
                candidates.append(symbol)
            # Partial match in ID
            elif query_lower in symbol_id.lower():
                candidates.append(symbol)
        
        if len(candidates) == 1:
            return candidates[0]
        elif len(candidates) > 1:
            # Prefer exact name matches
            exact = [c for c in candidates if c.name == query]
            if len(exact) == 1:
                return exact[0]
            # Return first match (caller should use more specific query)
            return candidates[0]
        
        return None
    
    def batch_analyze(
        self, 
        symbol_queries: List[str],
        max_depth: int = 3
    ) -> Dict[str, ImpactAnalysis]:
        """Analyze multiple symbols at once."""
        results = {}
        for query in symbol_queries:
            impact = self.analyze(query, max_depth)
            if impact:
                results[impact.target.id] = impact
        return results
    
    def find_high_impact_symbols(self, min_callers: int = 5) -> List[Symbol]:
        """
        Find symbols with many callers (high-impact if changed).
        
        Useful for identifying "dangerous" code to modify.
        """
        high_impact = []
        
        for symbol_id, symbol in self.graph.symbols.items():
            caller_count = len(self.graph.called_by.get(symbol_id, set()))
            if caller_count >= min_callers:
                high_impact.append((symbol, caller_count))
        
        # Sort by caller count descending
        high_impact.sort(key=lambda x: x[1], reverse=True)
        
        return [s for s, _ in high_impact]
    
    def get_dependency_chain(
        self, 
        from_symbol: str, 
        to_symbol: str,
        max_depth: int = 10
    ) -> Optional[List[Symbol]]:
        """
        Find the shortest path from one symbol to another.
        
        Useful for understanding how changes propagate.
        """
        from_resolved = self._resolve_symbol(from_symbol)
        to_resolved = self._resolve_symbol(to_symbol)
        
        if not from_resolved or not to_resolved:
            return None
        
        # BFS to find path
        visited = {from_resolved.id}
        queue = [(from_resolved.id, [from_resolved])]
        
        while queue:
            current_id, path = queue.pop(0)
            
            if current_id == to_resolved.id:
                return path
            
            if len(path) >= max_depth:
                continue
            
            # Check both directions
            neighbors = (
                self.graph.calls.get(current_id, set()) |
                self.graph.called_by.get(current_id, set())
            )
            
            for neighbor_id in neighbors:
                if neighbor_id not in visited and neighbor_id in self.graph.symbols:
                    visited.add(neighbor_id)
                    queue.append((neighbor_id, path + [self.graph.symbols[neighbor_id]]))
        
        return None  # No path found
