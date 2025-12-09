"""
Dependency graph construction with bidirectional edges.

Optimized for reverse lookups (called_by) which is the critical
feature for impact analysis.
"""

import os
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
from collections import defaultdict

from .models import Symbol, CallSite, CodeGraph, SymbolKind
from .parser import PythonParser, ParseResult


class DependencyGraph:
    """
    Builds and manages the CodeGraph from parsed results.
    
    Key features:
    1. Symbol resolution: matches call sites to symbol definitions
    2. Bidirectional edges: both calls and called_by are maintained
    3. Cross-file resolution: resolves imports to find symbols in other files
    """
    
    def __init__(self):
        self.graph = CodeGraph()
        self.parser = PythonParser()
        
        # Index for fast symbol lookup by name
        self._symbols_by_name: Dict[str, List[Symbol]] = defaultdict(list)
        
        # Index for fast lookup by file
        self._symbols_by_file: Dict[str, List[Symbol]] = defaultdict(list)
        
        # Module name -> file path mapping
        self._module_to_file: Dict[str, str] = {}
    
    def build_from_directory(self, dir_path: str) -> CodeGraph:
        """Build the complete graph from a directory."""
        dir_path = os.path.abspath(dir_path)
        
        # Phase 1: Parse all files
        parse_results = self.parser.parse_directory(dir_path)
        
        # Phase 2: Add all symbols to graph and build indices
        for result in parse_results:
            self._add_parse_result(result, dir_path)
        
        # Phase 3: Resolve call sites and build edges
        for result in parse_results:
            self._resolve_calls(result)
        
        return self.graph
    
    def build_from_files(self, file_paths: List[str]) -> CodeGraph:
        """Build graph from specific files."""
        parse_results = []
        
        for file_path in file_paths:
            try:
                result = self.parser.parse_file(file_path)
                parse_results.append(result)
            except Exception as e:
                print(f"Warning: Failed to parse {file_path}: {e}")
        
        # Determine common root for module resolution
        if file_paths:
            common_root = os.path.commonpath([os.path.dirname(f) for f in file_paths])
        else:
            common_root = "."
        
        for result in parse_results:
            self._add_parse_result(result, common_root)
        
        for result in parse_results:
            self._resolve_calls(result)
        
        return self.graph
    
    def _add_parse_result(self, result: ParseResult, root_dir: str) -> None:
        """Add symbols from a parse result to the graph."""
        
        # Register module name for this file
        rel_path = os.path.relpath(result.file_path, root_dir)
        module_name = self._path_to_module(rel_path)
        self._module_to_file[module_name] = result.file_path
        
        # Add symbols
        for symbol in result.symbols:
            self.graph.add_symbol(symbol)
            self._symbols_by_name[symbol.name].append(symbol)
            self._symbols_by_file[result.file_path].append(symbol)
        
        # Store imports for later resolution
        self.graph.imports[result.file_path] = set(result.imports)
        
        # Store call sites for resolution
        self.graph.call_sites.extend(result.call_sites)
    
    def _resolve_calls(self, result: ParseResult) -> None:
        """Resolve call sites to their target symbols."""
        
        file_imports = self.graph.imports.get(result.file_path, set())
        
        for call_site in result.call_sites:
            # Only process calls from this file
            if not call_site.caller_id.startswith(result.file_path):
                continue
            
            resolved = self._resolve_callee(
                call_site.callee_name,
                result.file_path,
                file_imports
            )
            
            if resolved:
                call_site.resolved_target_id = resolved.id
                self.graph.add_edge(call_site.caller_id, resolved.id)
    
    def _resolve_callee(
        self, 
        callee_name: str, 
        caller_file: str,
        imports: Set[str]
    ) -> Optional[Symbol]:
        """
        Resolve a callee name to a Symbol.
        
        Resolution order:
        1. Same file (local functions/classes)
        2. Imported modules
        3. Global name match (fallback)
        """
        
        # Handle method calls: obj.method -> try to resolve 'method'
        if "." in callee_name:
            parts = callee_name.split(".")
            # Try last part as method name
            method_name = parts[-1]
            # Also try the full qualified name
            candidates = (
                self._symbols_by_name.get(method_name, []) +
                self._symbols_by_name.get(callee_name, [])
            )
        else:
            candidates = self._symbols_by_name.get(callee_name, [])
        
        if not candidates:
            return None
        
        # Priority 1: Same file
        for symbol in candidates:
            if symbol.file_path == caller_file:
                return symbol
        
        # Priority 2: Imported modules
        for symbol in candidates:
            symbol_module = self._path_to_module(
                os.path.relpath(symbol.file_path, os.path.dirname(caller_file))
            )
            # Check if any import could resolve to this symbol
            for imp in imports:
                if imp in symbol_module or symbol_module.startswith(imp):
                    return symbol
        
        # Priority 3: First match (imprecise, but better than nothing)
        # In practice, LSP resolution should improve this
        return candidates[0] if len(candidates) == 1 else None
    
    def _path_to_module(self, file_path: str) -> str:
        """Convert file path to Python module name."""
        # Remove .py extension
        if file_path.endswith(".py"):
            file_path = file_path[:-3]
        
        # Convert path separators to dots
        module = file_path.replace(os.sep, ".").replace("/", ".")
        
        # Remove __init__ suffix
        if module.endswith(".__init__"):
            module = module[:-9]
        
        # Remove leading dots
        module = module.lstrip(".")
        
        return module
    
    def get_impact_summary(self, symbol_id: str, max_depth: int = 3) -> Dict:
        """
        Get a summary of impact for changing a symbol.
        
        Returns a dict with:
        - direct_callers: immediate callers
        - transitive_callers: all callers up to max_depth
        - call_chain: paths from symbol to callers
        """
        if symbol_id not in self.graph.symbols:
            return {"error": f"Symbol not found: {symbol_id}"}
        
        direct = self.graph.get_direct_callers(symbol_id)
        transitive = self.graph.get_transitive_callers(symbol_id, max_depth)
        
        return {
            "target": self.graph.symbols[symbol_id],
            "direct_callers": direct,
            "transitive_callers": transitive,
            "direct_count": len(direct),
            "transitive_count": len(transitive),
        }
    
    def find_symbol(self, query: str) -> List[Symbol]:
        """
        Find symbols matching a query.
        
        Query can be:
        - Simple name: "validate_token"
        - File:name: "auth.py:validate_token"
        - Partial match: "validate"
        """
        results = []
        
        # Exact name match
        if query in self._symbols_by_name:
            results.extend(self._symbols_by_name[query])
        
        # File:name format
        if ":" in query and not results:
            file_part, name_part = query.rsplit(":", 1)
            for symbol in self._symbols_by_name.get(name_part, []):
                if file_part in symbol.file_path:
                    results.append(symbol)
        
        # Partial match fallback
        if not results:
            query_lower = query.lower()
            for name, symbols in self._symbols_by_name.items():
                if query_lower in name.lower():
                    results.extend(symbols)
        
        return results
    
    def get_symbols_in_file(self, file_path: str) -> List[Symbol]:
        """Get all symbols defined in a file."""
        file_path = os.path.abspath(file_path)
        return self._symbols_by_file.get(file_path, [])
