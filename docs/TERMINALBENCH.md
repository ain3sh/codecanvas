# TerminalBench Harness

A custom evaluation harness wrapping Terminal-Bench 2.0, Harbor, and Claude Code for running LLM agent benchmarks with optional MCP server integration.

## Overview

This harness enables systematic evaluation of Claude Code on Terminal-Bench 2.0 tasks, with first-class support for comparing baseline (text-only) runs against MCP-augmented runs. The implementation leverages Harbor's containerized execution model while extending it with custom agent configuration, MCP installation, and multi-profile parallel execution.

```
┌─────────────────────────────────────────────────────────────────┐
│  terminalbench/ui/cli.py                                        │
│  CLI entrypoint, argument parsing, multi-profile dispatch       │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│  terminalbench/harbor/runner.py                                 │
│  HarborRunner: orchestrates harbor subprocess, build caching    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│  terminalbench/harbor/agent.py                                  │
│  ClaudeCodeMCP: custom Harbor agent with MCP installation       │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│  Harbor Framework                                               │
│  Container orchestration, task execution, trajectory capture    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│  Claude Code (headless)                                         │
│  Anthropic's CLI agent, MCP support, extended thinking          │
└─────────────────────────────────────────────────────────────────┘
```

## Terminal-Bench 2.0

Terminal-Bench is a benchmark for evaluating LLM agents on complex terminal tasks. Version 2.0 (November 2025) provides:

**Task Characteristics:**
- 89+ validated tasks spanning system administration, security, build systems, database recovery, and file operations
- Real-world complexity: compiling Linux kernels, configuring Git web servers, cracking 7z hashes, TLS certificate generation
- Containerized execution ensures reproducibility across runs
- Binary reward signal (0/1) based on automated verification scripts

**Evaluation Model:**
- Agent receives task description and terminal access
- Agent issues shell commands, observes output, iterates
- Verifier runs post-execution tests to determine success
- Top agents achieve ~50% success rate, indicating genuine difficulty

**Dataset Versioning:**
- `terminal-bench@2.0`: Stable release
- `terminal-bench-core==head`: Pre-release with latest tasks
- Tasks registered in central registry at tbench.ai

## Harbor Framework

Harbor is the execution framework developed alongside Terminal-Bench 2.0. It abstracts container orchestration, agent interfaces, and result collection.

**Core Abstractions:**
- **Environment**: Containerized sandbox (Docker, Daytona, Modal, E2B)
- **Agent**: Interface for LLM-powered task execution (`BaseAgent`, `AbstractInstalledAgent`)
- **Task**: Specification with prompt, setup scripts, verification
- **Trajectory**: ATIF-format trace of agent actions

**Pre-integrated Agents:**
- `terminus`: Native Harbor agent using LiteLLM
- `claude-code`: Anthropic's Claude Code CLI
- `aider`: Aider coding assistant
- Custom agents via `--agent-import-path`

**Key Features:**
- Automatic environment caching (avoids rebuild churn)
- Parallel task execution across workers
- Cloud provider integration for horizontal scaling
- ATIF trajectory output for analysis pipelines

**CLI Usage (native Harbor):**
```bash
tb run --dataset terminal-bench-core==head --agent claude-code --model anthropic/claude-sonnet-4-20250514 --task-id hello-world
```

## Claude Code

Claude Code is Anthropic's CLI agent for software engineering tasks. In headless mode, it executes autonomously without human interaction.

**Execution Modes:**
- **Interactive**: TUI for human collaboration
- **Headless**: Programmatic execution via `claude -p "prompt" --dangerously-skip-permissions`
- **SDK**: Python/TypeScript bindings for orchestration

**MCP (Model Context Protocol):**
- Extends Claude with external tools via JSON-RPC servers
- Configured via `.mcp.json` in working directory
- Servers provide tools (functions), resources (data), and prompts (templates)
- Claude auto-discovers and invokes MCP tools during reasoning

**Permission Model:**
- `--dangerously-skip-permissions`: Approve all tool calls (required for benchmarking)
- `--allowedTools`: Whitelist specific tools including `mcp__<server>` patterns
- Hooks can intercept tool calls for validation

**Extended Thinking:**
- `--reasoning low|medium|high`: Controls thinking budget
- Higher reasoning improves complex task performance at token cost

## Harness Architecture

### Module Structure

```
terminalbench/
├── __init__.py
├── core/
│   ├── config.py      # TBConfig dataclass, persistent config
│   ├── profiles.py    # AgentProfile: model, reasoning, MCP settings
│   └── tasks.py       # Task loading from manifest (tasks.yaml)
├── harbor/
│   ├── runner.py      # HarborRunner: subprocess orchestration
│   ├── agent.py       # ClaudeCodeMCP: custom agent class
│   └── install-claude-code-utils.sh.j2  # Container setup template
├── ui/
│   ├── cli.py         # argparse CLI with config-set support
│   └── display.py     # Output formatting
└── analytics/         # Post-run analysis (see RUNANALYTICS.md)
```

### ClaudeCodeMCP Agent

Extends Harbor's `ClaudeCode` agent to support MCP server installation and configuration:

```python
class ClaudeCodeMCP(ClaudeCode):
    def __init__(self, mcp_git_source, mcp_servers, mcp_config, ...):
        # Clone MCP repo into container
        # Install via pip
        # Configure .mcp.json
        # Auto-approve mcp__* tools
```

