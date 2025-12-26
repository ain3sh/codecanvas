## Implementation Plan: Multi-Batch Results Directory Support

### Current State
The results directory now supports multiple batch runs (0/, 1/, 2/, etc.), each containing:
- `runs/` - Harbor job outputs + index.json
- `analytics/` - Generated analysis reports
- `canvas/` - CodeCanvas state copies
- `experiment_*.log` - Experiment log

But the terminalbench code still hardcodes paths assuming a flat `results/runs/` structure.

---

### Changes Required

#### 1. **terminalbench/core/config.py**
- Change `output_dir` default from `Path("./results/runs")` to `Path("./results")`
- Add helper function `get_batch_dir(base: Path, batch_id: int | None = None) -> Path` that:
  - If `batch_id` is None: auto-detect next batch ID (max existing + 1)
  - Creates and returns `{base}/{batch_id}/` structure

#### 2. **terminalbench/scripts/run-experiment.sh**
```bash
# Replace hardcoded paths with batch-aware logic:
BATCH_ID=$(ls -d "$PROJECT_ROOT/results"/[0-9]* 2>/dev/null | wc -l)
BATCH_DIR="${PROJECT_ROOT}/results/${BATCH_ID}"
mkdir -p "$BATCH_DIR"/{runs,analytics,canvas}
RESULTS_DIR="${BATCH_DIR}/runs"
LOGFILE="${BATCH_DIR}/experiment_$(date +%Y%m%d_%H%M%S).log"

# Update analytics command at end:
python3 -m terminalbench.analytics "$RESULTS_DIR" --output "$BATCH_DIR/analytics/"
```

#### 3. **terminalbench/ui/cli.py**
- Add `--batch` argument (optional int, default=None for auto)
- Resolve batch directory before passing to HarborRunner:
```python
from terminalbench.core.config import get_batch_dir
batch_dir = get_batch_dir(args.output_dir, args.batch)
runner = HarborRunner(output_root=batch_dir / "runs", ...)
```

#### 4. **terminalbench/analytics/io/cli.py**
- Change `--output` default from `Path("results/analytics")` to `None`
- Auto-derive output path from runs_dir parent:
```python
if args.output is None:
    args.output = args.runs_dir.parent / "analytics"
```

#### 5. **terminalbench/harbor/runner.py**
- No changes needed - it already uses `output_root` passed by caller

#### 6. **terminalbench/analytics/io/parser.py**
- No changes needed - works with explicit `runs_dir` path

---

### Backward Compatibility
- Analytics CLI will auto-detect if given a batch's `runs/` subdirectory
- Old flat structure still works if user explicitly provides full path

---

### Testing Checklist
- [ ] New experiment creates batch N+1 directory
- [ ] All outputs land in correct batch subdirectories
- [ ] Analytics correctly reads from batch's runs/ dir
- [ ] Analytics outputs to batch's analytics/ dir
- [ ] Explicit `--batch N` flag works