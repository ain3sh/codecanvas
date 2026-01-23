# AGENTS.md

Project instructions for AI agents.

iterative improvement flow: `make changes -> commit/push (including any spec files) -> clean up results/* -> re-run task with 600s timeout (no batch flag, tasks list in experiments/*.toml) -> analyze run artifacts -> report back to me with your findings`

validators: `uv run ty check codecanvas terminalbench && uv run ruff check --fix codecanvas terminalbench && uv run pytest`

test run 600s timeout (task-list in experiments/*.toml): `cd "/mnt/d/Personal_Folders/Tocho/ain3sh/codecanvas" && TERMINALBENCH_FORCE_REBUILD=1 uv run python -m terminalbench.experiments run experiments/tb2-core7__t-cg-cc__haiku45-low.toml --tasks <task>`

task URL roots:
- TB: `https://www.tbench.ai/registry/terminal-bench/2.0/<task_id>`
- GH: `https://github.com/laude-institute/terminal-bench-2/tree/main/<task_id>`

---

## Skills

@.agents/SKILLS.md
