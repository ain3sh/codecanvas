"""Tests for the Tree-sitter parser."""

import os
import tempfile
import pytest
from codecanvas.core.parser import PythonParser
from codecanvas.core.models import SymbolKind


@pytest.fixture
def parser():
    return PythonParser()


@pytest.fixture
def sample_code():
    return '''
"""Sample module docstring."""

import os
from pathlib import Path


class User:
    """A user class."""
    
    def __init__(self, name: str):
        self.name = name
    
    def greet(self) -> str:
        """Return greeting."""
        return f"Hello, {self.name}"


def create_user(name: str) -> User:
    """Create a new user."""
    user = User(name)
    user.greet()
    return user


def main():
    """Entry point."""
    user = create_user("Alice")
    print(user.greet())
'''


def test_parse_file(parser, sample_code):
    """Test parsing a Python file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(sample_code)
        f.flush()
        
        try:
            result = parser.parse_file(f.name)
            
            # Check we found symbols
            assert len(result.symbols) > 0
            
            # Check we found the class
            class_symbols = [s for s in result.symbols if s.kind == SymbolKind.CLASS]
            assert len(class_symbols) == 1
            assert class_symbols[0].name == "User"
            
            # Check we found functions
            func_symbols = [s for s in result.symbols if s.kind == SymbolKind.FUNCTION]
            func_names = {s.name for s in func_symbols}
            assert "create_user" in func_names
            assert "main" in func_names
            
            # Check we found methods
            method_symbols = [s for s in result.symbols if s.kind == SymbolKind.METHOD]
            method_names = {s.name for s in method_symbols}
            assert "__init__" in method_names
            assert "greet" in method_names
            
            # Check we found imports
            assert "os" in result.imports
            assert "pathlib" in result.imports
            
            # Check we found call sites
            assert len(result.call_sites) > 0
            call_names = {cs.callee_name for cs in result.call_sites}
            assert "User" in call_names  # User() constructor call
            
        finally:
            os.unlink(f.name)


def test_extract_docstrings(parser, sample_code):
    """Test docstring extraction."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(sample_code)
        f.flush()
        
        try:
            result = parser.parse_file(f.name)
            
            # Find create_user function
            create_user = next(
                (s for s in result.symbols if s.name == "create_user"), 
                None
            )
            assert create_user is not None
            assert create_user.docstring is not None
            assert "Create a new user" in create_user.docstring
            
        finally:
            os.unlink(f.name)


def test_extract_signatures(parser, sample_code):
    """Test signature extraction."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(sample_code)
        f.flush()
        
        try:
            result = parser.parse_file(f.name)
            
            # Find create_user function
            create_user = next(
                (s for s in result.symbols if s.name == "create_user"), 
                None
            )
            assert create_user is not None
            assert "def create_user" in create_user.signature
            assert "name: str" in create_user.signature
            assert "-> User" in create_user.signature
            
        finally:
            os.unlink(f.name)
