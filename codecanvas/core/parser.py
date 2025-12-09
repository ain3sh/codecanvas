"""
Tree-sitter based parser for extracting symbols and call sites.

Phase 1 of CodeCanvas: Static extraction without LSP.
"""

import os
from pathlib import Path
from typing import List, Optional, Tuple, Generator
from dataclasses import dataclass

try:
    import tree_sitter_python as tspython
    from tree_sitter import Language, Parser, Node
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False

from .models import Symbol, CallSite, SymbolKind


@dataclass
class ParseResult:
    """Result of parsing a single file."""
    file_path: str
    symbols: List[Symbol]
    call_sites: List[CallSite]
    imports: List[str]


class PythonParser:
    """
    Tree-sitter based Python parser.
    
    Extracts:
    - Function definitions (with signatures and docstrings)
    - Class definitions
    - Method definitions
    - Call sites (function calls, method calls)
    - Import statements
    """
    
    def __init__(self):
        if not HAS_TREE_SITTER:
            raise ImportError(
                "tree-sitter and tree-sitter-python required. "
                "Install with: pip install tree-sitter tree-sitter-python"
            )
        
        self.language = Language(tspython.language())
        self.parser = Parser(self.language)
    
    def parse_file(self, file_path: str) -> ParseResult:
        """Parse a single Python file."""
        file_path = os.path.abspath(file_path)
        
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        
        tree = self.parser.parse(bytes(source, "utf-8"))
        
        symbols = []
        call_sites = []
        imports = []
        
        # Extract all definitions and calls
        self._extract_from_node(
            tree.root_node, 
            file_path, 
            source,
            symbols, 
            call_sites, 
            imports,
            current_class=None,
            current_function=None
        )
        
        return ParseResult(
            file_path=file_path,
            symbols=symbols,
            call_sites=call_sites,
            imports=imports
        )
    
    def parse_directory(self, dir_path: str, exclude_patterns: Optional[List[str]] = None) -> List[ParseResult]:
        """Parse all Python files in a directory recursively."""
        exclude_patterns = exclude_patterns or [
            "__pycache__", ".git", ".venv", "venv", "node_modules", 
            ".eggs", "*.egg-info", "build", "dist"
        ]
        
        results = []
        dir_path = Path(dir_path)
        
        for py_file in dir_path.rglob("*.py"):
            # Skip excluded patterns - check path parts, not substrings
            skip = False
            path_parts = py_file.parts
            for pattern in exclude_patterns:
                # Check if any path component matches the pattern
                if pattern in path_parts:
                    skip = True
                    break
                # Also check for glob-style patterns like *.egg-info
                if "*" in pattern:
                    import fnmatch
                    for part in path_parts:
                        if fnmatch.fnmatch(part, pattern):
                            skip = True
                            break
            
            if skip:
                continue
            
            try:
                result = self.parse_file(str(py_file))
                results.append(result)
            except Exception as e:
                print(f"Warning: Failed to parse {py_file}: {e}")
        
        return results
    
    def _extract_from_node(
        self,
        node: "Node",
        file_path: str,
        source: str,
        symbols: List[Symbol],
        call_sites: List[CallSite],
        imports: List[str],
        current_class: Optional[str] = None,
        current_function: Optional[str] = None
    ) -> None:
        """Recursively extract symbols and calls from AST node."""
        
        # Function definition
        if node.type == "function_definition":
            symbol = self._extract_function(node, file_path, source, current_class)
            if symbol:
                symbols.append(symbol)
                # Recurse into function body with updated context
                for child in node.children:
                    if child.type == "block":
                        self._extract_from_node(
                            child, file_path, source, symbols, call_sites, imports,
                            current_class=current_class,
                            current_function=symbol.id
                        )
                return  # Don't double-process children
        
        # Class definition
        elif node.type == "class_definition":
            symbol = self._extract_class(node, file_path, source)
            if symbol:
                symbols.append(symbol)
                # Recurse into class body
                for child in node.children:
                    if child.type == "block":
                        self._extract_from_node(
                            child, file_path, source, symbols, call_sites, imports,
                            current_class=symbol.id,
                            current_function=None
                        )
                return
        
        # Function call
        elif node.type == "call":
            call_site = self._extract_call(node, file_path, source, current_function)
            if call_site:
                call_sites.append(call_site)
        
        # Import statements
        elif node.type in ("import_statement", "import_from_statement"):
            imported = self._extract_import(node, source)
            imports.extend(imported)
        
        # Recurse into children
        for child in node.children:
            self._extract_from_node(
                child, file_path, source, symbols, call_sites, imports,
                current_class=current_class,
                current_function=current_function
            )
    
    def _extract_function(
        self, 
        node: "Node", 
        file_path: str, 
        source: str,
        current_class: Optional[str]
    ) -> Optional[Symbol]:
        """Extract a function/method definition."""
        
        # Get function name
        name_node = None
        params_node = None
        return_type = None
        body_node = None
        
        for child in node.children:
            if child.type == "identifier":
                name_node = child
            elif child.type == "parameters":
                params_node = child
            elif child.type == "type":
                return_type = self._get_node_text(child, source)
            elif child.type == "block":
                body_node = child
        
        if not name_node:
            return None
        
        name = self._get_node_text(name_node, source)
        
        # Build symbol ID
        if current_class:
            # It's a method
            class_name = current_class.split(":")[-1]  # Get class name from ID
            symbol_id = f"{file_path}:{class_name}.{name}"
            kind = SymbolKind.METHOD
        else:
            symbol_id = f"{file_path}:{name}"
            kind = SymbolKind.FUNCTION
        
        # Build signature
        params_text = self._get_node_text(params_node, source) if params_node else "()"
        ret_text = f" -> {return_type}" if return_type else ""
        signature = f"def {name}{params_text}{ret_text}"
        
        # Extract docstring
        docstring = None
        if body_node and body_node.children:
            first_stmt = body_node.children[0]
            if first_stmt.type == "expression_statement":
                expr = first_stmt.children[0] if first_stmt.children else None
                if expr and expr.type == "string":
                    docstring = self._get_node_text(expr, source).strip('"""\'\'\'')
        
        return Symbol(
            id=symbol_id,
            name=name,
            kind=kind,
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=signature,
            docstring=docstring,
            parent_id=current_class
        )
    
    def _extract_class(self, node: "Node", file_path: str, source: str) -> Optional[Symbol]:
        """Extract a class definition."""
        
        name_node = None
        bases = []
        body_node = None
        
        for child in node.children:
            if child.type == "identifier":
                name_node = child
            elif child.type == "argument_list":
                # Base classes
                for arg in child.children:
                    if arg.type == "identifier":
                        bases.append(self._get_node_text(arg, source))
            elif child.type == "block":
                body_node = child
        
        if not name_node:
            return None
        
        name = self._get_node_text(name_node, source)
        symbol_id = f"{file_path}:{name}"
        
        # Build signature
        bases_text = f"({', '.join(bases)})" if bases else ""
        signature = f"class {name}{bases_text}"
        
        # Extract docstring
        docstring = None
        if body_node and body_node.children:
            first_stmt = body_node.children[0]
            if first_stmt.type == "expression_statement":
                expr = first_stmt.children[0] if first_stmt.children else None
                if expr and expr.type == "string":
                    docstring = self._get_node_text(expr, source).strip('"""\'\'\'')
        
        return Symbol(
            id=symbol_id,
            name=name,
            kind=SymbolKind.CLASS,
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=signature,
            docstring=docstring,
            parent_id=None
        )
    
    def _extract_call(
        self, 
        node: "Node", 
        file_path: str, 
        source: str,
        current_function: Optional[str]
    ) -> Optional[CallSite]:
        """Extract a function/method call."""
        
        if not current_function:
            # Calls at module level - use file as caller
            current_function = f"{file_path}:__module__"
        
        # Get the function being called
        func_node = node.children[0] if node.children else None
        if not func_node:
            return None
        
        # Handle different call patterns
        if func_node.type == "identifier":
            # Simple call: foo()
            callee_name = self._get_node_text(func_node, source)
        elif func_node.type == "attribute":
            # Method call: obj.method() or module.func()
            # Get the full attribute path
            callee_name = self._get_node_text(func_node, source)
        else:
            # Complex expression (e.g., func()(), getattr(), etc.)
            return None
        
        return CallSite(
            caller_id=current_function,
            callee_name=callee_name,
            line=node.start_point[0] + 1,
            column=node.start_point[1],
            resolved_target_id=None,  # To be resolved later
            call_type="call"
        )
    
    def _extract_import(self, node: "Node", source: str) -> List[str]:
        """Extract imported module names."""
        imports = []
        
        if node.type == "import_statement":
            # import foo, bar
            for child in node.children:
                if child.type == "dotted_name":
                    imports.append(self._get_node_text(child, source))
                elif child.type == "aliased_import":
                    for subchild in child.children:
                        if subchild.type == "dotted_name":
                            imports.append(self._get_node_text(subchild, source))
                            break
        
        elif node.type == "import_from_statement":
            # from foo import bar
            module_name = None
            for child in node.children:
                if child.type == "dotted_name":
                    module_name = self._get_node_text(child, source)
                    break
                elif child.type == "relative_import":
                    module_name = self._get_node_text(child, source)
                    break
            if module_name:
                imports.append(module_name)
        
        return imports
    
    def _get_node_text(self, node: "Node", source: str) -> str:
        """Get the source text for a node."""
        return source[node.start_byte:node.end_byte]
