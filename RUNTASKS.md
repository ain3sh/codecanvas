# TerminalBench Runner

Run Terminal-Bench 2.0 with Claude Code, with or without MCP tools, using Harbor.

## Quick Start

```bash
# Install
uv pip install -e ".[terminalbench]"

# Baseline (no MCP)
python -m terminalbench.cli --tasks sanitize-git-repo --reasoning low \
  --model anthropic/claude-haiku-4-5

# Baseline vs MCP in one call (text + locagent)
python -m terminalbench.cli --tasks sanitize-git-repo --reasoning low \
  --model anthropic/claude-haiku-4-5 --profiles-parallel 2 \
  --config-set --no-mcp --key text \
  --config-set --mcp-server locagent --mcp-git-source https://github.com/ain3sh/codecanvas --key loc
```

## Installation

**Prerequisites:**
- Python 3.10+
- Docker (or alternative: daytona, modal, e2b)
- `ANTHROPIC_API_KEY` in `terminalbench/.env`

```bash
# Install terminalbench
uv pip install -e ".[terminalbench]"

# Harbor is auto-installed via uvx on first run
```

**Build reuse:** environments are kept (`--no-delete`) to avoid rebuild spikes. The harness auto-rebuilds when the install template or MCP git source changes; set `TERMINALBENCH_FORCE_REBUILD=1` to force a fresh build once.

## Basic Usage

### Run All Tasks
```bash
python -m terminalbench.cli
```

### Run Specific Tasks
```bash
python -m terminalbench.cli --tasks sanitize-git-repo build-cython-ext
```

### Model Selection
Use API IDs (examples): `anthropic/claude-haiku-4-5`, `anthropic/claude-sonnet-4-5`, `anthropic/claude-opus-4-5`.

Reasoning levels: `low`, `medium`, `high`.

## MCP Integration

MCP (Model Context Protocol) servers provide Claude with additional tools. The harness supports:
1. Loading MCP config from `.mcp.json`
2. Selectively enabling servers
3. Installing MCP servers in Harbor containers

### MCP Configuration

MCP servers are defined in `.mcp.json` (Claude Code standard format):

```json
{
  "mcpServers": {
    "locagent": {
      "command": "uv",
      "args": ["run", "python", "-m", "locagent.server"],
      "env": {"PYTHONUNBUFFERED": "1"}
    }
  }
}
```

### Enable MCP Servers

```bash
# List available servers
python -m terminalbench.cli --list-mcp-servers

# Enable specific server(s)
python -m terminalbench.cli --mcp-server locagent --tasks sanitize-git-repo

# Enable multiple servers
python -m terminalbench.cli --mcp-server locagent --mcp-server another

# Disable all MCP (baseline run)
python -m terminalbench.cli --no-mcp --tasks sanitize-git-repo
```

### Install MCP in Container

For Harbor runs, MCP servers must be installed in the container:

```bash
python -m terminalbench.cli \
  --mcp-server locagent \
  --mcp-git-source https://github.com/ain3sh/codecanvas \
  --tasks sanitize-git-repo
```

If you skip `--mcp-git-source`, the MCP server will fail to start and trajectories may not parse.

For private repos, set `GITHUB_TOKEN` in `terminalbench/.env` or use `--github-token`.

### System Prompts (USAGE.md)

The harness auto-discovers `<server_name>/USAGE.md` files and appends them to Claude's system prompt. Create `locagent/USAGE.md` with tool usage instructions.

## Configuration

### Persistent Config

```bash
python -m terminalbench.cli setup
```

Saves to `~/.terminalbench/config.yaml`. CLI flags override saved config.

### Environment Variables

Create `terminalbench/.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...  # Optional: for private MCP repos
```

### Manifest (tasks.yaml)

```yaml
env_file: terminalbench/.env
mcp_config: .mcp.json

tasks:
  - id: sanitize-git-repo
    dataset: terminal-bench@2.0
    order: 1
```

## CLI Reference

### Task Selection
| Flag | Description |
|------|-------------|
| `--tasks ID [ID ...]` | Run specific tasks |
| `--manifest FILE` | Custom manifest file |

