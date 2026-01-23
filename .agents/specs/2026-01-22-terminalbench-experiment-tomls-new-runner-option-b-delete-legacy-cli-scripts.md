# Goals

- Replace `tasks.yaml + giant CLI flags + bash scripts` with **reproducible** `experiments/<slug>.toml` configs.
- Make results land in: `results/<experiment_slug>/<batch>/{runs,analytics,artifacts}`.
- Remove the legacy `terminalbench.ui.cli` execution route and related junk.
- Add a built-in `kill` command (replacement for `kill-experiment.sh`).
- Generalize CodeCanvas mirroring to **arbitrary `agent/sessions/<target>/`** directories.
- Split the monolithic repo-root `.mcp.json` into **per-server** configs at server root, and standardize `hooks.json` at server root.

# Non-goals

- No backwards-compatibility for `python -m terminalbench.ui.cli ...` or `tasks.yaml`.
- No changes to `terminalbench.analytics` behavior beyond path compatibility.

# Proposed layout

## Configs

```
experiments/
  <experiment_slug>.toml
  .env            # local-only, untracked (optional)
```

## Results

```
results/
  <experiment_slug>/
    0/
      runs/
      analytics/
      artifacts/
        codecanvas/
          <trial_dir>/...
        <other_target>/
          <trial_dir>/...
```

# Experiment TOML schema (minimal but complete)

Example `experiments/tb2-core7__t-cg-cc__haiku45-low.toml`:

```toml
name = "TB2 core7: text vs codegraph vs codecanvas (haiku low)"
slug = "tb2-core7__t-cg-cc__haiku45-low"

[run]
results_root = "results"          # base output dir
profiles_parallel = 3
attempts = 1
retries = 0
parallel = 0                       # harbor -n
container_env = "docker"
force_rebuild = true               # sets TERMINALBENCH_FORCE_REBUILD=1

[tasks]
dataset = "terminal-bench@2.0"
ids = [
  "sanitize-git-repo",
  "build-cython-ext",
  "custom-memory-heap-crash",
  "db-wal-recovery",
  "modernize-scientific-stack",
  "rstan-to-pystan",
  "fix-code-vulnerability",
]

[defaults]
model = "anthropic/claude-haiku-4-5"
reasoning = "low"
mcp_git_source = "https://github.com/ain3sh/codecanvas"
env_file = "experiments/.env"     # local-only path; not committed

[artifacts]
# Copy these from agent/sessions/<target>/ into results/.../artifacts/<target>/...
targets = ["codecanvas"]

[[profiles]]
key = "text"
no_mcp = true

[[profiles]]
key = "codegraph"
mcp_servers = ["codegraph"]

[[profiles]]
key = "codecanvas"
mcp_servers = ["codecanvas"]
hooks = "codecanvas/hooks.json"   # standardized location
```

Notes:
- `slug` is the canonical filesystem/run identity. `name` is purely human.
- No secrets in TOML; only an `env_file` *path*.

# Naming standard (short but meaningful)

Use a 3-part slug:

`<taskset>__<profileset>__<variant>`

- **taskset**: compact alias (`tb2-core7`, `tb2-sanitize`, `custom-x`)
- **profileset**: compact alias (`t-cg-cc`, `cc-only`, `t-vs-cc`)
- **variant**: only knobs you’re actually sweeping (`haiku45-low`, `sonnet45-med`, `hooks-v2`)

The *full* task list + profile settings live in TOML, so the slug doesn’t need to encode everything.

# New runner: `terminalbench.experiments`

## CLI

- Run:
  - `python -m terminalbench.experiments run experiments/<slug>.toml [--tasks ...] [--profiles ...] [--batch N] [--dry-run]`
- Kill (replacement for `kill-experiment.sh`):
  - `python -m terminalbench.experiments kill [--all] [--yes]`

### Kill behavior

