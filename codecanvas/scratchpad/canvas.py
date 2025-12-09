"""
CodeCanvas: The main scratchpad interface for LLM agents.

Provides:
1. Impact analysis queries
2. Mutable state tracking (addressed, notes)
3. Checklist rendering for LLM consumption
"""

import os
import json
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, field
from pathlib import Path

from ..core.models import Symbol, CodeGraph, ImpactAnalysis
from ..core.graph import DependencyGraph
from ..analysis.impact import ImpactAnalyzer
from .checklist import ChecklistRenderer


@dataclass
class CanvasState:
    """Persistent state for a canvas session."""
    addressed: Set[str] = field(default_factory=set)
    notes: Dict[str, str] = field(default_factory=dict)
    flags: Dict[str, str] = field(default_factory=dict)  # symbol_id -> flag (e.g., "issue", "done")
    history: List[str] = field(default_factory=list)  # Query history


class CodeCanvas:
    """
    Main interface for CodeCanvas - the LLM agent's scratchpad.
    
    Usage:
        canvas = CodeCanvas.from_directory("/path/to/repo")
        
        # Query impact
        impact = canvas.impact_of("validate_token")
        print(canvas.render())
        
        # Mark progress
        canvas.mark_addressed("api/routes.py:handler")
        print(canvas.remaining())
    """
    
    def __init__(self, graph: CodeGraph):
        self.graph = graph
        self.analyzer = ImpactAnalyzer(graph)
        self.renderer = ChecklistRenderer()
        self.state = CanvasState()
        
        # Current analysis (most recent query)
        self._current_impact: Optional[ImpactAnalysis] = None
    
    @classmethod
    def from_directory(cls, dir_path: str) -> "CodeCanvas":
        """Create a canvas from a directory."""
        builder = DependencyGraph()
        graph = builder.build_from_directory(dir_path)
        return cls(graph)
    
    @classmethod
    def from_files(cls, file_paths: List[str]) -> "CodeCanvas":
        """Create a canvas from specific files."""
        builder = DependencyGraph()
        graph = builder.build_from_files(file_paths)
        return cls(graph)
    
    # === Primary Query Interface ===
    
    def impact_of(self, symbol_query: str, depth: int = 3) -> Optional[ImpactAnalysis]:
        """
        Analyze impact of changing a symbol.
        
        This is the primary query - answers "what breaks if I change X?"
        
        Args:
            symbol_query: Symbol name, file:name, or partial match
            depth: How many levels of transitive callers
        
        Returns:
            ImpactAnalysis with direct_callers, transitive_callers, tests
        """
        impact = self.analyzer.analyze(symbol_query, max_depth=depth)
        
        if impact:
            self._current_impact = impact
            # Copy existing state to the new analysis
            impact.addressed = self.state.addressed.copy()
            impact.notes = self.state.notes.copy()
            self.state.history.append(symbol_query)
        
        return impact
    
    def callers_of(self, symbol_query: str) -> List[Symbol]:
        """Get direct callers of a symbol."""
        symbol = self.analyzer._resolve_symbol(symbol_query)
        if symbol:
            return self.graph.get_direct_callers(symbol.id)
        return []
    
    def callees_of(self, symbol_query: str) -> List[Symbol]:
        """Get symbols that a symbol calls."""
        symbol = self.analyzer._resolve_symbol(symbol_query)
        if symbol:
            return self.graph.get_direct_callees(symbol.id)
        return []
    
    def tests_for(self, symbol_query: str) -> List[Symbol]:
        """Find tests that cover a symbol."""
        symbol = self.analyzer._resolve_symbol(symbol_query)
        if symbol:
            return self.analyzer.test_mapper.find_tests_for(symbol.id)
        return []
    
    def find(self, query: str) -> List[Symbol]:
        """Search for symbols by name."""
        results = []
        query_lower = query.lower()
        
        for symbol in self.graph.symbols.values():
            if query_lower in symbol.name.lower() or query_lower in symbol.id.lower():
                results.append(symbol)
        
        return results
    
    # === Scratchpad State Management ===
    
    def mark_addressed(self, symbol_query: str) -> bool:
        """Mark a symbol as addressed (handled by the agent)."""
        symbol = self.analyzer._resolve_symbol(symbol_query)
        if symbol:
            self.state.addressed.add(symbol.id)
            if self._current_impact:
                self._current_impact.addressed.add(symbol.id)
            return True
        return False
    
    def unmark_addressed(self, symbol_query: str) -> bool:
        """Remove addressed mark from a symbol."""
        symbol = self.analyzer._resolve_symbol(symbol_query)
        if symbol:
            self.state.addressed.discard(symbol.id)
            if self._current_impact:
                self._current_impact.addressed.discard(symbol.id)
            return True
        return False
    
    def add_note(self, symbol_query: str, note: str) -> bool:
        """Add a note to a symbol."""
        symbol = self.analyzer._resolve_symbol(symbol_query)
        if symbol:
            self.state.notes[symbol.id] = note
            if self._current_impact:
                self._current_impact.notes[symbol.id] = note
            return True
        return False
    
    def flag(self, symbol_query: str, flag: str) -> bool:
        """Flag a symbol (e.g., 'issue', 'done', 'skip')."""
        symbol = self.analyzer._resolve_symbol(symbol_query)
        if symbol:
            self.state.flags[symbol.id] = flag
            return True
        return False
    
    def remaining(self) -> List[Symbol]:
        """Get symbols that haven't been addressed yet."""
        if self._current_impact:
            return self._current_impact.remaining()
        return []
    
    def is_complete(self) -> bool:
        """Check if all dependencies have been addressed."""
        if self._current_impact:
            return self._current_impact.is_complete
        return True
    
    # === Output Rendering ===
    
    def render(self, format: str = "markdown") -> str:
        """
        Render current analysis as text.
        
        Args:
            format: "markdown" (default), "json", or "brief"
        """
        if not self._current_impact:
            return "No analysis loaded. Call impact_of() first."
        
        if format == "json":
            return self._render_json()
        elif format == "brief":
            return self.renderer.render_brief(self._current_impact, self.state)
        else:
            return self.renderer.render_markdown(self._current_impact, self.state)
    
    def _render_json(self) -> str:
        """Render as JSON for programmatic use."""
        if not self._current_impact:
            return "{}"
        
        impact = self._current_impact
        return json.dumps({
            "target": {
                "id": impact.target.id,
                "name": impact.target.name,
                "file": impact.target.file_path,
                "line": impact.target.line_start,
                "signature": impact.target.signature,
            },
            "direct_callers": [
                {"id": s.id, "name": s.name, "file": s.file_path, "line": s.line_start,
                 "addressed": s.id in self.state.addressed}
                for s in impact.direct_callers
            ],
            "transitive_callers": [
                {"id": s.id, "name": s.name, "file": s.file_path, "line": s.line_start}
                for s in impact.transitive_callers
            ],
            "tests": [
                {"id": s.id, "name": s.name, "file": s.file_path,
                 "addressed": s.id in self.state.addressed}
                for s in impact.tests
            ],
            "remaining_count": len(impact.remaining()),
            "is_complete": impact.is_complete,
        }, indent=2)
    
    # === Persistence ===
    
    def save_state(self, path: str) -> None:
        """Save canvas state to a file."""
        data = {
            "addressed": list(self.state.addressed),
            "notes": self.state.notes,
            "flags": self.state.flags,
            "history": self.state.history,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    
    def load_state(self, path: str) -> None:
        """Load canvas state from a file."""
        with open(path, "r") as f:
            data = json.load(f)
        
        self.state.addressed = set(data.get("addressed", []))
        self.state.notes = data.get("notes", {})
        self.state.flags = data.get("flags", {})
        self.state.history = data.get("history", [])
    
    # === Statistics ===
    
    def stats(self) -> Dict:
        """Get statistics about the codebase."""
        return {
            "total_symbols": len(self.graph.symbols),
            "total_edges": sum(len(v) for v in self.graph.calls.values()),
            "functions": len([s for s in self.graph.symbols.values() 
                           if s.kind.value in ("function", "method")]),
            "classes": len([s for s in self.graph.symbols.values() 
                          if s.kind.value == "class"]),
            "files": len(set(s.file_path for s in self.graph.symbols.values())),
            "tests": len(self.analyzer.test_mapper.get_all_tests()),
        }
