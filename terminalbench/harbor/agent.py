"""Custom Claude Code agent with MCP and hooks support for Harbor."""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any

from harbor.agents.installed.base import ExecInput
from harbor.agents.installed.claude_code import ClaudeCode
from harbor.environments.base import BaseEnvironment
from harbor.models.trial.paths import EnvironmentPaths
from jinja2 import Environment


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
        mcp_extras: str | None = None,
        install_r_languageserver: bool = False,
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
        self.mcp_extras = mcp_extras
        self.install_r_languageserver = install_r_languageserver
        self.system_prompt = system_prompt

    @staticmethod
    def name() -> str:
        return "claude-code-mcp"

    @property
    def _install_agent_template_path(self) -> Path:
        """Path to the custom install template with MCP support."""
        return Path(__file__).parent / "install-claude-code-utils.sh.j2"

    @property
    def _template_variables(self) -> dict[str, str | bool | None]:
        """Variables to pass to the install template."""
        return {
            "claude_version": self.claude_version or self._version,
            "mcp_git_source": self.mcp_git_source,
            "mcp_extras": self.mcp_extras,
            "install_r_languageserver": self.install_r_languageserver,
        }

    async def setup(self, environment: BaseEnvironment) -> None:
        await environment.exec(command="mkdir -p /installed-agent")

        setup_dir = self.logs_dir / "setup"
        setup_dir.mkdir(parents=True, exist_ok=True)

        if not self._install_agent_template_path.exists():
            raise FileNotFoundError(f"Install agent template file not found: {self._install_agent_template_path}")

        env = Environment()
        template = env.from_string(self._install_agent_template_path.read_text())
        rendered_script = template.render(**self._template_variables)

        script_path = self.logs_dir / "install.sh"
        script_path.write_text(rendered_script)

        await environment.upload_file(
            source_path=script_path,
            target_path="/installed-agent/install.sh",
        )

        install_env = None
        github_token = os.environ.get("GITHUB_TOKEN")
        if github_token:
            install_env = {"GITHUB_TOKEN": github_token}

        try:
            result = await environment.exec(
                command='bash -lc "bash /installed-agent/install.sh 2>&1 | tee /installed-agent/install.log"',
                env=install_env,
            )
            (setup_dir / "return-code.txt").write_text(str(result.return_code))
            if result.stdout:
                (setup_dir / "stdout.txt").write_text(result.stdout)
            if result.stderr:
                (setup_dir / "stderr.txt").write_text(result.stderr)
        except BaseException as exc:
            (setup_dir / "return-code.txt").write_text("timeout")
            (setup_dir / "exception.txt").write_text(str(exc))
            try:
                tail = await environment.exec(
                    command="tail -n 200 /installed-agent/install.log || true",
                    env=install_env,
                    timeout_sec=30,
                )
                if tail.stdout:
                    (setup_dir / "stdout.txt").write_text(tail.stdout)
                if tail.stderr:
                    (setup_dir / "stderr.txt").write_text(tail.stderr)
            except BaseException:
                pass
            raise

    def _get_session_dir(self) -> Path | None:
        """Select the best Claude Code session directory deterministically.

        Harbor's default implementation prints a warning and returns None when
        multiple session directories exist; that breaks trajectory extraction.
        """

        sessions_root = self.logs_dir / "sessions"
        project_root = sessions_root / "projects"
        if not project_root.exists():
            return None

        try:
            candidate_files = list(project_root.glob("**/*.jsonl"))
        except Exception:
            return None
        if not candidate_files:
            return None

        candidate_dirs = sorted({f.parent for f in candidate_files if f.parent.is_dir()})
        if not candidate_dirs:
            return None
        if len(candidate_dirs) == 1:
            return candidate_dirs[0]

        app_root = project_root / "-app"
        preferred = [d for d in candidate_dirs if (d == app_root or app_root in d.parents)]
        dirs = preferred or candidate_dirs

        def _score(d: Path) -> tuple[float, int]:
            try:
                files = list(d.glob("*.jsonl"))
                newest = max((f.stat().st_mtime for f in files), default=0.0)
                total_size = sum((f.stat().st_size for f in files), 0)
                return (float(newest), int(total_size))
            except Exception:
                return (0.0, 0)

        return max(dirs, key=_score)

    def create_run_agent_commands(self, instruction: str) -> list[ExecInput]:
        escaped_instruction = shlex.quote(instruction)

        env = {
            "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
            "CLAUDE_CODE_OAUTH_TOKEN": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", ""),
            "FORCE_AUTO_BACKGROUND_TASKS": "1",
            "ENABLE_BACKGROUND_TASKS": "1",
            "ANTHROPIC_CUSTOM_HEADERS": "anthropic-beta: interleaved-thinking-2025-05-14",
            "IS_SANDBOX": "1",
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
            # "--debug", #! disabled: triggers stack overflow in Claude Code 2.0.76 logging
            "--verbose",
            "--output-format",
            "stream-json",
            "--dangerously-skip-permissions",  # Non-interactive: skip permission prompts
            "-p",
            escaped_instruction,
        ]

        # Write MCP config to file if provided
        if self.mcp_config:
            mcp_file = "/tmp/mcp-config.json"
            setup_cmds.append(
                ExecInput(
                    command=f"cat << 'MCPEOF' > {mcp_file}\n{self.mcp_config}\nMCPEOF",
                    env=env,
                )
            )
            cmd_parts.extend(["--mcp-config", mcp_file])

        # Build settings.json with hooks and MCP permissions
        settings: dict[str, Any] = {}
        if self.hooks_config:
            hooks_data = json.loads(self.hooks_config) if isinstance(self.hooks_config, str) else self.hooks_config
            settings.update(hooks_data)

        permissions = settings.setdefault("permissions", {})
        permissions.setdefault("defaultMode", "bypassPermissions")

        # Pre-allow MCP tools if MCP config is provided
        # Per Claude Code docs: MCP permissions do NOT support wildcards.
        # Use mcp__<server_name> to approve ALL tools from that server.
        if self.mcp_config:
            mcp_data = json.loads(self.mcp_config) if isinstance(self.mcp_config, str) else self.mcp_config
            permissions.setdefault("allow", [])
            for server_name in mcp_data.get("mcpServers", {}).keys():
                permissions["allow"].append(f"mcp__{server_name}")

        settings_file = "/tmp/claude-settings.json"
        settings_json = json.dumps(settings)
        setup_cmds.append(
            ExecInput(
                command=f"cat << 'SETTINGSEOF' > {settings_file}\n{settings_json}\nSETTINGSEOF",
                env=env,
            )
        )
        cmd_parts.extend(["--settings", settings_file])

        # Add system prompt if provided (pass content directly, not file path)
        if self.system_prompt:
            escaped_prompt = shlex.quote(self.system_prompt)
            cmd_parts.extend(["--append-system-prompt", escaped_prompt])

        # Build final command string
        cmd = " ".join(cmd_parts) + " 2>&1 </dev/null | tee /logs/agent/claude-code.txt"

        return setup_cmds + [ExecInput(command=cmd, env=env)]
