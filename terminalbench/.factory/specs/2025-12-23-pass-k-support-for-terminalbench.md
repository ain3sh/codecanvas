## pass@k Implementation Spec

### Design Philosophy
- **pass@k becomes THE metric** - not an optional add-on
- **Clean breaks over cruft** - rename `--attempts` to `--samples`, update data model
- **Elegant defaults** - `--samples 1` gives pass@1, displayed as "pass@1" not "Accuracy"

---

### Changes

#### 1. `analytics/core/pass_at_k.py` (NEW)

```python
from dataclasses import dataclass
from statistics import mean, stdev
from typing import Dict, List

def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k estimator (Codex paper)."""
    if n - c < k:
        return 1.0
    if c == 0:
        return 0.0
    result = 1.0
    for i in range(k):
        result *= (n - c - i) / (n - i)
    return 1.0 - result

@dataclass
class PassAtKResult:
    k: int
    mean: float
    std: float
    n_tasks: int
    per_task: Dict[str, float]
    min_samples: int

def compute_pass_at_k(
    task_results: Dict[str, List[bool]],
    k_values: List[int]
) -> Dict[int, PassAtKResult]:
    """Compute pass@k per task, aggregate across tasks."""
    results = {}
    for k in k_values:
        per_task = {}
        for task_id, successes in task_results.items():
            n, c = len(successes), sum(successes)
            if n >= k:
                per_task[task_id] = pass_at_k(n, c, k)
        
        if per_task:
            vals = list(per_task.values())
            results[k] = PassAtKResult(
                k=k,
                mean=mean(vals),
                std=stdev(vals) if len(vals) > 1 else 0.0,
                n_tasks=len(per_task),
                per_task=per_task,
                min_samples=min(len(task_results[t]) for t in per_task),
            )
    return results
```

#### 2. `harbor/runner.py`

**Rename `attempts` → `samples`:**
```python
class HarborRunner:
    def __init__(
        self,
        samples: int = 1,           # was: attempts
        samples_parallel: int = 1,  # NEW
        ...
    ):
        self.samples = samples
        self.samples_parallel = samples_parallel
```

**Collect ALL trajectories:**
```python
def _find_all_trajectories(self, job_dir: Path, task_id: str) -> List[Tuple[int, Path, Path]]:
    """Find all trajectory.json files for a task."""
    results = []
    for trial_dir in sorted(job_dir.iterdir()):
        if trial_dir.is_dir() and trial_dir.name.startswith(f"{task_id}__"):
            traj = trial_dir / "agent" / "trajectory.json"
            if traj.exists():
                idx = int(trial_dir.name.split("__")[1]) if "__" in trial_dir.name else len(results)
                results.append((idx, traj, trial_dir))
    return results
```

**Update RunResult:**
```python
@dataclass
class RunResult:
    task_id: str
    agent_key: str
    sample_index: int      # NEW - mandatory
    exit_code: int
    success: bool
    ...
```

**Batched sampling with parallelism:**
```python
def run_samples(self, tasks, profile) -> List[RunResult]:
    """Run samples with resource-efficient batching."""
    if self.samples_parallel <= 1:
        # Single Harbor invocation
        cmd_samples = self.samples
        return self._run_batch(tasks, profile, cmd_samples, sample_offset=0)
    
    # Parallel batches
    batch_size = (self.samples + self.samples_parallel - 1) // self.samples_parallel
    all_results = []
    
    with ThreadPoolExecutor(max_workers=self.samples_parallel) as pool:
        futures = []
        for batch_idx in range(self.samples_parallel):
            offset = batch_idx * batch_size
            count = min(batch_size, self.samples - offset)
            if count > 0:
                futures.append(pool.submit(
                    self._run_batch, tasks, profile, count, offset
                ))
        for fut in as_completed(futures):
            all_results.extend(fut.result())
    
    return all_results
```

#### 3. `ui/cli.py`

**Replace `--attempts` with `--samples`:**
```python
parser.add_argument("--samples", "-n", type=int, default=1,
    help="samples per task for pass@k")
parser.add_argument("--samples-parallel", type=int, default=1,
    help="max concurrent sample batches")
parser.add_argument("--k", type=int, nargs="+", default=[1],
    help="k values for pass@k (default: 1)")
```

**Wire up runner:**
```python
runner = HarborRunner(
    samples=args.samples,
    samples_parallel=args.samples_parallel,
    ...
)
```

#### 4. `ui/display.py`

**Replace "Accuracy" with pass@k:**
```python
def print_summary(results: List[RunResult], k_values: List[int] = [1]) -> None:
    from terminalbench.analytics.core.pass_at_k import compute_pass_at_k
    
    # Group by (profile, task)
    by_profile = defaultdict(lambda: defaultdict(list))
    for r in results:
        by_profile[r.agent_key][r.task_id].append(r.success)
    
    table = Table(title="Results")
    table.add_column("Profile")
    for k in k_values:
        table.add_column(f"pass@{k}", justify="right")
    table.add_column("Tasks", justify="right")
    table.add_column("Samples", justify="right")
    
    for profile, task_results in by_profile.items():
        pass_at_k = compute_pass_at_k(task_results, k_values)
        row = [profile]
        for k in k_values:
            if k in pass_at_k:
                row.append(f"{pass_at_k[k].mean:.1%}")
            else:
                row.append("N/A")
        row.append(str(len(task_results)))
        row.append(str(sum(len(v) for v in task_results.values())))
        table.add_row(*row)
```

#### 5. `analytics/io/cli.py`

**Add `--k` flag, integrate pass@k:**
```python
parser.add_argument("--k", type=int, nargs="+", default=[1],
    help="k values for pass@k")

# In run_deterministic_analysis:
for profile, metrics in metrics_by_profile.items():
    task_successes = defaultdict(list)
    for m in metrics:
        task_successes[m.task_id].append(m.success)
    
    pass_at_k = compute_pass_at_k(task_successes, args.k)
    # Write to reports
```

#### 6. `analytics/io/reports.py`

Add pass@k to summary CSV and markdown.

---

### Data Model

**index.json:**
```json
{
  "runs": [
    {"task_id": "foo", "agent_key": "claude", "sample_index": 0, "success": true, ...},
    {"task_id": "foo", "agent_key": "claude", "sample_index": 1, "success": false, ...}
  ]
}
```

Old data without `sample_index`? Rerun or migrate with a script. Clean break.

---

### Files

| File | Action |
|------|--------|
| `analytics/core/pass_at_k.py` | CREATE |
| `harbor/runner.py` | MODIFY: `samples`, `samples_parallel`, `_find_all_trajectories`, `RunResult.sample_index` |
| `ui/cli.py` | MODIFY: `--samples`, `--samples-parallel`, `--k` (remove `--attempts`) |
| `ui/display.py` | MODIFY: pass@k display, remove "Accuracy" |
| `analytics/io/cli.py` | MODIFY: `--k` flag, pass@k integration |
| `analytics/io/reports.py` | MODIFY: pass@k in reports |

---

### Usage

```bash
# pass@1 (default)
terminalbench --tasks foo bar

# 20 samples, show pass@1, pass@5, pass@10
terminalbench --tasks foo bar --samples 20 --k 1 5 10

# High-throughput: 100 samples, 4 parallel workers
terminalbench --tasks foo bar --samples 100 --samples-parallel 4

# Analytics
terminalbench.analytics runs/ --k 1 5 10
```