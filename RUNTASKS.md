# TerminalBench Runner

Run Terminal-Bench tasks with different agent configurations for benchmarking.

## Quick Start

```bash
# Prerequisites
pip install terminal-bench pyyaml rich

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
--attempts 3             # retry attempts per task (-k flag to tb)
--retries 2              # retry on failure
--parallel 4             # run N tasks concurrently
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
| `ANTHROPIC_API_KEY` | Required for tb runs |
| `LOCAGENT_MCP` | Default LocAgent MCP URL |
| `CODECANVAS_MCP` | Default CodeCanvas MCP URL |
| `CLAUDE_CODE_HOOKS` | Default hooks file path |

## tasks.yaml Format

```yaml
env_file: terminalbench/.env     # optional: path to .env file (default: terminalbench/.env)

tasks:
  - id: processing-pipeline      # required: task identifier
    dataset: terminal-bench-core==head  # optional: dataset (default shown)
    order: 1                     # optional: execution order (lower = first)

  - id: custom-task
    dataset: my-dataset@1.0
    order: 10
```

**env_file resolution order:** CLI `--env-file` > manifest `env_file` > `terminalbench/.env` (if exists)

**Default tasks:** processing-pipeline, sanitize-git-repo, swe-bench-fsspec, deterministic-tarball, tree-directory-parser, c-to-safe-rust, reverse-engineering

## Output Structure

```
runs/
├── index.json                              # auto-maintained run index
└── 2025-12-11__22-25-21/                   # tb-created timestamp dir
    ├── results.json                        # aggregate results
    ├── run.log                             # orchestrator log
    └── processing-pipeline/
        └── processing-pipeline.1-of-1.../
            └── sessions/
                ├── agent.log               # agent reasoning trace
                ├── agent.cast              # terminal replay
                └── tests.log               # verifier output
```

### index.json
```json
{
  "runs": [
    {
      "task_id": "processing-pipeline",
      "agent_key": "text",
      "success": true,
      "accuracy": 1.0,
      "elapsed_sec": 68.5,
      "timestamp_dir": "runs/2025-12-11__22-25-21",
      "agent_log": "runs/.../sessions/agent.log"
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
| `tb` not found | `pip install terminal-bench` or use full path |
| Docker errors | Ensure Docker daemon is running with sufficient resources |
