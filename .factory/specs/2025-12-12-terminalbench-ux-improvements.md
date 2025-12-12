## TerminalBench UX Improvements Spec

### 1. Fix Naming Mismatch (Critical)
**Issue:** Code uses `harbor` but official CLI is `tb` (from `pip install terminal-bench`)
- Rename `HarborRunner` → `TBRunner`  
- Change `harbor_bin` default from `"harbor"` → `"tb"`
- Update `--harbor-bin` arg → `--tb-bin`
- Update `jobs_dir` default from `./harbor_runs` → `./tb_runs`
- Update docstrings/comments

### 2. Progress Bars & Live Output
**Current:** `subprocess.run(capture_output=True)` blocks silently
**Fix:** Add `rich` for progress display:
```python
# runner.py - stream output while showing progress
with Progress(...) as progress:
    task = progress.add_task(f"[cyan]{profile.key}/{task.id}", total=None)
    proc = subprocess.Popen(cmd, stdout=PIPE, stderr=PIPE, ...)
    # Stream and display output in real-time
```
- Show spinner per-task with elapsed time
- Option `--quiet` to suppress live output (for CI)

### 3. Result Aggregation & Comparison Stats
**Add to cli.py after runs complete:**
```
═══════════════════════════════════════════════════
                  RESULTS SUMMARY
═══════════════════════════════════════════════════
Agent        Passed  Failed  Total  Accuracy  Avg Time
──────────────────────────────────────────────────
text            4       3      7      57.1%    45.2s
locagent       5       2      7      71.4%    38.1s
codecanvas      6       1      7      85.7%    52.3s
═══════════════════════════════════════════════════
```
- Per-agent breakdown
- Task-level matrix (which tasks each agent passed/failed)
- Export to CSV with `--csv results.csv`

### 4. Verbose Dry-Run Output
**Current:** Silent, just returns empty CompletedProcess
**Fix:** Print commands that would execute:
```python
if self.dry_run:
    print(f"[DRY-RUN] {' '.join(cmd)}")
    print(f"          env: {profile.env()}")
```

### 5. Parallel Execution
**Add `--parallel N` flag:**
```python
# runner.py
from concurrent.futures import ThreadPoolExecutor

def run_tasks_parallel(self, tasks, profile, max_workers=4):
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(self._run_single, t, profile): t for t in tasks}
        # Collect results with progress updates
```
- Default: sequential (current behavior)
- `--parallel 4`: run up to 4 tasks concurrently

### 6. Retry-on-Failure Logic
**Add `--retries N` flag (default 0):**
```python
def _run_single(self, task, profile):
    for attempt in range(1, self.retries + 2):
        result = self._execute(task, profile)
        if result.success:
            return result
        if attempt <= self.retries:
            print(f"[RETRY] {task.id} attempt {attempt+1}/{self.retries+1}")
    return result  # Return last failed result
```

### 7. Enhanced Verification
**Parse `results.json` from jobs_dir after run:**
```python
@dataclass
class RunResult:
    # ... existing fields ...
    accuracy: Optional[float] = None  # from results.json
    tests_passed: Optional[int] = None
    tests_total: Optional[int] = None

def _parse_results_json(self, jobs_dir: Path) -> dict:
    results_file = jobs_dir / "results.json"
    if results_file.exists():
        return json.loads(results_file.read_text())
    return {}
```

### 8. Simple Setup CLI (`tb-setup` subcommand)
**New interactive config wizard:**
```bash
$ python -m terminalbench setup

TerminalBench Configuration
───────────────────────────
Model [anthropic/claude-haiku-4-5]: 
Reasoning level (low/medium/high) [medium]: 
LocAgent MCP server URL (optional): 
CodeCanvas MCP server URL (optional): 
Hooks file path (optional): 

Saved to ~/.terminalbench/config.yaml
```
- Store config in `~/.terminalbench/config.yaml`
- Auto-load in `run_cli()` as defaults
- Override with CLI args

### Implementation Order
1. **Naming fix** (breaking change, do first)
2. **Dry-run verbosity** (quick win)
3. **Result aggregation** (high value)
4. **Progress bars** (requires `rich` dep)
5. **Retry logic** (straightforward)
6. **Parallel execution** (moderate complexity)
7. **Enhanced verification** (depends on tb output format)
8. **Setup CLI** (nice-to-have, lowest priority)

### Dependencies to Add
```toml
# pyproject.toml
dependencies = [
    "pyyaml",
    "rich>=13.0",  # progress bars, tables
]
```

### Files Modified
- `runner.py` - TBRunner, parallel, retry, verification
- `cli.py` - new args, summary output, setup subcommand
- `agents.py` - minor (config loading)
- New: `config.py` - config file handling
- New: `display.py` - rich-based output formatting