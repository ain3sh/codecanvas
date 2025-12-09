"""
Test mapping: finds test functions that cover production code.

Uses multiple strategies:
1. Convention-based: foo.py -> test_foo.py, tests/test_foo.py
2. Import-based: tests that import the module containing the symbol
3. Call-based: test functions that call the symbol (from reverse index)
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Set, Optional
from collections import defaultdict

from ..core.models import Symbol, CodeGraph, SymbolKind


class TestMapper:
    """
    Maps production code symbols to their test functions.
    
    Critical for answering: "What tests do I need to run after changing X?"
    """
    
    def __init__(self, graph: CodeGraph):
        self.graph = graph
        
        # Cache: symbol_id -> list of test symbol_ids
        self._test_cache: Dict[str, List[str]] = {}
        
        # All test symbols (functions starting with test_)
        self._test_symbols: List[Symbol] = []
        
        # Test file paths
        self._test_files: Set[str] = set()
        
        # Build test index
        self._build_test_index()
    
    def _build_test_index(self) -> None:
        """Identify all test functions and files."""
        
        for symbol in self.graph.symbols.values():
            # Test functions: name starts with test_
            if symbol.name.startswith("test_") and symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                self._test_symbols.append(symbol)
                self._test_files.add(symbol.file_path)
            
            # Test files: path contains test_ or tests/
            file_name = os.path.basename(symbol.file_path)
            dir_name = os.path.dirname(symbol.file_path)
            
            if file_name.startswith("test_") or "/tests/" in symbol.file_path or "\\tests\\" in symbol.file_path:
                self._test_files.add(symbol.file_path)
    
    def find_tests_for(self, symbol_id: str) -> List[Symbol]:
        """
        Find all test functions that likely test the given symbol.
        
        Combines multiple strategies for comprehensive coverage.
        """
        if symbol_id in self._test_cache:
            return [self.graph.symbols[tid] for tid in self._test_cache[symbol_id] 
                    if tid in self.graph.symbols]
        
        if symbol_id not in self.graph.symbols:
            return []
        
        symbol = self.graph.symbols[symbol_id]
        test_ids: Set[str] = set()
        
        # Strategy 1: Convention-based (test file naming)
        test_ids.update(self._find_by_convention(symbol))
        
        # Strategy 2: Call-based (tests that call this symbol)
        test_ids.update(self._find_by_calls(symbol))
        
        # Strategy 3: Import-based (tests that import this module)
        test_ids.update(self._find_by_imports(symbol))
        
        # Cache the results
        self._test_cache[symbol_id] = list(test_ids)
        
        return [self.graph.symbols[tid] for tid in test_ids if tid in self.graph.symbols]
    
    def _find_by_convention(self, symbol: Symbol) -> Set[str]:
        """
        Find tests using naming conventions.
        
        Conventions:
        - foo.py -> test_foo.py
        - foo.py -> tests/test_foo.py
        - foo.py -> foo_test.py
        - Class/function name in test function name
        """
        test_ids = set()
        
        file_name = os.path.basename(symbol.file_path)
        base_name = file_name[:-3] if file_name.endswith(".py") else file_name
        
        # Expected test file patterns
        test_file_patterns = [
            f"test_{base_name}.py",
            f"{base_name}_test.py",
            f"test_{base_name}s.py",  # plural
        ]
        
        # Find matching test files
        for test_file in self._test_files:
            test_file_name = os.path.basename(test_file)
            if test_file_name in test_file_patterns:
                # All test functions in this file are relevant
                for test_sym in self._test_symbols:
                    if test_sym.file_path == test_file:
                        test_ids.add(test_sym.id)
        
        # Also check for symbol name in test function names
        # e.g., test_validate_token tests validate_token
        symbol_name_lower = symbol.name.lower()
        for test_sym in self._test_symbols:
            test_name_lower = test_sym.name.lower()
            # test_validate_token -> validate_token
            if symbol_name_lower in test_name_lower:
                test_ids.add(test_sym.id)
        
        return test_ids
    
    def _find_by_calls(self, symbol: Symbol) -> Set[str]:
        """Find test functions that call this symbol (direct or transitive)."""
        test_ids = set()
        
        # Get all callers of this symbol
        callers = self.graph.called_by.get(symbol.id, set())
        
        for caller_id in callers:
            if caller_id in self.graph.symbols:
                caller = self.graph.symbols[caller_id]
                # Is this caller a test function?
                if caller.name.startswith("test_"):
                    test_ids.add(caller_id)
                # Is this caller in a test file? (helper function)
                elif caller.file_path in self._test_files:
                    # Find test functions that call this helper
                    helper_callers = self.graph.called_by.get(caller_id, set())
                    for hc_id in helper_callers:
                        if hc_id in self.graph.symbols:
                            hc = self.graph.symbols[hc_id]
                            if hc.name.startswith("test_"):
                                test_ids.add(hc_id)
        
        return test_ids
    
    def _find_by_imports(self, symbol: Symbol) -> Set[str]:
        """Find test files that import the module containing this symbol."""
        test_ids = set()
        
        # Get module name from symbol file path
        symbol_module = self._file_to_module(symbol.file_path)
        
        # Check which test files import this module
        for test_file in self._test_files:
            imports = self.graph.imports.get(test_file, set())
            
            for imp in imports:
                # Check if import matches our module
                if imp == symbol_module or symbol_module.endswith(f".{imp}") or imp.endswith(f".{symbol_module}"):
                    # All test functions in this file might be relevant
                    for test_sym in self._test_symbols:
                        if test_sym.file_path == test_file:
                            test_ids.add(test_sym.id)
                    break
        
        return test_ids
    
    def _file_to_module(self, file_path: str) -> str:
        """Convert file path to module name."""
        # Simple conversion: remove .py and convert separators
        if file_path.endswith(".py"):
            file_path = file_path[:-3]
        
        # Get just the filename without path for simple matching
        return os.path.basename(file_path)
    
    def get_all_tests(self) -> List[Symbol]:
        """Get all test functions in the codebase."""
        return self._test_symbols.copy()
    
    def get_test_coverage_map(self) -> Dict[str, List[str]]:
        """
        Build a map of symbol -> tests for all symbols.
        
        Expensive operation, use sparingly.
        """
        coverage = {}
        
        for symbol_id in self.graph.symbols:
            tests = self.find_tests_for(symbol_id)
            if tests:
                coverage[symbol_id] = [t.id for t in tests]
        
        return coverage
