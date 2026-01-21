# AGENTS.md

Project instructions for AI agents.

iterative improvement flow: `make changes -> commit/push (including any spec files) -> clean up results/* -> re-run task with 600s timeout (no batch flag, tasks list in tasks.yaml) -> analyze run artifacts -> report back to me with your findings`

validators: `uv run ty check codecanvas terminalbench && uv run ruff check --fix codecanvas terminalbench && uv run pytest`

test run 600s timeout (task-list in tasks.yaml): `cd "/mnt/d/Personal_Folders/Tocho/ain3sh/codecanvas" && TERMINALBENCH_FORCE_REBUILD=1 uv run python -m terminalbench.ui.cli --manifest tasks.yaml --tasks <task> --model anthropic/claude-haiku-4-5 --reasoning low --profiles-parallel 1 [--batch <n>] -C --mcp-server codecanvas --mcp-git-source https://github.com/ain3sh/codecanvas --hooks codecanvas/hooks/hooks.json --key codecanvas`

---

## Skills

@.agents/SKILLS.md
