# TerminalBench Runner

Run Terminal-Bench 2.0 tasks via Harbor framework with different agent configurations.

## Quick Start

```bash
# Prerequisites (harbor auto-installed via uvx on first run)
uv pip install -e ".[terminalbench]"

# Run single task with text-only agent (uses terminalbench/.env by default)
python -m terminalbench.cli --agent text --tasks processing-pipeline

# Run all tasks with all agents
python -m terminalbench.cli
```

## CLI Reference

### Agent Selection
```bash
--agent {text,locagent,codecanvas,all}   # default: all
```

### Task Selection
```bash
--tasks processing-pipeline sanitize-git-repo   # specific tasks
--manifest custom.yaml                          # custom manifest file
```

### Execution Options
```bash
--env-file .env          # load ANTHROPIC_API_KEY from file
--output-dir ./runs      # output directory (default: ./runs)
--attempts 3             # retry attempts per task (--n-attempts to harbor)
--retries 2              # retry on failure
--parallel 4             # parallel workers (passed to harbor -n)
--container-env docker   # container runtime (docker|daytona|modal|e2b)
--harbor-bin /path/to/harbor  # custom harbor binary (default: uses uvx)
--extra-flag --verbose   # extra flags passed to harbor run (repeatable)
--dry-run                # print commands without executing
--quiet                  # suppress summary output
```

### MCP Configuration
```bash
--locagent-mcp "http://localhost:8000"   # LocAgent MCP server
--canvas-mcp "http://localhost:8001"     # CodeCanvas MCP server
--hooks ./hooks.json                      # Claude Code hooks file
```

### Output Options
```bash
--json                   # emit results as JSON
--csv results.csv        # export to CSV file
```

## Configuration

### Persistent Config
```bash
python -m terminalbench.cli setup
```

Saves to `~/.terminalbench/config.yaml`. CLI args override saved config.

### Environment Variables
| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Required for Harbor runs |
| `LOCAGENT_MCP` | Default LocAgent MCP URL |
| `CODECANVAS_MCP` | Default CodeCanvas MCP URL |
| `CLAUDE_CODE_HOOKS` | Default hooks file path |

## tasks.yaml Format

```yaml
env_file: terminalbench/.env     # optional: path to .env file (default: terminalbench/.env)

tasks:
  - id: processing-pipeline      # required: task identifier
    dataset: terminal-bench@2.0  # optional: dataset (default shown)
    order: 1                     # optional: execution order (lower = first)
    tb_url: https://tbench.ai/tasks/processing-pipeline  # ignored (human reference)
    gh_url: https://github.com/...                       # ignored (human reference)

  - id: custom-task
    dataset: my-dataset@1.0
    order: 10
```

**Note:** Extra fields like `tb_url` and `gh_url` are ignored during parsing - use them for human reference.

**env_file resolution order:** CLI `--env-file` > manifest `env_file` > `terminalbench/.env` (if exists)

**Default tasks:** processing-pipeline, sanitize-git-repo, swe-bench-fsspec, deterministic-tarball, tree-directory-parser, c-to-safe-rust, reverse-engineering

## Output Structure

```
runs/
├── index.json                              # auto-maintained run index
└── {timestamp}/                            # Harbor job directory
    ├── config.json                         # job configuration
    ├── result.json                         # aggregate results with metrics
    └── {task_id}__{hash}/                  # trial directory
        └── agent/
            ├── trajectory.json             # agent trace
            └── sessions/                   # claude code session logs
```

### index.json
```json
{
  "runs": [
    {
      "task_id": "build-cython-ext",
      "agent_key": "text",
      "success": true,
      "accuracy": 0.0,
      "resolved": false,
      "elapsed_sec": 485.7,
      "job_dir": "runs/2025-12-12__02-23-38",
      "results_json": "runs/.../result.json",
      "trajectory_json": "runs/.../agent/trajectory.json"
    }
  ]
}
```

## Common Workflows

### Benchmark all agents on one task
```bash
python -m terminalbench.cli --tasks processing-pipeline --env-file .env
```

### Compare two agents
```bash
python -m terminalbench.cli --agent text --env-file .env --csv text.csv
python -m terminalbench.cli --agent locagent --locagent-mcp http://localhost:8000 --env-file .env --csv locagent.csv
```

### Full benchmark with parallel execution
```bash
python -m terminalbench.cli --parallel 4 --env-file .env --csv full_results.csv
```

### Dry run to verify commands
```bash
python -m terminalbench.cli --dry-run
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ANTHROPIC_API_KEY is required` | Use `--env-file` or export the key |
| CRLF errors in .env | Run `dos2unix .env` |
| `uvx` not found | Install uv: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Modal Python 3.14+ error | Expected - harbor runs in isolated Python 3.13 via uvx |
| Docker errors | Ensure Docker daemon is running with sufficient resources |
| Container env issues | Try `--container-env daytona` or `--container-env modal` |
