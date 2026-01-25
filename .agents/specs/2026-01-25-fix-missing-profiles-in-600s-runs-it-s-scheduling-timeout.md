# Findings (why it looked like only codegraph ran)

- The profiles **were registered**. `terminalbench.experiments` calls `runner.run_profiles(tasks, profiles, profiles_parallel=cfg.run.profiles_parallel)`.
- In `HarborRunner.run_profiles`, when `TERMINALBENCH_FORCE_REBUILD=1` (your standard command), `profile_needs_rebuild()` returns **True for every profile**, so we take the `any_rebuild` path.
- That path runs profiles in this order:
  1) **canonical MCP profile** first (in your config order that’s `codegraph`),
  2) then **incompatible MCP profiles** sequentially (here: `codecanvas`),
  3) only **after that** the “compatible” baseline profile (here: `text`).

So with a hard 600s wall timeout, it’s totally possible to finish `codegraph`, get most of the way through `codecanvas`, and **never reach `text`**.

## Evidence from your results directory
- `results/.../runs/2026-01-23__17-19-26__codecanvas/...` exists and contains `agent/trajectory.json` **and** `verifier/{reward.txt, ctrf.json}` but **no** trial `result.json` → Harbor was killed before finalizing the trial/job, consistent with a 600s timeout.

I’m not “very unsure”, so I’m **not** using `gh` to bisect right now.

---

# Goal

Make `--profiles text codegraph codecanvas` on **one task** reliably produce **all three** within the 600s run budget, without changing per-profile MCP/hooks/model behavior.

---

# Options

## Option A (minimal change): Run profiles concurrently even under rebuild

### Changes
1. In `terminalbench/harbor/runner.py`:
   - If `profiles_parallel > 0`, run **all requested profiles concurrently** (ThreadPoolExecutor) regardless of the `any_rebuild` canonical/incompatible sequencing.
   - Compute `force_build` per profile as today.
2. Prevent `runs/index.json` corruption under concurrency:
   - Add a `threading.Lock` around `_update_index()` (or write index once at the end from collected results).
3. (Optional) Print the resolved profile execution plan at start of `terminalbench.experiments run` so it’s obvious what’s queued.

### Why this fixes the symptom
Total wall time becomes ~`max(profile_runtime)` instead of `sum(profile_runtime)`, so `text` can’t be starved behind `codecanvas`.

---

## Option B (more integrated): Single Harbor job with multiple agents (one Harbor run total)

### Changes
1. Build one `JobConfig` with:
   - `datasets` grouped by dataset (mixed datasets supported)
   - `agents=[AgentConfig(...)]` **one per profile**
2. Set `AgentConfig.name = <profile_key>` so we can reconstruct `agent_key` for analytics.
3. After Harbor completes, scan trial dirs and build `runs/index.json` using:
   - `task_id` from trial `result.json` (`task_name`)
   - `profile_key` from `result.json.config.agent.name`

### Why this is “cleanest”
Harbor orchestrates concurrency across agents/tasks inside one job; no runner-level parallelism or index races.

---

# Validation plan (for either option)

1. Run validators: `uv run ty check ... && uv run ruff check --fix ... && uv run pytest`
2. **Commit/push**
3. `rm -rf results/*`
4. Re-run (600s):
   ```bash
   TERMINALBENCH_FORCE_REBUILD=1 uv run python -m terminalbench.experiments run \
     experiments/tb2-core7__t-cg-cc__haiku45-low.toml \
     --tasks sanitize-git-repo \
     --profiles text codegraph codecanvas
   ```
5. Verify `results/.../runs/index.json` has **3** entries and each profile job/trials have `result.json`.
6. Run `terminalbench.experiments analyze ...` and report findings.

---

Pick Option A (minimal) vs Option B (single Harbor run).