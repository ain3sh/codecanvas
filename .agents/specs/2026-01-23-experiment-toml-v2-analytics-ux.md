# Overview

We’ll introduce an **Experiment TOML v2** that is (a) easy to read/write, (b) supports **mixed task datasets**, (c) uses **map-style profiles** (`[profiles.<key>]`), and (d) provides a clean analytics entrypoint aligned with `results/<slug>/<batch>/...`.

Terminal usage stays config-first:

- Run: `uv run python -m terminalbench.experiments run experiments/<exp>.toml`
- Analyze: `uv run python -m terminalbench.experiments analyze experiments/<exp>.toml`

---

# 1) Tasks v2: mixed datasets, clean + ordered

## TOML schema

```toml
[tasks]
# Default dataset for any task item that omits `dataset`
default_dataset = "terminal-bench@2.0"

# Ordered task list (supports mixed datasets)
items = [
  { id = "sanitize-git-repo" },
  { id = "build-cython-ext" },
  { id = "my-task", dataset = "my-dataset@1.0" },
]
```

## Semantics
- `tasks.items` is the **single source of truth** for tasks and their order.
- Each item requires `id` and may optionally specify `dataset`.
- If `dataset` omitted: use `tasks.default_dataset`, else default to `terminal-bench@2.0`.

## Why this design
- Order is explicit and stable.
- Mixed datasets are natural.
- No “per-task subtables” explosion for large lists.
- Parsing is straightforward with `tomllib` (`items` becomes a list of dicts).

### Sub-todos
1. Update `terminalbench/experiments/config.py` dataclasses to represent `tasks.items` (e.g., `TaskItem{id,dataset}`) and parse/validate it.
2. Update `terminalbench/experiments/cli.py` to build `Task` objects from `tasks.items` and keep `--tasks` as an optional filter.
3. Update `codecanvas/core/state.py` experiment discovery to read `tasks.items` so `task_select` still works with experiments.
4. Migrate existing experiment TOMLs to v2 tasks format.

---

# 2) Profiles v2: `[profiles.<key>]` (no array-of-tables)

## TOML schema

```toml
[profiles.text]
no_mcp = true

[profiles.codegraph]
mcp_servers = ["codegraph"]

[profiles.codecanvas]
mcp_servers = ["codecanvas"]
hooks = "codecanvas/hooks.json"
```

## Semantics
- Each profile key is the table name (`text`, `codegraph`, `codecanvas`).
- Execution order follows declaration order in the TOML.
- Validation:
  - If `no_mcp=true`, `mcp_servers` is treated as empty and hooks default off unless explicitly set.
  - If `no_mcp=false`, require `mcp_servers` non-empty.

## Why this design
- It’s the canonical “clean TOML” way to express keyed configs.
- Eliminates the confusing `[[profiles]]` + `key = ...` pattern.

### Sub-todos
1. Update `terminalbench/experiments/config.py` parser to treat `profiles` as a dict and build profile configs from `(key, table)` pairs.
2. Update the example experiment TOML(s) to the new format.
3. Keep `--profiles` as an optional filter (keys match `profiles.<key>`).

---

# 3) Analytics: align with results + make invocation clean

## Current compatibility
Analytics already operates on a `runs/` directory, which still exists at:

- `results/<slug>/<batch>/runs`

So the core analytics logic is compatible.

## Improvement: `terminalbench.experiments analyze`

Add:

```bash
uv run python -m terminalbench.experiments analyze experiments/<exp>.toml [--batch N]
```

Behavior:
- Derive `slug` from the experiment TOML.
- Locate batch:
  - If `--batch` provided, use it.
  - Otherwise use **latest numeric batch** under `results/<slug>/`.
- Run analytics against `results/<slug>/<batch>/runs`.
- Default output to `results/<slug>/<batch>/analytics`.
- Pass through common analytics flags (`--no-llm`, `--llm-only`, `--model`, `--tasks`, `--profiles`, `--compare`, `--limit`, `--list`, `--succeeded`, `--failed`, `--estimate-cost`, `--quiet`).

Implementation note (keep it clean):
- Extract the current analytics CLI body into a reusable function (e.g., `terminalbench.analytics.run.run_analysis(...)`) and call it from both the analytics CLI and the new `analyze` subcommand (avoids `sys.argv` patching).

### Sub-todos
1. Add `analyze` subcommand to `terminalbench.experiments`.
2. Implement “latest batch” selection logic.
3. Refactor analytics entrypoint into an importable function and reuse it.
4. Smoke-test analyze against an existing batch.

---

# Example full TOML (v2)

```toml
schema_version = 2
name = "TB2 core7: codecanvas only (haiku low)"
slug = "tb2-core7__cc__haiku45-low"

[run]
results_root = "results"
profiles_parallel = 1
force_rebuild = true

[defaults]
model = "anthropic/claude-haiku-4-5"
reasoning = "low"
mcp_git_source = "https://github.com/ain3sh/codecanvas"
env_file = "experiments/.env"

[tasks]
default_dataset = "terminal-bench@2.0"
items = [
  { id = "sanitize-git-repo" },
  { id = "build-cython-ext" },
  { id = "some-other-task", dataset = "other-dataset@1.0" },
]

[artifacts]
targets = ["codecanvas"]

[profiles.codecanvas]
mcp_servers = ["codecanvas"]
hooks = "codecanvas/hooks.json"
```

---

# Validation
After implementing v2 + analyze:
- `uv run ty check codecanvas terminalbench`
- `uv run ruff check --fix codecanvas terminalbench`
- `uv run pytest`

---

If you approve this v2 schema + `analyze` command design, I’ll implement the migration end-to-end (parser, runner, codecanvas task discovery, analytics wrapper) and update the sample experiment TOML(s).