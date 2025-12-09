"""
Checklist renderer: formats ImpactAnalysis as LLM-optimized markdown.

The output format is designed to be:
1. Easy for LLMs to parse and update
2. Actionable (checkboxes for tracking)
3. Informative (includes context like line numbers, signatures)
"""

import os
from typing import Optional
from ..core.models import ImpactAnalysis, Symbol

# Import CanvasState type for hints
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .canvas import CanvasState


class ChecklistRenderer:
    """Renders ImpactAnalysis as markdown checklists."""
    
    def render_markdown(self, impact: ImpactAnalysis, state: "CanvasState") -> str:
        """
        Render full markdown checklist.
        
        Format:
        # Impact Analysis: Modifying `file:symbol`
        
        ## Direct Callers (N) - MUST UPDATE
        - [ ] `file:func` (line X) - signature
        
        ## Tests (N) - MUST RUN
        - [ ] `test_file::test_func`
        
        ## Transitive Impact (N)
        - chain visualization
        
        ## Status: X/Y addressed
        """
        lines = []
        
        # Header
        target = impact.target
        lines.append(f"# Impact Analysis: Modifying `{target.short_id}`")
        lines.append("")
        lines.append(f"**File:** `{os.path.basename(target.file_path)}`")
        lines.append(f"**Line:** {target.line_start}")
        lines.append(f"**Signature:** `{target.signature}`")
        if target.docstring:
            lines.append(f"**Docstring:** {target.docstring[:100]}...")
        lines.append("")
        
        # Direct Callers
        lines.append(f"## Direct Callers ({len(impact.direct_callers)}) - MUST UPDATE")
        lines.append("")
        
        if impact.direct_callers:
            for caller in impact.direct_callers:
                checkbox = "x" if caller.id in state.addressed else " "
                note = state.notes.get(caller.id, "")
                note_str = f" - {note}" if note else ""
                lines.append(
                    f"- [{checkbox}] `{caller.short_id}` (line {caller.line_start}){note_str}"
                )
                lines.append(f"      Signature: `{caller.signature}`")
        else:
            lines.append("*No direct callers found*")
        
        lines.append("")
        
        # Tests
        lines.append(f"## Tests ({len(impact.tests)}) - MUST RUN")
        lines.append("")
        
        if impact.tests:
            for test in impact.tests:
                checkbox = "x" if test.id in state.addressed else " "
                # Format as pytest-style: file::test_name
                test_file = os.path.basename(test.file_path)
                lines.append(f"- [{checkbox}] `{test_file}::{test.name}`")
        else:
            lines.append("*No tests found - consider adding test coverage*")
        
        lines.append("")
        
        # Transitive Impact
        if impact.transitive_callers:
            lines.append(f"## Transitive Impact ({len(impact.transitive_callers)}) - REVIEW")
            lines.append("")
            
            # Group by file for readability
            by_file = {}
            for caller in impact.transitive_callers:
                file_name = os.path.basename(caller.file_path)
                if file_name not in by_file:
                    by_file[file_name] = []
                by_file[file_name].append(caller)
            
            for file_name, callers in by_file.items():
                lines.append(f"**{file_name}:**")
                for caller in callers[:5]:  # Limit per file
                    lines.append(f"  - `{caller.name}` (line {caller.line_start})")
                if len(callers) > 5:
                    lines.append(f"  - ... and {len(callers) - 5} more")
            
            lines.append("")
        
        # Summary
        remaining = impact.remaining()
        total = len(impact.direct_callers) + len(impact.tests)
        addressed = total - len(remaining)
        
        lines.append("---")
        lines.append(f"## Status: {addressed}/{total} addressed")
        lines.append("")
        
        if remaining:
            lines.append(f"**Remaining ({len(remaining)}):**")
            for sym in remaining[:10]:
                lines.append(f"- `{sym.short_id}`")
            if len(remaining) > 10:
                lines.append(f"- ... and {len(remaining) - 10} more")
        else:
            lines.append("**All dependencies addressed!**")
        
        return "\n".join(lines)
    
    def render_brief(self, impact: ImpactAnalysis, state: "CanvasState") -> str:
        """
        Render brief summary (for status checks).
        
        Format:
        Impact of `symbol`: 3 callers, 2 tests | 2/5 addressed | INCOMPLETE
        """
        remaining = impact.remaining()
        total = len(impact.direct_callers) + len(impact.tests)
        addressed = total - len(remaining)
        
        status = "COMPLETE" if impact.is_complete else "INCOMPLETE"
        
        return (
            f"Impact of `{impact.target.short_id}`: "
            f"{len(impact.direct_callers)} callers, {len(impact.tests)} tests | "
            f"{addressed}/{total} addressed | {status}"
        )
    
    def render_symbol_detail(self, symbol: Symbol, state: "CanvasState") -> str:
        """Render detailed info about a single symbol."""
        lines = []
        
        lines.append(f"## `{symbol.short_id}`")
        lines.append("")
        lines.append(f"- **Kind:** {symbol.kind.value}")
        lines.append(f"- **File:** `{symbol.file_path}`")
        lines.append(f"- **Lines:** {symbol.line_start}-{symbol.line_end}")
        lines.append(f"- **Signature:** `{symbol.signature}`")
        
        if symbol.docstring:
            lines.append(f"- **Docstring:** {symbol.docstring}")
        
        if symbol.id in state.addressed:
            lines.append("- **Status:** ADDRESSED")
        
        if symbol.id in state.notes:
            lines.append(f"- **Note:** {state.notes[symbol.id]}")
        
        if symbol.id in state.flags:
            lines.append(f"- **Flag:** {state.flags[symbol.id]}")
        
        return "\n".join(lines)
