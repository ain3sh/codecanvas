## CodeCanvas Cleanup Spec

### Files: Keep all 9 (structure is sound)

### Dead Code Removal (~50 lines):

**1. models.py** - Remove unused DepViz layout fields from `GraphNode`:
```python
# DELETE these fields:
x: Optional[float] = None
y: Optional[float] = None
docked: bool = True
collapsed: bool = False
```
Also remove their serialization in `to_dict()`.

**2. impact.py** - Remove unused scratchpad state (now handled by state.py):
```python
# DELETE from ImpactAnalysis:
addressed: Set[str] = field(default_factory=set)
notes: Dict[str, str] = field(default_factory=dict)

def mark_addressed(self, node_id: str) -> None: ...
def remaining(self) -> List[str]: ...
@property
def is_complete(self) -> bool: ...

# DELETE from ImpactAnalyzer:
def find_high_impact(self, min_callers: int = 3) -> List[GraphNode]: ...
```

**3. canvas.py** - Remove CLI entry point:
```python
# DELETE main() function and if __name__ == "__main__" block
```

**4. __init__.py** - Simplify to essential exports:
```python
from .canvas import canvas
from .state import load_state, save_state

__all__ = ["canvas", "load_state", "save_state"]
```

### Result
- 8 source files (excluding test.py)
- ~50 lines removed
- Clean, focused API: just `canvas()` + state helpers