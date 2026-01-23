# What went wrong (from logs)

Harbor refuses to reuse an existing job directory with a different `JobConfig`.

Our runner currently calls **`harbor run` once per task** but passes the **same `--job-name` per profile** (e.g. `2026-01-23__16-26-48__codecanvas`). On the 2nd task, Harbor sees `runs/<job-name>/config.json` already exists and the config differs (task list changes), so it raises:

> `FileExistsError: Job directory ... already exists and cannot be resumed with a different config.`

This is why only the first task actually produced a trajectory; subsequent tasks show `exit_code=1` and no `trajectory.json`.

---

# Requirements (confirmed)

- **No fallbacks / no legacy.**
- **Mixed dataset tasks must NOT force multiple Harbor runs.**
- Preserve **per-profile** agent customization (MCP config, hooks, model/reasoning, prompts, etc.).

---

# Proposed fix (do it right)

## A) Run exactly ONE Harbor job per profile (not per task)

For each profile, we generate a **Harbor `JobConfig` JSON** that includes **all tasks**, grouped by dataset, and run:

```bash
uvx --python 3.13 harbor run -c <job_config.json>
```

This gives:
- **No job-name collisions** (single job dir per profile)
- **Mixed datasets in one run** (multiple dataset entries inside one `JobConfig`)
- **No degradation** of per-profile agent kwargs (we encode them directly in `AgentConfig.kwargs`)

### JobConfig shape
- `job_name`: `<timestamp>__<profile_key>`
- `jobs_dir`: `<batch>/runs`
- `environment`: `type=cfg.run.container_env`, `delete=false`, `force_build=<computed>`
- `orchestrator.n_concurrent_trials`: from `cfg.run.parallel` (or default)
- `orchestrator.retry.max_retries`: from `cfg.run.retries` (maps cleanly to Harbor’s native retry)
- `agents`: a single `AgentConfig` built from the `AgentProfile` (import_path/model_name/kwargs)
- `datasets`: one `RegistryDatasetConfig` per dataset with `task_names=[...]` (supports mixed datasets)

## B) Index + analytics compatibility

After the job finishes, we build `runs/index.json` by **scanning the job dir** for trial folders and collecting:
- `task_id` from each trial `result.json` (`task_name`)
- `agent_key` = profile key
- `trajectory_json` path
- `job_dir` / `results_json` paths

This keeps analytics working without changing the analytics parser.

## C) Artifact mirroring

Update `terminalbench.harbor.mirror_artifacts` to mirror **all trials in a job** (no `--task-id` required), triggered when `<job_dir>/result.json` appears.
The runner spawns **one** watcher per job.

## D) Fix `terminalbench.experiments kill` self-kill

The current kill heuristic matches `uv run ... terminalbench.experiments kill` and can kill its own wrapper, resulting in SIGKILL. We’ll exclude commands containing `terminalbench.experiments kill` from the kill set.

---

# Implementation steps (atomic)

1. Refactor `terminalbench/harbor/runner.py` to:
   - build a `JobConfig` JSON per profile (group tasks by dataset)
   - run Harbor once per profile (`harbor run -c ...`)
   - populate `runs/index.json` by scanning produced trial dirs
2. Update `terminalbench/harbor/mirror_artifacts.py`:
   - remove required `--task-id`
   - mirror all trial dirs for provided targets once job `result.json` exists
3. Patch `terminalbench/experiments/cli.py` / metadata if needed (no user-facing changes beyond “it works”).
4. Patch kill command to avoid killing itself.
5. Validators: `ty`, `ruff --fix`, `pytest`.
6. Flow per AGENTS.md: clean `results/*`, rerun with 600s timeout, run `terminalbench.experiments analyze`, then report findings.

---

If you approve, I’ll implement exactly the above (no legacy paths, no fallback mode).