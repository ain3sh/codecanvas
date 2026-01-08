## Root Cause Analysis

**Why call graph edges = 0 in Harbor:**

1. `LspSession.definitions()` (line 743) uses `asyncio.gather()` to parallelize calls
2. BUT `MultilspyBackend.definition()` (line 336) calls `self._lsp.request_definition()` - a **SYNC call**
3. Sync calls BLOCK the event loop, so `gather()` runs them **sequentially**
4. With 50-200 call sites × 100-500ms each = 5-100 seconds per file
5. 10s budget times out on first file

**Evidence:** Debug output showed `files=1, processed=0, lsp_fail={'TimeoutError': 1}` - first file timed out before processing any call sites.

---

## Part 1: Changes to REVERT

| Commit | Change | Action | Reason |
|--------|--------|--------|--------|
| 92dd318 | `time_budget_s=0.35` → `2.0` (line 255) | **REVERT to 0.35** | Foreground should be quick |
| 92dd318 | `time_budget_s=0.2` → `2.0` (line 340) | **REVERT to 0.2** | Same |
| 93f68b6 + 488724c | Added `_log()` function in `_worker()` | **REMOVE entirely** | Debug cruft |
| Uncommitted | 30s timeout in call_graph.py | **REVERT** | Broken fix |

**Changes to KEEP from 92dd318:**
- `_wait_for_call_graph()` helper - useful for impact to wait for background
- `_wait_for_call_graph()` call in `_action_impact()` - ensures impact sees completed graph

---

## Part 2: The Real Fix

### In `codecanvas/parser/lsp.py`, `MultilspyBackend.definition()`:

**Before (line 328-339):**
```python
async def definition(self, uri_or_path: str, *, line: int, char: int) -> List[Dict[str, Any]]:
    await self._ensure_started()
    path = uri_to_path(uri_or_path) if uri_or_path.startswith("file://") else uri_or_path
    rel_path = os.path.relpath(path, self.workspace_root)
    try:
        result = self._lsp.request_definition(rel_path, line, char)  # BLOCKS!
        return _parse_definition_locations(result)
    except Exception:
        return []
```

**After:**
```python
async def definition(self, uri_or_path: str, *, line: int, char: int) -> List[Dict[str, Any]]:
    await self._ensure_started()
    path = uri_to_path(uri_or_path) if uri_or_path.startswith("file://") else uri_or_path
    rel_path = os.path.relpath(path, self.workspace_root)
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, self._lsp.request_definition, rel_path, line, char
        )
        return _parse_definition_locations(result)
    except Exception:
        return []
```

This runs `request_definition()` in the default thread pool, allowing true parallelism.

### In `codecanvas/server.py`:

Increase background budget: `time_budget_s=10.0` → `time_budget_s=30.0` (line 258)

With parallel definition calls, 30s should be plenty for even complex C++ projects.

---

## Summary of Final State

| File | Changes |
|------|---------|
| `lsp.py` | Parallelize `MultilspyBackend.definition()` with thread pool |
| `server.py` | Revert foreground timeouts to 0.35s/0.2s, increase background to 30s, remove `_log()` cruft, keep `_wait_for_call_graph` |
| `call_graph.py` | Revert to using `remaining_s` timeout (undo my broken change) |

---

## Testing

1. Local: Run call graph test with C++ files, verify edges found
2. Harbor: Run `custom-memory-heap-crash`, verify `edge_count > 0` in state.json
3. Verify impact PNGs show call connections