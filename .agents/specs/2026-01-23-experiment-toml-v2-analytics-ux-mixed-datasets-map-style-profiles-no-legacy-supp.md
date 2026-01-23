# Principles

- **TOML-first** UX: configuration lives in `experiments/<exp>.toml`; CLI flags are only for *quick filtering* (`--tasks`, `--profiles`, `--batch`).
- **No legacy support**: we do **schema v2 only** (fail fast if missing/incorrect).
- **Clear, intuitive config**: no array-of-tables for profiles; tasks and profiles both use keyed subtables.

---

# TOML v2 Schema (final)

```toml
schema_version = 2
name = "TB2 core7: ..."
slug = "tb2-core7__t-cg-cc__haiku45-low"

[run]
results_root = "results"
profiles_parallel = 3
attempts = 1
retries = 0
parallel = 0
container_env = "docker"
force_rebuild = true

[defaults]
model = "anthropic/claude-haiku-4-5"
reasoning = "low"
mcp_git_source = "https://github.com/ain3sh/codecanvas"
env_file = "experiments/.env"

[artifacts]
targets = ["codecanvas"]

[tasks]
# Optional convenience; used only when a task omits dataset
# If omitted, default is "terminal-bench@2.0"
default_dataset = "terminal-bench@2.0"

# Task order is definition order in this file.
# If a task id contains a dot, quote it: [tasks."my.task"]
[tasks.sanitize-git-repo]

[tasks.build-cython-ext]

[tasks.custom-task]
dataset = "my-dataset@1.0"   # mixed dataset supported

[profiles.text]
no_mcp = true

[profiles.codegraph]
mcp_servers = ["codegraph"]

[profiles.codecanvas]
mcp_servers = ["codecanvas"]
hooks = "codecanvas/hooks.json"
```

### Validation rules
- `schema_version` is **required** and must equal `2`.
- `slug` required; must be filesystem-safe.
- **Tasks**:
  - Keys under `[tasks]` (except `default_dataset`) are the task IDs.
  - Each task may optionally define `dataset`.
  - Effective dataset = `tasks.<id>.dataset` else `tasks.default_dataset` else `terminal-bench@2.0`.
  - Task IDs must be unique (they are by construction) and **must not collide via dotted keys** unless quoted.
- **Profiles**:
  - Keys under `[profiles]` are profile keys.
  - If `no_mcp=true` → treat as MCP disabled; ignore `mcp_servers`; ignore `hooks` unless explicitly set (same behavior as today).
  - If `no_mcp=false` → require non-empty `mcp_servers`.

---

# Clean terminal invocation (final)

## Run
```bash
uv run python -m terminalbench.experiments run experiments/<exp>.toml
```
Optional filters:
```bash
... --tasks sanitize-git-repo build-cython-ext
... --profiles codecanvas
... --batch 0
```

## Analyze (new)
```bash
uv run python -m terminalbench.experiments analyze experiments/<exp>.toml
```
- If `--batch` omitted → pick **latest numeric** batch under `results/<slug>/`.
- Uses `runs_dir = results/<slug>/<batch>/runs` and writes to `results/<slug>/<batch>/analytics`.
- Pass through key analytics flags (`--no-llm`, `--llm-only`, `--model`, `--tasks`, `--profiles`, `--compare`, `--limit`, `--list`, `--succeeded`, `--failed`, `--estimate-cost`, `--quiet`).

---

# Work breakdown (sub-todos)

## 1) Mixed dataset tasks
1. Update `terminalbench/experiments/config.py`:
   - parse/validate `schema_version==2`
   - parse `[tasks]` as mapping; build an ordered `List[TaskEntry(id, dataset)]`
2. Update `terminalbench/experiments/cli.py`:
   - `_build_tasks()` consumes the ordered `TaskEntry` list
   - `--tasks` filtering remains by task id
3. Update CodeCanvas task listing (`codecanvas/core/state.py`):
   - remove any `tasks.yaml` parsing; list tasks from `experiments/*.toml` using **v2 schema** only

## 2) Profiles as `[profiles.<key>]`
1. Update `terminalbench/experiments/config.py`:
   - parse `[profiles]` mapping into ordered `List[ProfileConfig(key, ...)]`
2. Update `terminalbench/experiments/cli.py`:
   - `_build_profiles()` iterates ordered list and validates per-profile MCP rules
3. Migrate existing example experiment TOML(s) to v2

## 3) Analytics alignment + UX
1. Add `analyze` subcommand to `terminalbench.experiments`:
   - derive results path from experiment TOML
   - select latest batch if not provided
   - call existing analytics entrypoints with derived `runs_dir`
2. Update analytics CLI help text examples (code help output only) to reflect `results/<slug>/<batch>/runs`.

---

# Validation (after implementation)
- `uv run ty check codecanvas terminalbench`
- `uv run ruff check --fix codecanvas terminalbench`
- `uv run pytest`
- Smoke:
  - `... terminalbench.experiments run ... --profiles codecanvas --tasks sanitize-git-repo`
  - `... terminalbench.experiments analyze ...` (latest batch)

---

If you approve, I’ll implement TOML v2 (tasks+profiles), remove all remaining tasks.yaml plumbing (no legacy), add `analyze`, migrate the example experiment file, and run validators.