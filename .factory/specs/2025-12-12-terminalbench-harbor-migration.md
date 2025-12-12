## Migration: tb CLI + Terminal-Bench 1.0 → Harbor + Terminal-Bench 2.0

### Summary of Changes

The migration involves updating the terminalbench harness to use the Harbor framework, which is the official successor to the tb CLI and supports Terminal-Bench 2.0.

### Key CLI Differences

| Old (tb) | New (harbor) |
|----------|-------------|
| `tb run --dataset X --task-id Y` | `harbor run -d dataset@version --task-ids Y` |
| `-k N` (attempts) | `--n-attempts N` |
| `--output-path` | `--jobs-dir` |
| N/A | `-n N` (parallel workers) |
| N/A | `--env docker\|daytona\|modal\|e2b` |

### Files to Modify

#### 1. `runner.py` - Core Changes
- Rename `tb_bin` → `harbor_bin` (default: `"harbor"`)
- Update `_build_command()`:
  ```python
  # Old: tb run --dataset terminal-bench-core==head --task-id foo -a claude-code -m model
  # New: harbor run -d terminal-bench@2.0 --task-ids foo -a claude-code -m model
  cmd = [self.harbor_bin, "run", "-d", task.dataset, "--task-ids", task.id]
  cmd.extend(["-a", profile.agent, "-m", profile.model])
  if self.attempts > 1:
      cmd.extend(["--n-attempts", str(self.attempts)])
  if output_dir:
      cmd.extend(["--jobs-dir", str(output_dir)])
  if self.parallel > 0:
      cmd.extend(["-n", str(self.parallel)])
  ```
- Update output parsing for ATIF trajectory format:
  - Harbor writes `trajectory.json` following ATIF spec
  - Results are in `jobs_dir/{timestamp}/results.json` with different schema
- Remove parallel logic from runner (Harbor handles it natively with `-n`)

#### 2. `tasks.py` - Dataset Format
- Change default dataset: `"terminal-bench-core==head"` → `"terminal-bench@2.0"`
- Update Task dataclass to match Harbor's task selection:
  ```python
  @dataclass(frozen=True)
  class Task:
      id: str
      dataset: str = "terminal-bench@2.0"  # Updated default
      order: int | None = None
  ```

#### 3. `tasks.yaml` - Update Dataset References
```yaml
tasks:
  - id: processing-pipeline
    dataset: terminal-bench@2.0  # Changed from terminal-bench-core==head
    order: 1
  # ... same for all tasks
```

#### 4. `agents.py` - MCP Integration
- Harbor's Claude Code agent doesn't natively support MCP servers via CLI flags
- Options:
  1. Use `--agent-import-path` with custom agent wrapper
  2. Pass MCP config via environment variables (if supported)
  3. Create a custom installed agent extending `BaseInstalledAgent`
- Update `tb_args()` → `harbor_args()`:
  ```python
  def harbor_args(self) -> List[str]:
      return ["-a", self.agent, "-m", self.model]
  ```

#### 5. `cli.py` - Flag Updates
- `--tb-bin` → `--harbor-bin`
- Remove `--parallel` (handled by `-n` in harbor command)
- Add `--env` option for container runtime selection
- Update config defaults

#### 6. `config.py` - Config Keys
- `tb_bin` → `harbor_bin`
- Add `container_env: str = "docker"` for runtime selection

### Output Structure Changes

**Old (tb):**
```
runs/
  {timestamp}__task/
    results.json
    {task_id}/
      {trial}/
        sessions/agent.log
```

**New (Harbor):**
```
jobs_dir/
  {job_id}/
    results.json  # Contains task_results with accuracy, reward
    trials/
      {task_id}/
        {attempt}/
          logs/agent/trajectory.json  # ATIF format
```

Update `_parse_results()` and `_find_agent_log()` to navigate new structure.

### ATIF Trajectory Parsing

Harbor outputs trajectories in ATIF format. Key fields:
```python
# trajectory.json structure
{
    "schema_version": "ATIF-v1.4",
    "session_id": "...",
    "agent": {"name": "claude-code", "version": "..."},
    "steps": [...],  # Contains tool_calls, observations, metrics
    "final_metrics": {
        "total_prompt_tokens": int,
        "total_completion_tokens": int,
        "total_cost_usd": float
    }
}
```

### MCP Server Support (Critical)

Harbor's built-in `claude-code` agent uses a fixed tool list:
```python
ALLOWED_TOOLS = ["Bash", "Edit", "Write", "Read", "Glob", "Grep", "LS", ...]
```

**To add MCP support, we need to create custom agents:**

Option A: Custom Installed Agent (Recommended)
```python
class ClaudeCodeWithMCP(BaseInstalledAgent):
    def __init__(self, mcp_servers: list[str] = None, ...):
        self.mcp_servers = mcp_servers or []
    
    def create_run_agent_commands(self, instruction: str) -> list[ExecInput]:
        env = {...}
        if self.mcp_servers:
            env["CLAUDE_CODE_MCP_SERVERS"] = ",".join(self.mcp_servers)
        # ... similar to harbor's claude_code.py
```

Option B: External Agent Wrapper
- Implement `BaseAgent` and manage Claude Code process externally

### Migration Steps

1. **Update dependencies**: Add `harbor` package, remove/replace `terminal-bench`
2. **Update runner.py**: New command building, output parsing
3. **Update tasks.yaml**: Change dataset to `terminal-bench@2.0`
4. **Update CLI flags**: Rename and add new options
5. **Create custom agents**: For MCP support (locagent, codecanvas)
6. **Test with oracle**: `harbor run -d terminal-bench@2.0 -a oracle`
7. **Test with claude-code**: Basic run without MCP
8. **Implement MCP agents**: Custom wrappers for locagent/codecanvas

### Questions Before Implementation (ANSWERED)

1. Should we keep backward compatibility with tb CLI via a `--legacy` flag?
 - NO! We will fully migrate to Harbor. Delete ALL old tb code after writing the 2.0 equivalents.
2. Do we want to register custom agents with Harbor or keep them local?
 - If Harbor registration would mean registering with their public registry, then NO. We want to keep our custom agents local only.
3. Should MCP agents be implemented as External or Installed agents?
 - MCP agents are just claude code with an mcp bolted on, that's it. Same goes for hooks. The harness itself is still Claude Code.