**Install Template** (`install-claude-code-utils.sh.j2`):
1. Install Node.js (via fnm) and Claude Code CLI
2. Install uv for Python package management
3. Clone MCP source repository (with optional GitHub token)
4. `pip install -e .` the MCP package
5. Write adapted `.mcp.json` to container

**MCP Config Adaptation:**
- Converts `uv run python -m` to `python3 -m` for container compatibility
- Discovers `<server>/USAGE.md` and appends to system prompt

### HarborRunner

Orchestrates Harbor subprocess calls with caching and fingerprinting:

```python
class HarborRunner:
    def compute_build_fingerprint(self) -> str:
        # SHA256 of (install_template + mcp_git_source)
        # Used to detect when rebuild is needed
    
    def run_task(self, task, profile) -> dict:
        # Invoke: harbor run --agent <custom> --task <id> ...
        # Capture trajectory.json, result.json, verifier output
```

**Environment Reuse Strategy:**
- `--no-delete` keeps containers across runs
- Fingerprint change triggers rebuild
- `TERMINALBENCH_FORCE_REBUILD=1` forces fresh build

### Multi-Profile Execution

The `--config-set` / `-C` flag enables comparative runs in a single invocation:

```bash
python -m terminalbench.ui.cli --tasks sanitize-git-repo \
  -C --no-mcp --key text \
  -C --mcp-server codegraph --mcp-git-source https://github.com/ain3sh/codecanvas --key loc
```

**Behavior:**
- Each `-C` defines an `AgentProfile` with distinct settings
- Profiles execute in parallel if `--profiles-parallel N` specified
- Results tagged by `--key` for downstream analysis
- Auto-generates key as `nomcp`/`server1-server2` if omitted

## Trajectory Format (ATIF)

Harbor outputs trajectories in Agent Trajectory Interchange Format (ATIF v1.2+):

```json
{
  "metadata": {
    "agent": "claude-code",
    "model": "anthropic/claude-sonnet-4-20250514",
    "task_id": "sanitize-git-repo"
  },
  "steps": [
    {
      "index": 0,
      "source": "agent",
      "action": {
        "type": "tool_call",
        "tool": "Bash",
        "input": {"command": "git log --oneline"}
      },
      "observation": "abc123 Initial commit\n...",
      "tokens": {"input": 1234, "output": 567}
    }
  ],
  "result": {
    "success": true,
    "reward": 1.0
  }
}
```

**Key Fields:**
- `steps[].source`: "agent" (model turn) or "environment" (tool output)
- `steps[].action.type`: "tool_call", "text", "error"
- `steps[].tokens`: Per-step token accounting
- `result.reward`: Binary success from verifier

## Configuration

### Task Manifest (tasks.yaml)

```yaml
env_file: terminalbench/.env
mcp_config: .mcp.json

tasks:
  - id: sanitize-git-repo
    dataset: terminal-bench@2.0
    order: 1
  - id: build-cython-ext
    dataset: terminal-bench@2.0
    order: 2
```

### MCP Configuration (.mcp.json)

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

### Environment Variables (terminalbench/.env)

```bash
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...  # For private MCP repos
```

## Output Structure

```
results/
├── 0/                                      # Batch 0
│   ├── runs/
│   │   ├── index.json                      # Run index
│   │   └── {timestamp}__{profile_key}/     # Unique per profile
│   │       ├── config.json                 # Job configuration
│   │       ├── result.json                 # Aggregate results
│   │       └── {task_id}__{hash}/
│   │           ├── agent/
│   │           │   ├── trajectory.json     # ATIF trace
│   │           │   ├── claude-code.txt     # Raw Claude output
│   │           │   └── sessions/           # Claude Code session logs
│   │           │       └── codecanvas/     # CodeCanvas artifacts (if used)
│   │           └── verifier/
│   │               ├── ctrf.json           # Test results
│   │               └── reward.txt          # Binary reward
│   ├── canvas/                             # Mirror of agent/sessions/codecanvas (per trial)
│   │   └── {task_id}__{hash}/              # Contains state.json + *.png
│   └── analytics/                          # Post-run analysis outputs
└── 1/                                      # Batch 1
```

If a run produces CodeCanvas artifacts under `agent/sessions/codecanvas/`, the harness mirrors them into `results/<batch>/canvas/<task_id>__<hash>/` for convenient browsing.

## Design Decisions

### Why Custom Harbor Agent?

Harbor's built-in `ClaudeCode` agent doesn't support:
1. MCP server installation from external git sources
2. Dynamic MCP configuration at runtime
3. System prompt augmentation from USAGE.md files

`ClaudeCodeMCP` addresses these by injecting install steps and config generation into the container setup phase.

### Why Build Fingerprinting?

Container builds are slow (~30-60s). Fingerprinting the install template and MCP git source allows:
- Skipping rebuilds when config unchanged
- Forcing rebuild when MCP code updated (`TERMINALBENCH_FORCE_REBUILD=1`)
- Sharing builds across compatible profiles

### Why Multi-Profile in One Run?

Comparative evaluation requires controlled conditions:
- Same timestamp for paired runs
- Parallel execution reduces wall-clock time
- Unified result structure simplifies analytics

## Limitations

- **Claude Code specific**: Agent class assumes Claude Code; other agents need separate implementation
- **Single MCP source**: Only one git repository can be installed per profile
- **No streaming**: Results collected post-execution, no live progress

## References

- Terminal-Bench: https://tbench.ai
- Harbor Framework: https://harborframework.com
- Claude Code: https://code.claude.com/docs
- ATIF Specification: https://harborframework.com/docs/trajectory-format
- MCP Protocol: https://modelcontextprotocol.io
