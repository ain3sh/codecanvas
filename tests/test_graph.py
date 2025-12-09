"""Tests for dependency graph construction."""

import os
import tempfile
import pytest
from codecanvas.core.graph import DependencyGraph
from codecanvas.core.models import SymbolKind


@pytest.fixture
def sample_project(tmp_path):
    """Create a sample project structure."""
    
    # models.py
    models = tmp_path / "models.py"
    models.write_text('''
class User:
    def __init__(self, name: str):
        self.name = name
    
    def save(self):
        """Save the user."""
        pass
''')
    
    # service.py
    service = tmp_path / "service.py"
    service.write_text('''
from models import User

def create_user(name: str) -> User:
    """Create and save a user."""
    user = User(name)
    user.save()
    return user

def update_user(user: User, name: str):
    """Update user name."""
    user.name = name
    user.save()
''')
    
    # api.py
    api = tmp_path / "api.py"
    api.write_text('''
from service import create_user, update_user

def handle_create(request):
    """API handler for create."""
    name = request.get("name")
    return create_user(name)

def handle_update(request, user):
    """API handler for update."""
    name = request.get("name")
    update_user(user, name)
''')
    
    # test_service.py
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_service = tests_dir / "test_service.py"
    test_service.write_text('''
from service import create_user, update_user
from models import User

def test_create_user():
    """Test user creation."""
    user = create_user("Alice")
    assert user.name == "Alice"

def test_update_user():
    """Test user update."""
    user = User("Alice")
    update_user(user, "Bob")
    assert user.name == "Bob"
''')
    
    return tmp_path


def test_build_graph(sample_project):
    """Test building a dependency graph."""
    builder = DependencyGraph()
    graph = builder.build_from_directory(str(sample_project))
    
    # Should have symbols
    assert len(graph.symbols) > 0
    
    # Should have User class
    user_symbols = [s for s in graph.symbols.values() if s.name == "User"]
    assert len(user_symbols) == 1
    
    # Should have create_user function
    create_symbols = [s for s in graph.symbols.values() if s.name == "create_user"]
    assert len(create_symbols) == 1


def test_reverse_dependencies(sample_project):
    """Test that reverse dependencies (called_by) are built correctly."""
    builder = DependencyGraph()
    graph = builder.build_from_directory(str(sample_project))
    
    # Find User.save method
    save_symbols = [s for s in graph.symbols.values() if s.name == "save"]
    assert len(save_symbols) == 1
    save_id = save_symbols[0].id
    
    # Check callers of save()
    callers = graph.get_direct_callers(save_id)
    caller_names = {c.name for c in callers}
    
    # Both create_user and update_user call save()
    assert "create_user" in caller_names or "update_user" in caller_names


def test_find_symbol(sample_project):
    """Test symbol search."""
    builder = DependencyGraph()
    builder.build_from_directory(str(sample_project))
    
    # Exact name search
    results = builder.find_symbol("create_user")
    assert len(results) == 1
    assert results[0].name == "create_user"
    
    # Partial search
    results = builder.find_symbol("user")
    assert len(results) > 0


def test_impact_summary(sample_project):
    """Test impact summary generation."""
    builder = DependencyGraph()
    builder.build_from_directory(str(sample_project))
    
    # Find create_user
    results = builder.find_symbol("create_user")
    assert len(results) == 1
    
    summary = builder.get_impact_summary(results[0].id)
    
    assert "target" in summary
    assert "direct_callers" in summary
    assert "direct_count" in summary
