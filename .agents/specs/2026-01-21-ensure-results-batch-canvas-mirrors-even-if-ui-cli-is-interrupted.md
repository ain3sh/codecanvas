# Goal
Fix cases where `results/<batch>/canvas/` stays empty even though CodeCanvas artifacts exist under `results/<batch>/runs/<job>/<trial>/agent/sessions/codecanvas/`.

# What’s happening (root cause)
`results/<batch>/canvas/<trial>/` is populated by `terminalbench/harbor/runner.py:HarborRunner._mirror_codecanvas_artifacts()`, which is only invoked **after** `subprocess.run(cmd, env=env)` returns in `_run_single()`.

If the UI process (`python -m terminalbench.ui.cli …`) is interrupted/terminated while the Harbor subprocess keeps running (common when a wrapper times out/cancels), the Harbor job can still finish and write `result.json`, but the mirror step never runs—leaving `results/<batch>/canvas` empty.

# Acceptance criteria
- After a completed run, `results/<batch>/canvas/<trial>/` exists and contains the `agent/sessions/codecanvas/*` files (PNGs + JSONs), matching the corresponding run directory.
- If the UI CLI is terminated while the Harbor job continues and finishes later, the mirror still happens automatically (Option B) or is at least attempted on exit (Option A).

# Option A: Mirror on exit (SIGTERM/atexit)
## Changes
1. Add a public helper on `HarborRunner`:
   - `mirror_latest_codecanvas_artifacts(task_ids: list[str]) -> None`
   - Finds latest `job_dir` under `output_root` and calls `_mirror_codecanvas_artifacts(job_dir=…, task_id=…)` for each task.
2. In `terminalbench/ui/cli.py`, wrap `runner.run_profiles(...)` with:
   - `try/finally` to call `runner.mirror_latest_codecanvas_artifacts([t.id for t in tasks])`.
   - Install `SIGTERM`/`SIGINT` handlers that run the same mirror helper, then re-raise/exit.

## Pros/Cons
- ✅ Minimal change; no extra processes.
- ❌ If terminated early, mirror may run before artifacts exist (or copy partial). If killed hard (SIGKILL), nothing runs.

# Option B: Detached mirror watchdog (recommended)
## Changes
1. Add a small module, e.g. `terminalbench/harbor/mirror_codecanvas.py`:
   - Args: `--runs-dir`, `--job-name`, `--task-id`, `--poll-seconds`, `--timeout-seconds`.
   - Waits for `<runs-dir>/<job-name>/result.json` (or timeout).
   - On completion, mirrors `<trial>/agent/sessions/codecanvas` → `results/<batch>/canvas/<trial>` (best-effort, per task).
2. In `terminalbench/harbor/runner.py:_run_single()`:
   - When `output_root` and `job_name` are known, spawn the watchdog via `subprocess.Popen([sys.executable, "-m", "terminalbench.harbor.mirror_codecanvas", ...], start_new_session=True, stdout/stderr=DEVNULL)`.
   - Keep existing `_mirror_codecanvas_artifacts(...)` call for the normal (non-interrupted) path.
3. (Optional but nice) Also keep Option A’s `finally` mirror as a fast path; watchdog remains the “last resort.”

## Pros/Cons
- ✅ Robust even if the UI process dies mid-run, as long as the Harbor job completes and writes to the same `results/<batch>/runs` directory.
- ✅ Mirror happens *after* job completion, so canvas contains final artifacts.
- ❌ Slight complexity: one extra short-lived process per task run.

# Validation
After implementation:
1. Run validators: `uv run ty check codecanvas terminalbench && uv run ruff check --fix codecanvas terminalbench && uv run pytest`.
2. Re-run `modernize-scientific-stack` and confirm `results/0/canvas/<trial>/` is populated.
3. Simulate interruption: start the run, terminate the UI CLI early, wait for job completion, verify `results/0/canvas/<trial>/` is still populated (Option B) or at least contains partial artifacts (Option A).
