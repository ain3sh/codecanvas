# Reduce dead space in view PNGs for small graphs

## 1) JSON ↔ PNG cross-check (no missing info)
- `graph_meta.04cb…json`: `modules=1, classes=1, funcs=5, import_edges=0` → `architecture.04cb….png` shows **1 CORE card** with `classes=1 funcs=5` and **no highways**; ENTRY/FOUNDATION empty (matches `import_edges=0`).
- `graph_meta.87c8…json`: `modules=2, classes=3, funcs=9, import_edges=0` → `architecture.87c8….png` shows **2 CORE cards** with matching per-file class/func counts; no highways.
- `call_edges.87c8…json`: 5 call edges → impact PNGs show correct subsets:
  - `impact_fn_dbbd…run_analysis.png`: 3 callees (state E2 metrics `node_count=4 edge_count=3`).
  - `impact_fn_3e34…run_analysis.png`: 2 callees (state E3 metrics `node_count=3 edge_count=2`).
- `state.json` evidence has E1 (architecture) + E2/E3 (impact) → `task.png` displays those 3 tiles; CLAIMS/DECISIONS are empty as reflected in state.

## 2) Problem observed in images
- **Architecture views** always reserve 3 full-height bands (ENTRY/CORE/FOUNDATION). With 1–2 modules, only CORE is populated → large unused vertical space.
- **Impact views** are always 1000×800 and center the target even when callers==0 → large unused left half and large unused vertical space.
- **Task board** always renders 3 equal columns; when claims/decisions are empty, 2/3 of the width is unused and thumbnails are smaller than necessary.

## 3) Options

## Option A: Adaptive canvas sizing (recommended)
Focus: compute a layout first, then choose canvas dimensions that tightly fit the rendered content (within sane min/max bounds). This directly eliminates dead space without “filling” it with junk.

### A1) `ArchitectureView` (`codecanvas/views/architecture.py`)
- **Collapse empty bands**: only render bands that actually have visible districts.
- **Adaptive height**: compute total canvas height from:
  - top margin + sum(band heights for rendered bands) + legend space + bottom margin
  - clamp to a safe range (e.g., `min≈520`, `max=900`).
- **Card sizing/centering** for tiny graphs:
  - cap max card width/height (avoid a single massive, mostly-empty card)
  - center the grid within its band when there are only 1–2 cards.
- **Title truncation improvement**:
  - for path-like district names, use `_short_path` style (keep basename and some prefix) instead of cutting off the extension.
- **More useful content when graph is tiny**:
  - for single-module districts and small graphs (e.g., total modules ≤ 6), show more `top_symbols` (e.g., up to 6) so the reclaimed space is informative.

### A2) `ImpactView` (`codecanvas/views/impact.py`)
- Replace fixed 1000×800 frame with **extent-driven sizing**:
  - compute positions for target + neighbor nodes
  - compute bounding box of all boxes/labels/edges + padding
  - render into a canvas sized to that box (with min dims to avoid being too small).
- **Side-aware centering**:
  - if callers==0, shift target left so the callee column is centered; if callees==0, shift right.
- **Label truncation**:
  - replace tail-only truncation (`…ulate_mean_temperature`) with middle-ellipsis (`calculate…temperature`) to preserve more semantic signal.

(Implementation choice inside this option: keep the existing arc layout but add translate/crop, or swap to a simple 2-column stacked layout. Arc+crop is less invasive; stacked layout is more compact/predictable.)

### A3) `TaskView` (`codecanvas/views/task.py`)
- **Responsive panels**:
  - if claims and decisions are both empty → render a single, full-width EVIDENCE panel.
  - if one side is empty → give evidence ~65–70% width; remaining panel gets the rest.
  - otherwise keep 3 columns.
- **Evidence tiling adapts to count**:
  - ≤3 evidence: use a 3-up row (or 2+1 layout) with larger thumbnails.
  - 4–6: keep 2-column grid but compute tile height from available space to minimize bottom blank.
- Slight caption font bump when evidence gets more space.

## Option B: Fixed canvas; scale/layout content to fill
Focus: keep image dimensions constant (architecture 1400×900, impact 1000×800, task 1400×900) but redistribute space internally.
- Architecture: shrink empty bands to header-only rows; allocate remaining height to populated bands.
- Impact: dynamically move `cx` based on which side is empty and widen angle ranges for small node counts.
- Task: keep 3 panels but make empty panels narrow “rails” instead of full columns.

Pros: avoids variable output dimensions.
Cons: more tuning knobs; harder to guarantee minimal dead space in every sparse case.

## 4) Acceptance criteria
- For graphs with 1–2 modules: architecture PNG shows only relevant band(s) and content occupies most of the frame.
- For impact with callers==0 or callees==0: target is shifted so there’s no half-empty canvas; vertical blank is substantially reduced.
- Task board with empty claims/decisions: evidence thumbnails are materially larger and empty columns are removed/collapsed.
- Existing tests/validators still pass.

## 5) Validation (after you approve and I implement)
- Run: `uv run ruff check .`, `uv run ty check`, `uv run pytest` (plus any existing formatting check if configured).
- Regenerate a small-graph run (same TB task you used here) and visually confirm the three outputs are improved:
  - `architecture.<digest>.png`
  - `impact_fn_*.png`
  - `task.png`
