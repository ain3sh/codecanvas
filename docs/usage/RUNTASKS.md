# TerminalBench Runner

Run Terminal-Bench 2.0 with Claude Code, with or without MCP tools, using Harbor.

## Quick Start

```bash
# Install
uv pip install -e ".[terminalbench]"

# Baseline (no MCP)
python -m terminalbench.ui.cli --tasks sanitize-git-repo --reasoning medium \
  --model anthropic/claude-sonnet-4-5

# Baseline vs MCP in one call (text + codegraph)
python -m terminalbench.ui.cli --tasks sanitize-git-repo --reasoning medium \
  --model anthropic/claude-sonnet-4-5 --profiles-parallel 2 \
  -C --no-mcp --key text \
  -C --mcp-server codegraph --mcp-git-source https://github.com/ain3sh/codecanvas --key loc
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
python -m terminalbench.ui.cli
```

### Run Specific Tasks
```bash
python -m terminalbench.ui.cli --tasks sanitize-git-repo build-cython-ext
```

### Model Selection
Use API IDs (examples): `anthropic/claude-sonnet-4-5`, `anthropic/claude-opus-4-5`.

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
    "codegraph": {
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
python -m terminalbench.ui.cli --list-mcp-servers

# Enable specific server(s)
python -m terminalbench.ui.cli --mcp-server codegraph --tasks sanitize-git-repo

# Enable multiple servers
python -m terminalbench.ui.cli --mcp-server codegraph --mcp-server another

# Disable all MCP (baseline run)
python -m terminalbench.ui.cli --no-mcp --tasks sanitize-git-repo
```

### Install MCP in Container

For Harbor runs, MCP servers must be installed in the container:

```bash
python -m terminalbench.ui.cli \
  --mcp-server codegraph \
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
python -m terminalbench.ui.cli setup
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
| `--claude-version` | Claude Code version to install (optional) | latest |

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
| `--output-dir DIR` | Base results directory | `./results` |
| `--batch N` | Batch ID (default: auto-increment) | auto |
| `--attempts N` | Attempts per task | `1` |
| `--retries N` | Retries on failure | `0` |
| `--registry-path FILE` | Local registry.json (workaround for broken remote) | remote |
| `--parallel`, `-n` | Parallel workers | `0` |
| `--container-env` | Runtime (docker/daytona/modal/e2b) | `docker` |
| `--dry-run` | Print commands without executing | |
| `--quiet` | Suppress output | |
| `--env-file FILE` | Load env vars from file | `terminalbench/.env` |
| `--profiles-parallel N` | Parallelize multiple config-sets | `0` |
| `--config-set`, `-C` | Define an agent config (repeatable); supports `--key`, `--model`, `--reasoning`, `--claude-version`, `--mcp-server`, `--no-mcp`, `--hooks`, `--mcp-config`, `--mcp-git-source`, `--github-token`. Auto-generates key as `nomcp`/`server1-server2`/`profileN` if omitted | |

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

Results are organized by batch (auto-incrementing ID):

```
results/
├── 0/                                      # Batch 0
│   ├── runs/
│   │   ├── index.json                      # Run index
│   │   └── {timestamp}__{profile_key}/     # Unique per profile
│   │       ├── config.json                 # Job configuration
│   │       ├── result.json                 # Aggregate results
│   │       └── {task_id}__{hash}/
│   │           └── agent/
│   │               ├── trajectory.json     # Agent trace (ATIF format)
│   │               ├── claude-code.txt     # Raw Claude output
│   │               └── sessions/           # Claude Code session logs
│   ├── analytics/                          # Analytics outputs
│   ├── canvas/                             # CodeCanvas state copies
│   └── experiment_*.log                    # Experiment log
├── 1/                                      # Batch 1
└── 2/                                      # Batch 2 (etc.)
```

When running multiple profiles in parallel (`--profiles-parallel`), each profile gets its own timestamped directory with the profile key appended (e.g., `2025-12-21__14-30-00__text`, `2025-12-21__14-30-00__codegraph`).

Use `--batch N` to target a specific batch, or omit to auto-create the next batch.

## Common Workflows

### Baseline vs MCP Comparison

```bash
# Baseline (no MCP)
python -m terminalbench.ui.cli --no-mcp --tasks sanitize-git-repo --csv baseline.csv

# With MCP
python -m terminalbench.ui.cli --mcp-server codegraph \
  --mcp-git-source https://github.com/ain3sh/codecanvas \
  --tasks sanitize-git-repo --csv mcp.csv

# Both in one command (parallel profiles, -C is shorthand for --config-set)
python -m terminalbench.ui.cli --tasks sanitize-git-repo --reasoning medium \
  --model anthropic/claude-sonnet-4-5 --profiles-parallel 2 \
  -C --no-mcp --key text \
  -C --mcp-server codegraph --mcp-git-source https://github.com/ain3sh/codecanvas --key loc
```

### Full Benchmark (Single Profile)

```bash
python -m terminalbench.ui.cli \
  --mcp-server codegraph \
  --mcp-git-source https://github.com/ain3sh/codecanvas \
  --parallel 4 \
  --csv results.csv
```

### Full Experiment Suite (3 Profiles x 7 Tasks)

Run all tasks with text-only baseline, codegraph MCP, and codecanvas MCP profiles:

```bash
# Use the experiment runner script
./terminalbench/scripts/run-experiment.sh

# Or manually per task:
python -m terminalbench.ui.cli \
  --manifest tasks.yaml \
  --tasks sanitize-git-repo \
  --model anthropic/claude-sonnet-4-5 \
  --reasoning medium \
  --profiles-parallel 3 \
  -C --no-mcp --key text \
  -C --mcp-server codegraph --mcp-git-source https://github.com/ain3sh/codecanvas --key codegraph \
  -C --mcp-server codecanvas --mcp-git-source https://github.com/ain3sh/codecanvas --key codecanvas
```

See `terminalbench/scripts/run-experiment.sh` for the complete automation script.

### Dry Run

```bash
python -m terminalbench.ui.cli --dry-run --tasks sanitize-git-repo
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
