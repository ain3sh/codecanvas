"""Custom Claude Code agent with MCP and hooks support for Harbor."""
from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any

from harbor.agents.installed.base import ExecInput
from harbor.agents.installed.claude_code import ClaudeCode
from harbor.models.trial.paths import EnvironmentPaths


def _ensure_json_string(value: Any) -> str | None:
    """Convert value to JSON string if it's a dict/list, or return as-is if string."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


class ClaudeCodeMCP(ClaudeCode):
    """Claude Code agent with MCP server and hooks support.
    
    This agent extends ClaudeCode to:
    1. Install MCP servers in the container from a git source
    2. Pass MCP config and hooks to the Claude CLI
    3. Optionally append a system prompt to guide tool usage
    
    Installation options (via kwargs):
    - mcp_git_source: Git URL to clone (e.g., "https://github.com/user/codecanvas")
                      Assumes 'main' branch.
    
    Note: Harbor's kwarg parser converts JSON strings to dicts, so we handle both.
    """

    def __init__(
        self,
        mcp_config: str | dict | None = None,
        hooks_config: str | dict | None = None,
        reasoning: str = "medium",
        claude_version: str | None = None,
        mcp_git_source: str | None = None,
        github_token: str | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        # Harbor's kwarg parser converts JSON to dicts, so convert back to string
        self.mcp_config = _ensure_json_string(mcp_config)
        self.hooks_config = _ensure_json_string(hooks_config)
        self.reasoning = reasoning
        self.claude_version = claude_version
        self.mcp_git_source = mcp_git_source
        # GitHub token for private repos - from kwarg or env var
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN")
        self.system_prompt = system_prompt

    @staticmethod
    def name() -> str:
        return "claude-code-mcp"

    @property
    def _install_agent_template_path(self) -> Path:
        """Path to the custom install template with MCP support."""
        return Path(__file__).parent / "install-claude-code-mcp.sh.j2"

    @property
    def _template_variables(self) -> dict[str, str | None]:
        """Variables to pass to the install template."""
        return {
            "claude_version": self.claude_version or self._version,
            "mcp_git_source": self.mcp_git_source,
            "github_token": self.github_token,
        }

    def create_run_agent_commands(self, instruction: str) -> list[ExecInput]:
        escaped_instruction = shlex.quote(instruction)

        env = {
            "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
            "CLAUDE_CODE_OAUTH_TOKEN": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", ""),
            "FORCE_AUTO_BACKGROUND_TASKS": "1",
            "ENABLE_BACKGROUND_TASKS": "1",
        }
        env = {k: v for k, v in env.items() if v}

        if self.model_name:
            env["ANTHROPIC_MODEL"] = self.model_name.split("/")[-1]
        elif "ANTHROPIC_MODEL" in os.environ:
            env["ANTHROPIC_MODEL"] = os.environ["ANTHROPIC_MODEL"]

        if "MAX_THINKING_TOKENS" in os.environ:
            env["MAX_THINKING_TOKENS"] = os.environ["MAX_THINKING_TOKENS"]

        env["CLAUDE_CONFIG_DIR"] = (EnvironmentPaths.agent_dir / "sessions").as_posix()

        # Setup commands to run before main command
        setup_cmds = [
            ExecInput(
                command=(
                    "mkdir -p $CLAUDE_CONFIG_DIR/debug $CLAUDE_CONFIG_DIR/projects/-app "
                    "$CLAUDE_CONFIG_DIR/shell-snapshots $CLAUDE_CONFIG_DIR/statsig "
                    "$CLAUDE_CONFIG_DIR/todos"
                ),
                env=env,
            ),
        ]

        # Build the claude command parts
        cmd_parts = [
            "claude",
            "--verbose",
            "--output-format", "stream-json",
            "-p", escaped_instruction,
            "--allowedTools",
        ]
        cmd_parts.extend(self.ALLOWED_TOOLS)

        # Write MCP config to file if provided
        if self.mcp_config:
            mcp_file = "/tmp/mcp-config.json"
            escaped_mcp = shlex.quote(self.mcp_config)
            setup_cmds.append(
                ExecInput(
                    command=f"echo {escaped_mcp} > {mcp_file}",
                    env=env,
                )
            )
            cmd_parts.extend(["--mcp-config", mcp_file])

        # Write hooks config to file if provided
        if self.hooks_config:
            hooks_file = "/tmp/hooks-settings.json"
            escaped_hooks = shlex.quote(self.hooks_config)
            setup_cmds.append(
                ExecInput(
                    command=f"echo {escaped_hooks} > {hooks_file}",
                    env=env,
                )
            )
            cmd_parts.extend(["--settings", hooks_file])

        # Add system prompt if provided (pass content directly, not file path)
        if self.system_prompt:
            escaped_prompt = shlex.quote(self.system_prompt)
            cmd_parts.extend(["--append-system-prompt", escaped_prompt])

        # Build final command string
        cmd = " ".join(cmd_parts) + " 2>&1 </dev/null | tee /logs/agent/claude-code.txt"

        return setup_cmds + [ExecInput(command=cmd, env=env)]
