"""Core data models for CodeCanvas."""

from dataclasses import dataclass, field
from typing import Optional, List, Set, Dict
from enum import Enum


class SymbolKind(Enum):
    """Types of code symbols we track."""
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"


@dataclass
class Symbol:
    """A code symbol (function, class, method, etc.)."""
    
    id: str                         # Unique: "file_path:name" or "file_path:class.method"
    name: str                       # Simple name
    kind: SymbolKind
    file_path: str                  # Absolute path to file
    line_start: int                 # 1-indexed
    line_end: int
    signature: str                  # Full signature line
    docstring: Optional[str] = None
    parent_id: Optional[str] = None # Containing class/module symbol id
    
    def __hash__(self):
        return hash(self.id)
    
    def __eq__(self, other):
        if isinstance(other, Symbol):
            return self.id == other.id
        return False
    
    @property
    def short_id(self) -> str:
        """Shorter display id: filename:name."""
        import os
        filename = os.path.basename(self.file_path)
        return f"{filename}:{self.name}"


@dataclass
class CallSite:
    """A location where one symbol references another."""
    
    caller_id: str                          # Symbol id of the caller
    callee_name: str                        # Name being called (may be unresolved)
    line: int                               # Line number of the call
    column: int                             # Column of the call
    resolved_target_id: Optional[str] = None # Resolved symbol id (via LSP or heuristics)
    call_type: str = "call"                 # call, import, attribute, inherit
    
    def __hash__(self):
        return hash((self.caller_id, self.callee_name, self.line, self.column))


@dataclass
class CodeGraph:
    """
    Bidirectional code graph with symbols and their relationships.
    
    Primary data structure for CodeCanvas - optimized for reverse lookups.
    """
    
    symbols: Dict[str, Symbol] = field(default_factory=dict)
    call_sites: List[CallSite] = field(default_factory=list)
    
    # Forward edges: symbol_id -> list of symbol_ids it calls
    calls: Dict[str, Set[str]] = field(default_factory=lambda: {})
    
    # Reverse edges: symbol_id -> list of symbol_ids that call it (CRITICAL)
    called_by: Dict[str, Set[str]] = field(default_factory=lambda: {})
    
    # Module-level imports: file_path -> list of imported module paths
    imports: Dict[str, Set[str]] = field(default_factory=lambda: {})
    
    def add_symbol(self, symbol: Symbol) -> None:
        """Add a symbol to the graph."""
        self.symbols[symbol.id] = symbol
        if symbol.id not in self.calls:
            self.calls[symbol.id] = set()
        if symbol.id not in self.called_by:
            self.called_by[symbol.id] = set()
    
    def add_edge(self, caller_id: str, callee_id: str) -> None:
        """Add a directed edge (call relationship)."""
        if caller_id not in self.calls:
            self.calls[caller_id] = set()
        if callee_id not in self.called_by:
            self.called_by[callee_id] = set()
        
        self.calls[caller_id].add(callee_id)
        self.called_by[callee_id].add(caller_id)
    
    def get_direct_callers(self, symbol_id: str) -> List[Symbol]:
        """Get symbols that directly call this symbol."""
        caller_ids = self.called_by.get(symbol_id, set())
        return [self.symbols[cid] for cid in caller_ids if cid in self.symbols]
    
    def get_direct_callees(self, symbol_id: str) -> List[Symbol]:
        """Get symbols that this symbol directly calls."""
        callee_ids = self.calls.get(symbol_id, set())
        return [self.symbols[cid] for cid in callee_ids if cid in self.symbols]
    
    def get_transitive_callers(self, symbol_id: str, max_depth: int = 5) -> List[Symbol]:
        """BFS to get all transitive callers up to max_depth."""
        visited = set()
        result = []
        queue = [(symbol_id, 0)]
        
        while queue:
            current_id, depth = queue.pop(0)
            if current_id in visited or depth > max_depth:
                continue
            visited.add(current_id)
            
            if current_id != symbol_id and current_id in self.symbols:
                result.append(self.symbols[current_id])
            
            for caller_id in self.called_by.get(current_id, set()):
                if caller_id not in visited:
                    queue.append((caller_id, depth + 1))
        
        return result


@dataclass
class ImpactAnalysis:
    """
    Result of analyzing the impact of changing a symbol.
    
    This is the primary output that helps LLMs understand side-effects.
    """
    
    target: Symbol                          # The symbol being modified
    direct_callers: List[Symbol]            # Functions that call this directly
    transitive_callers: List[Symbol]        # Full reverse call tree
    tests: List[Symbol]                     # Test functions that exercise this
    interface_dependents: List[Symbol] = field(default_factory=list)
    
    # Scratchpad state - agent marks as addressed
    addressed: Set[str] = field(default_factory=set)
    notes: Dict[str, str] = field(default_factory=dict)
    
    def mark_addressed(self, symbol_id: str) -> None:
        """Mark a dependency as handled by the agent."""
        self.addressed.add(symbol_id)
    
    def add_note(self, symbol_id: str, note: str) -> None:
        """Add a note about a symbol."""
        self.notes[symbol_id] = note
    
    def remaining(self) -> List[Symbol]:
        """Get symbols that haven't been addressed yet."""
        all_deps = set(s.id for s in self.direct_callers + self.tests)
        remaining_ids = all_deps - self.addressed
        
        all_symbols = {s.id: s for s in self.direct_callers + self.tests}
        return [all_symbols[sid] for sid in remaining_ids if sid in all_symbols]
    
    @property
    def is_complete(self) -> bool:
        """Check if all dependencies have been addressed."""
        return len(self.remaining()) == 0