- **Default (safer):** attempt to kill only “likely harbor/terminal-bench” docker containers (filtered by image/name heuristics) + local wrapper processes.
- `--all`: replicate current script behavior (kill **all** running docker containers + matching local processes).
- Require `--yes` for destructive actions.

# Results/batch logic

- Experiments runner sets `output_base = Path(results_root) / slug`.
- Uses existing `get_batch_dir(output_base, batch)`.
- We will patch `get_batch_dir()` to `mkdir(parents=True, exist_ok=True)` on the base **before** scanning, and create `{runs,analytics,artifacts}`.

# Generalize artifact mirroring

- Rename: `terminalbench/harbor/mirror_codecanvas.py` → `terminalbench/harbor/mirror_artifacts.py`.
- Add args:
  - `--targets codecanvas other_target ...`
  - (optional) `--dest-dirname artifacts` (defaults to `artifacts`)
- Copy rule:
  - From: `.../runs/<job>/<task_id>__*/agent/sessions/<target>/`
  - To: `.../<batch>/artifacts/<target>/<task_id>__*/`

HarborRunner changes:
- Replace `_mirror_codecanvas_artifacts()` with `_mirror_artifacts(targets=[...])`.
- Runner will pass experiment’s `[artifacts].targets` into HarborRunner so it can spawn the background mirrorer and/or do a final best-effort sync.

# MCP config modularization

## Proposed convention

- `codecanvas/.mcp.json` contains only the `codecanvas` server entry.
- `locagent/.mcp.json` contains only the `codegraph` server entry.
- Remove repo-root `.mcp.json`.

## How experiments assemble MCP config

- For a profile with `mcp_servers = ["codegraph", "codecanvas"]`, the runner:
  1) maps server → source dir via existing aliases (`codegraph` → `locagent`)
  2) loads each `<source_dir>/.mcp.json`
  3) merges them into one `{ "mcpServers": { ... } }`
  4) runs existing `adapt_mcp_config_for_harbor()`

This keeps configs modular while still satisfying Harbor’s “single mcp_config blob” requirement.

# Hooks standardization

- Standardize optional hooks file at server root: `<server_dir>/hooks.json`.
- Move `codecanvas/hooks/hooks.json` → `codecanvas/hooks.json`.
- Profiles reference that path explicitly in TOML.

# Env file location

- Yes, moving `terminalbench/.env` → `experiments/.env` is sensible for visibility.
- The runner will default to `experiments/.env` if the config doesn’t specify `env_file`.
- **No env file contents are ever printed or written into results snapshots** (only the path).

(Security note: env files contain API keys; we’ll treat them as local-only and untracked.)

# Rip out legacy pieces

After the new runner works end-to-end:

- Delete:
  - `terminalbench/ui/cli.py` (and possibly `terminalbench/ui/display.py` if unused)
  - `terminalbench/scripts/run-experiment.sh`
  - `terminalbench/scripts/kill-experiment.sh`
  - `tasks.yaml` (and `tasks.md` too if it actually exists; I assume you meant `tasks.yaml`)
- Remove/trim now-unused code:
  - `terminalbench/core/tasks.py` manifest loader + manifest config
  - `terminalbench/core/config.py` YAML user config (`TBConfig`, `run_setup`) if nothing else uses it (keep `get_batch_dir`, possibly relocated)

# Update AGENTS.md

Replace the current “test run 600s timeout” command with something like:

```bash
TERMINALBENCH_FORCE_REBUILD=1 uv run python -m terminalbench.experiments run experiments/<slug>.toml --tasks <task>
```

(Exact flags will match the new CLI once implemented.)

# Validation

After implementation (and after deletions), run:

- `uv run ty check codecanvas terminalbench`
- `uv run ruff check --fix codecanvas terminalbench`
- `uv run pytest`

# Confirmation

If you confirm this plan, I’ll implement all changes above, migrate the repo to the new experiment TOML workflow, and run validators.