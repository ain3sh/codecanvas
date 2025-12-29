## Problem
Call graph shows 0 edges in Harbor because:
1. Foreground call graph has **0.35s timeout** - too short for cold LSP
2. Background thread starts but `_action_impact()` **doesn't wait** for it
3. Impact is called before background completes, sees 0 edges

## Solution: Hybrid Approach

### Changes to `codecanvas/server.py`:

1. **Add helper function** (after `_start_call_graph_background`, ~line 141):
```python
def _wait_for_call_graph(timeout_s: float = 10.0) -> None:
    """Wait for background call graph thread to complete."""
    global _call_graph_thread
    if _call_graph_thread and _call_graph_thread.is_alive():
        _call_graph_thread.join(timeout=timeout_s)
```

2. **Increase foreground timeout** from 0.35s to 2.0s:
   - Line 257: `time_budget_s=0.35` → `time_budget_s=2.0`
   - Line 342: `time_budget_s=0.2` → `time_budget_s=2.0`

3. **Wait in `_action_impact`** (line 346, after asserts):
```python
_wait_for_call_graph(timeout_s=10.0)
```

### Cleanup (after verifying fix):
- Remove debug `CALLGRAPH_RESULT` print from server.py line 77
- Remove debug `CALLGRAPH_DEBUG` block from call_graph.py lines 279-282

## Testing
1. Local call graph test to verify no regression
2. Harbor run of `custom-memory-heap-crash`
3. Verify `state.json` has `edge_count > 0`
4. Verify PNGs show call connections