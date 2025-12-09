"""Tests for the CodeCanvas interface."""

import os
import tempfile
import pytest
from codecanvas.scratchpad.canvas import CodeCanvas


@pytest.fixture
def sample_project(tmp_path):
    """Create a sample project for testing."""
    
    # auth.py
    auth = tmp_path / "auth.py"
    auth.write_text('''
def validate_token(token: str) -> bool:
    """Validate an authentication token."""
    return len(token) > 0

def get_user_from_token(token: str):
    """Get user from token."""
    if validate_token(token):
        return {"user": "test"}
    return None
''')
    
    # api.py
    api = tmp_path / "api.py"
    api.write_text('''
from auth import validate_token, get_user_from_token

def protected_endpoint(token: str):
    """A protected API endpoint."""
    if not validate_token(token):
        return {"error": "unauthorized"}
    user = get_user_from_token(token)
    return {"data": "secret", "user": user}

def public_endpoint():
    """A public endpoint."""
    return {"data": "public"}
''')
    
    # test_auth.py
    tests = tmp_path / "test_auth.py"
    tests.write_text('''
from auth import validate_token, get_user_from_token

def test_validate_token():
    """Test token validation."""
    assert validate_token("valid") == True
    assert validate_token("") == False

def test_get_user():
    """Test getting user from token."""
    user = get_user_from_token("valid")
    assert user is not None
''')
    
    return tmp_path


def test_canvas_creation(sample_project):
    """Test creating a canvas from a directory."""
    canvas = CodeCanvas.from_directory(str(sample_project))
    
    stats = canvas.stats()
    assert stats["total_symbols"] > 0
    assert stats["functions"] > 0


def test_impact_of(sample_project):
    """Test impact analysis."""
    canvas = CodeCanvas.from_directory(str(sample_project))
    
    impact = canvas.impact_of("validate_token")
    
    assert impact is not None
    assert impact.target.name == "validate_token"
    
    # Should have callers
    caller_names = {c.name for c in impact.direct_callers}
    assert len(caller_names) > 0


def test_callers_of(sample_project):
    """Test getting callers."""
    canvas = CodeCanvas.from_directory(str(sample_project))
    
    callers = canvas.callers_of("validate_token")
    
    assert len(callers) > 0
    caller_names = {c.name for c in callers}
    # get_user_from_token and protected_endpoint both call validate_token
    assert "get_user_from_token" in caller_names or "protected_endpoint" in caller_names


def test_tests_for(sample_project):
    """Test finding tests."""
    canvas = CodeCanvas.from_directory(str(sample_project))
    
    tests = canvas.tests_for("validate_token")
    
    # Should find test_validate_token
    test_names = {t.name for t in tests}
    assert "test_validate_token" in test_names


def test_mark_addressed(sample_project):
    """Test marking items as addressed."""
    canvas = CodeCanvas.from_directory(str(sample_project))
    
    impact = canvas.impact_of("validate_token")
    assert impact is not None
    
    # Initially nothing addressed
    initial_remaining = len(impact.remaining())
    
    # Mark first caller as addressed
    if impact.direct_callers:
        canvas.mark_addressed(impact.direct_callers[0].id)
        
        # Remaining should decrease
        new_remaining = len(impact.remaining())
        assert new_remaining < initial_remaining or initial_remaining == 0


def test_render_markdown(sample_project):
    """Test markdown rendering."""
    canvas = CodeCanvas.from_directory(str(sample_project))
    
    impact = canvas.impact_of("validate_token")
    assert impact is not None
    
    markdown = canvas.render(format="markdown")
    
    assert "# Impact Analysis" in markdown
    assert "validate_token" in markdown
    assert "Direct Callers" in markdown


def test_render_json(sample_project):
    """Test JSON rendering."""
    canvas = CodeCanvas.from_directory(str(sample_project))
    
    impact = canvas.impact_of("validate_token")
    assert impact is not None
    
    import json
    json_output = canvas.render(format="json")
    
    # Should be valid JSON
    data = json.loads(json_output)
    assert "target" in data
    assert "direct_callers" in data


def test_find(sample_project):
    """Test symbol search."""
    canvas = CodeCanvas.from_directory(str(sample_project))
    
    results = canvas.find("token")
    
    assert len(results) > 0
    # Should find validate_token and get_user_from_token
    names = {r.name for r in results}
    assert "validate_token" in names
