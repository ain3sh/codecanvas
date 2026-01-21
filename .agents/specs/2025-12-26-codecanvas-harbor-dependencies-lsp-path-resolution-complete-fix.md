## Summary

After thorough analysis of the analytics data, source code, and Harbor setup, I've identified the root causes of hooks + MCP under-triggering and the dependency issues.

---

## Fixes Already Applied (This Session)

| File | Change | Status |
|------|--------|--------|
| `codecanvas/hooks/session_init.py` | Removed `detect_repo()` and `count_code_files() < 5` early exits; added `load_state_summary()` | ✅ Done |
| `codecanvas/hooks/post_read.py` | Changed `"FUNCTION", "CLASS", "METHOD"` → `"func", "class"` | ✅ Done |
| `terminalbench/analytics/extensions/codecanvas.py` | Fixed `"files"` → `"parsed_files"`, added evidence metrics lookup | ✅ Done |
| `terminalbench/harbor/install-claude-code-mcp.sh.j2` | Added `npm install -g basedpyright` | ✅ Done (but see below) |

---

## Remaining Issue: LSP Path Resolution

### The Problem

In `codecanvas/parser/lsp.py`:
```python
def is_language_server_installed(lang: str) -> bool:
    # ...
    return shutil.which(cmd[0]) is not None  # Uses system PATH
```

In Harbor:
1. Python packages install to `/opt/venv/bin/`
2. `/opt/venv/bin/` is NOT in system PATH
3. `shutil.which("basedpyright-langserver")` → `None`
4. Every file falls back to tree-sitter → **no call edges**

### Solution Options

**Option A: Add `/opt/venv/bin` to PATH in install script**
```bash
# In install-claude-code-mcp.sh.j2
echo 'export PATH="/opt/venv/bin:$PATH"' >> /etc/profile.d/venv-path.sh
source /etc/profile.d/venv-path.sh
```
Pros: Simple, fixes all PATH issues globally
Cons: May not persist in all subprocess contexts

**Option B: Keep npm install (current approach)**
```bash
npm install -g basedpyright
```
Pros: npm global installs go to PATH locations automatically
Cons: Redundant with Python package; version sync issues

**Option C: Modify LSP code to use venv path**
```python
# In codecanvas/parser/lsp.py
VENV_BIN = Path("/opt/venv/bin")

def is_language_server_installed(lang: str) -> bool:
    cfg = LANGUAGE_SERVERS.get(lang)
    if not cfg:
        return False
    cmd = cfg.get("cmd")
    if not cmd:
        return False
    # Check system PATH first
    if shutil.which(cmd[0]) is not None:
        return True
    # Check venv bin (Harbor container)
    return (VENV_BIN / cmd[0]).exists()

def get_lsp_command(lang: str) -> List[str]:
    """Get LSP command, using full venv path if needed."""
    cfg = LANGUAGE_SERVERS.get(lang)
    cmd = list(cfg["cmd"])
    if shutil.which(cmd[0]) is None:
        venv_path = VENV_BIN / cmd[0]
        if venv_path.exists():
            cmd[0] = str(venv_path)
    return cmd
```
Pros: No external dependencies; works in any environment
Cons: Requires code changes in multiple places

**Recommendation: Option A + remove Option B**

Option A is cleanest - add PATH to install script, remove redundant npm install. This ensures:
- `shutil.which()` finds the binary
- Subprocess execution works
- No duplicate package installations

---

## pyproject.toml Dependency Cleanup

### Current Issues
```toml
dependencies = [
    "basedpyright>=1.36.1",   # codecanvas-specific
    "CairoSVG>=2.7.1",        # codecanvas-specific
    "tree-sitter>=0.24.0",    # shared
    # ...
]

[project.optional-dependencies]
locagent = [
    "tree-sitter>=0.24.0",    # DUPLICATE
    "pydantic>=2.0.0",        # also in [mcp]
    "PyYAML>=6.0.0",          # same as pyyaml in core
    # ...
]
```

### Proposed Structure
```toml
dependencies = [
    # Truly shared only
    "pyyaml>=6.0",
]

[project.optional-dependencies]
codecanvas = [
    "CairoSVG>=2.7.1",
    "lsprotocol>=2024.0.0",
    "basedpyright>=1.36.1",
    "tree-sitter>=0.24.0",
    "tree-sitter-language-pack>=0.13.0",
]
mcp = [
    "mcp>=1.0.0",
    "pydantic>=2.0.0",
]
locagent = [
    "networkx>=3.0.0",
    "bm25s>=0.2.0",
    "libcst>=1.0.0",
    # ... locagent-specific deps
]
```

Then install command becomes: `".[codecanvas,mcp,locagent]"` or just `".[codecanvas,mcp]"` for codecanvas-only.

---

## Implementation Plan

### Phase 1: Fix LSP Path (Critical)
1. Modify `install-claude-code-mcp.sh.j2`:
   - Add `/opt/venv/bin` to PATH
   - Remove `npm install -g basedpyright` (redundant)
2. Update `MCP_VENV_PYTHON` constant in `profiles.py` to `/opt/venv/bin/python`

### Phase 2: Verify Hook Adaptation (Already Done)
- `adapt_hooks_for_harbor()` replaces `uv run python` with `/opt/venv/bin/python` ✅
- `adapt_mcp_config_for_harbor()` does the same for MCP configs ✅

### Phase 3: pyproject.toml Cleanup
- Separate codecanvas and locagent dependencies
- Remove duplicates
- Update install script to use new extras

---

## Files to Modify

| File | Change |
|------|--------|
| `terminalbench/harbor/install-claude-code-mcp.sh.j2` | Add PATH export, remove npm basedpyright |
| `terminalbench/core/profiles.py` | Update `MCP_VENV_PYTHON` to `/opt/venv/bin/python` |
| `pyproject.toml` | Restructure dependency extras |