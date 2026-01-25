## What happened (evidence from `results/`)

### Structure
- `results/tb2-core7__t-cg-cc__haiku45-low/0/runs/2026-01-24__23-29-06__profiles/`
  - `config.json` → **3 agents** configured: `text`, `codegraph`, `codecanvas` (this confirms the multi-agent single-job change is in effect)
  - `result.json` (job-level) → `finished_at=null`, `n_total_trials=3`, but only `n_trials=2`
  - Trial dirs:
    - `sanitize-git-repo__De2AJm4` (**codegraph**) → has `result.json`, `verifier/{ctrf.json,reward.txt}`, `agent/trajectory.json`
    - `sanitize-git-repo__rJ7MJmL` (**text**) → has `result.json`, `verifier/{ctrf.json,reward.txt}`, `agent/trajectory.json`
    - `sanitize-git-repo__kFhcVy3` (**codecanvas**) → **missing** `result.json` + `agent/trajectory.json`; verifier dir empty

### Why codecanvas looks “missing”
- In `sanitize-git-repo__kFhcVy3/agent/claude-code.txt` (WarpGrep + tail read), the codecanvas agent **did run**, edited the intended files, verified secrets removed via `grep`, and even created a git commit inside the task repo (`[main 5ef6867] Sanitize repository of exposed credentials`).
- But Harbor never wrote the trial-level `result.json` (and therefore the runner couldn’t index it), and the wrapper never got to write `agent/trajectory.json` before the hard 600s wall-time cutoff.

### Why `terminalbench.experiments analyze` failed
- Analytics uses `terminalbench.analytics.io.parser.TrajectoryParser`, which only reads `runs/index.json`.
- `runs/index.json` is written by `HarborRunner._update_index()` **only after** `subprocess.run(harbor …)` returns.
- Because the overall CLI was killed at 600s, we never reached the post-run indexing step, so analyze saw “No trajectories found.”

## Expected vs actual (mapping back to our change)

### Expected (after “single Harbor job with multi-agent profiles”)
- 1 job dir containing 3 trials (one per profile)
- Each trial produces:
  - `trial/result.json`
  - `trial/agent/trajectory.json`
  - `trial/verifier/*`
- Runner writes `runs/index.json`
- `terminalbench.experiments analyze …` succeeds

### Actual
- All 3 trials were created.
- `text` + `codegraph` completed (but **failed verifier**, reward 0.0).
- `codecanvas` progressed far (appears to have finished the “fix” work) but did **not** reach the point where Harbor persisted `trial/result.json` / `agent/trajectory.json` / verifier output before the 600s cutoff.
- No `runs/index.json` → analyze fails.

## Delta + root cause
1. **Hard wall-time cutoff (600s) kills the runner before post-processing** → no `runs/index.json`.
2. **codecanvas trial runtime + overhead left no buffer** for Harbor to finish verifier + flush `result.json` + trajectory extraction before the cutoff.
3. **Analytics is brittle**: it requires `runs/index.json` and won’t scan the directory for trajectories.

## Fix plan (pick one option)

### Option A: Make analyze resilient (scan runs/ even without index.json)
1. Update `TrajectoryParser._load_index()`:
   - If `runs/index.json` is missing/invalid, scan `runs/**/agent/trajectory.json`.
   - For each found trajectory, locate sibling `trial/result.json` (if present) to derive `task_id` + `profile_key`; otherwise fall back to `trial/config.json`.
   - Build an in-memory index and proceed.
2. (Optional) When scanning succeeds, write a best-effort `runs/index.json` so future calls are fast.

**Pros:** minimal change; analyze works even on partial runs.

**Cons:** doesn’t solve the “codecanvas missing result.json” problem; only improves post-mortem + robustness.

### Option B: Write index incrementally + graceful 600s timeout (runner-side)
1. Add a runner-side watchdog process (similar to `mirror_artifacts`) that:
   - Periodically scans job dirs for newly finished trials (`trial/result.json`)
   - Updates `runs/index.json` continuously while Harbor is still running
2. Add a runner-enforced timeout slightly under 600s (e.g. 585–590s) so the Python CLI can:
   - terminate Harbor,
   - write any remaining index entries,
   - exit cleanly before the external 600s kill.

**Pros:** `runs/index.json` exists even if the run is cut off; analyze can always run; avoids “runner killed before post-step.”

**Cons:** more moving parts; still may cut off `codecanvas` if it’s near the limit.

## Validation (per `AGENTS.md` loop)
1. Run validators: `uv run ty check … && uv run ruff check --fix … && uv run pytest`
2. Commit + push (include any spec files)
3. `rm -rf results/*`
4. Re-run 600s: `TERMINALBENCH_FORCE_REBUILD=1 uv run python -m terminalbench.experiments run … --tasks sanitize-git-repo --profiles text codegraph codecanvas`
5. Run `terminalbench.experiments analyze …` and report findings (should work even if run is partial, depending on chosen option).

---

If you want the fastest path to better post-mortems immediately, I recommend **Option A** first; if you want the whole loop to be robust under hard timeouts, pick **Option B**.