### Model Configuration
| Flag | Description | Default |
|------|-------------|---------|
| `--model`, `-m` | Model name | `anthropic/claude-sonnet-4-20250514` |
| `--reasoning` | Thinking level (low/medium/high) | `medium` |

### MCP Configuration
| Flag | Description |
|------|-------------|
| `--mcp-config FILE` | Path to .mcp.json |
| `--mcp-server NAME` | Enable specific server (repeatable) |
| `--no-mcp` | Disable all MCP servers |
| `--list-mcp-servers` | List available servers and exit |
| `--mcp-git-source URL` | Git URL to install MCP from |
| `--github-token TOKEN` | GitHub token for private repos |

### Hooks Configuration
| Flag | Description |
|------|-------------|
| `--hooks FILE` | Claude Code hooks settings file |

### Execution Options
| Flag | Description | Default |
|------|-------------|---------|
| `--output-dir DIR` | Output directory | `./runs` |
| `--attempts N` | Attempts per task | `1` |
| `--retries N` | Retries on failure | `0` |
| `--parallel`, `-n` | Parallel workers | `0` |
| `--container-env` | Runtime (docker/daytona/modal/e2b) | `docker` |
| `--dry-run` | Print commands without executing | |
| `--quiet` | Suppress output | |
| `--env-file FILE` | Load env vars from file | `terminalbench/.env` |
| `--profiles-parallel N` | Parallelize multiple config-sets | `0` |
| `--config-set ...` | Define an additional agent config (repeatable) | |

### Output Options
| Flag | Description |
|------|-------------|
| `--json` | Emit results as JSON |
| `--csv FILE` | Export to CSV |

### Advanced
| Flag | Description |
|------|-------------|
| `--harbor-bin PATH` | Custom harbor binary |
| `--extra-flag FLAG` | Extra harbor flag (repeatable) |

## Output Structure

```
runs/
├── index.json                              # Run index
└── {timestamp}/
    ├── config.json                         # Job configuration
    ├── result.json                         # Aggregate results
    └── {task_id}__{hash}/
        └── agent/
            ├── trajectory.json             # Agent trace (ATIF format)
            ├── claude-code.txt             # Raw Claude output
            └── sessions/                   # Claude Code session logs
```

## Common Workflows

### Baseline vs MCP Comparison

```bash
# Baseline (no MCP)
python -m terminalbench.cli --no-mcp --tasks sanitize-git-repo --csv baseline.csv

# With MCP
python -m terminalbench.cli --mcp-server locagent \
  --mcp-git-source https://github.com/ain3sh/codecanvas \
  --tasks sanitize-git-repo --csv mcp.csv

# Both in one command (parallel profiles)
python -m terminalbench.cli --tasks sanitize-git-repo --reasoning low \
  --model anthropic/claude-haiku-4-5 --profiles-parallel 2 \
  --config-set --no-mcp --key text \
  --config-set --mcp-server locagent --mcp-git-source https://github.com/ain3sh/codecanvas --key loc
```

### Full Benchmark

```bash
python -m terminalbench.cli \
  --mcp-server locagent \
  --mcp-git-source https://github.com/ain3sh/codecanvas \
  --parallel 4 \
  --csv results.csv
```

### Dry Run

```bash
python -m terminalbench.cli --dry-run --tasks sanitize-git-repo
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ANTHROPIC_API_KEY is required` | Add to `terminalbench/.env` |
| `uvx not found` | Install uv: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| MCP permission errors | Ensure `--mcp-server` matches server name in `.mcp.json` |
| Git clone fails in container | Set `GITHUB_TOKEN` in `.env` and pass `--mcp-git-source` |
| Docker errors | Ensure Docker daemon is running |
| OOM errors | Task may read large files; try `--container-env modal` |
| CRLF errors in .env | Run `dos2unix terminalbench/.env` |

## Available Tasks

| Task ID | Description |
|---------|-------------|
| `sanitize-git-repo` | Remove API keys from repository |
| `build-cython-ext` | Build Cython extension |
| `custom-memory-heap-crash` | Debug memory issue |
| `db-wal-recovery` | Database recovery |
| `modernize-scientific-stack` | Update dependencies |
| `rstan-to-pystan` | R to Python migration |
| `fix-code-vulnerability` | Security fix |

See `tasks.yaml` for full task list.
