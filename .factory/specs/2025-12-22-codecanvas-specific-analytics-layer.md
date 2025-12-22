## Overview

Add a dedicated analytics layer for CodeCanvas that extracts insights from `state.json` and visual artifacts, answering: **"Did seeing blast radius visually change agent behavior?"**

---

## New Files

### `terminalbench/analytics/codecanvas_metrics.py`

**Data loading:**
```python
def load_codecanvas_state(trial_dir: Path) -> Optional[CanvasState]:
    """Load state.json from agent/sessions/codecanvas/"""
    state_path = trial_dir / "agent" / "sessions" / "codecanvas" / "state.json"
    if not state_path.exists():
        return None  # Not a codecanvas run or no state captured
    return CanvasState.from_json(state_path.read_text())
```

**Deterministic metrics (Layer 1):**

| Metric | Formula | Story |
|--------|---------|-------|
| `blast_radius_edit_rate` | `edits_in_analyzed_symbols / total_edits` | Did agent edit where they looked? |
| `anticipated_failure_rate` | `failed_tests_in_blast_radius / total_failed_tests` | Were failures expected? |
| `deliberation_depth` | `claims_before_first_edit + decisions_before_first_edit` | Did Evidence Board encourage planning? |
| `reasoning_density` | `len(claims) / len(evidence)` | How much reasoning per visual? |
| `systematic_progress` | `(addressed + skipped) / affected` | Did agent track their blast radius coverage? |
| `hook_vs_manual_ratio` | Hook-triggered impacts vs manual `canvas(action="impact")` calls | Was agent proactive or reactive? |

**Composite score:**
```python
informed_editing_score = (
    0.4 * blast_radius_edit_rate +
    0.3 * anticipated_failure_rate +
    0.3 * min(1.0, deliberation_depth / 3)  # Cap at 3 claims/decisions
)
```

---

### `terminalbench/analytics/codecanvas_vision.py`

**Vision-powered analysis (Layer 2, GPT-5.2):**

1. **Visual-Edit Alignment**
   - Input: `impact_*.png` + list of files edited after that analysis
   - Prompt: Assess whether edits align with visualized blast radius
   - Output: `alignment_score` (0-1), `observations` list

2. **Evidence Board Quality** (if `board.png` exists at end of run)
   - Input: Final board.png
   - Prompt: Evaluate quality of reasoning trail (systematic? hypothesis-driven?)
   - Output: `board_quality_score`, `reasoning_style`

---

## Integration Points

### `deterministic.py`
Add to `DeterministicMetrics` dataclass:
```python
# CodeCanvas-specific (None if not codecanvas run)
codecanvas_evidence_count: Optional[int] = None
codecanvas_claims_count: Optional[int] = None
codecanvas_decisions_count: Optional[int] = None
codecanvas_blast_radius_edit_rate: Optional[float] = None
codecanvas_anticipated_failure_rate: Optional[float] = None
codecanvas_deliberation_depth: Optional[int] = None
codecanvas_informed_editing_score: Optional[float] = None
```

### `llm_analysis.py`
Add `CodeCanvasVisualAnalysis` dataclass and `analyze_codecanvas_visuals()` method to `LLMAnalyzer`.

### `prompts.py`
Add `VISUAL_EDIT_ALIGNMENT_PROMPT` and `EVIDENCE_BOARD_QUALITY_PROMPT`.

### `reports.py`
Add `codecanvas_analysis.json` output with per-run visual analysis results.

---

## Output Files

| File | Contents |
|------|----------|
| `codecanvas_analysis.json` | Per-run: evidence/claim/decision counts, all codecanvas metrics |
| `codecanvas_comparison.md` | Side-by-side: codecanvas vs text vs codegraph on informed_editing_score |
| `codecanvas_visuals.json` | GPT-5.2 visual analysis results (when images present) |

---

## CLI Integration

```bash
# Include codecanvas-specific analysis automatically when state.json present
python -m terminalbench.analytics results/runs/ -o results/analytics/

# Explicit codecanvas-only analysis
python -m terminalbench.analytics results/runs/ --profiles codecanvas --codecanvas-deep
```

`--codecanvas-deep` flag triggers vision analysis on all available PNGs.

---

## Key Design Decisions

1. **Graceful presence check** - If `state.json` missing, codecanvas metrics are `None`, run still analyzed with base metrics
2. **Symbol-to-file mapping** - Use `symbol.file` from state.json to map blast radius symbols to edited files from trajectory
3. **Test-to-file mapping** - Parse CTRF test results to get file paths, cross-reference with blast radius
4. **No backwards compat** - Fresh data only, no legacy handling