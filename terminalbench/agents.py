"""Agent profile configuration for Terminal-Bench harness."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_MODEL = "anthropic/claude-sonnet-4-20250514"
DEFAULT_REASONING = "medium"


def load_mcp_config(config_path: Path) -> Dict[str, Any]:
    """Load and parse MCP config file."""
    if not config_path.exists():
        return {"mcpServers": {}}
    return json.loads(config_path.read_text())


def filter_mcp_servers(
    config: Dict[str, Any],
    enabled_servers: List[str] | None
) -> Dict[str, Any]:
    """Filter MCP config to only include enabled servers."""
    if enabled_servers is None:
        return config  # All servers enabled

    return {
        "mcpServers": {
            name: cfg
            for name, cfg in config.get("mcpServers", {}).items()
            if name in enabled_servers
        }
    }


def get_available_servers(config_path: Path) -> List[str]:
    """Get list of available MCP server names from config."""
    config = load_mcp_config(config_path)
    return list(config.get("mcpServers", {}).keys())


@dataclass(frozen=True)
class AgentProfile:
    """Configuration for a Terminal-Bench agent run."""

    key: str
    agent: str = "claude-code"
    model: str = DEFAULT_MODEL
    reasoning: str = DEFAULT_REASONING
    mcp_config_json: Optional[str] = None  # JSON string of MCP config
    hooks_config_json: Optional[str] = None  # JSON string of hooks config
    locagent_git_url: Optional[str] = None  # Git URL for locagent installation
    locagent_git_ref: Optional[str] = None  # Git ref (branch/tag/commit)
    locagent_pip_package: Optional[str] = None  # Pip package spec
    extra_env: Dict[str, str] = field(default_factory=dict)

    def harbor_args(self) -> List[str]:
        """Return CLI arguments for harbor run command."""
        args: List[str] = ["-m", self.model]

        # Use custom agent with MCP support
        args.extend(["--agent-import-path", "terminalbench.harbor_agent:ClaudeCodeMCP"])

        # Pass MCP config as agent kwarg (JSON string)
        if self.mcp_config_json:
            args.extend(["--ak", f"mcp_config={self.mcp_config_json}"])

        # Pass hooks config as agent kwarg
        if self.hooks_config_json:
            args.extend(["--ak", f"hooks_config={self.hooks_config_json}"])

        # Pass reasoning level
        if self.reasoning:
            args.extend(["--ak", f"reasoning={self.reasoning}"])

        # Pass locagent installation options
        if self.locagent_git_url:
            args.extend(["--ak", f"locagent_git_url={self.locagent_git_url}"])
        if self.locagent_git_ref:
            args.extend(["--ak", f"locagent_git_ref={self.locagent_git_ref}"])
        if self.locagent_pip_package:
            args.extend(["--ak", f"locagent_pip_package={self.locagent_pip_package}"])

        return args

    def env(self) -> Dict[str, str]:
        """Return environment variables for the run."""
        return dict(self.extra_env)


def build_profile(
    key: str,
    model: str = DEFAULT_MODEL,
    reasoning: str = DEFAULT_REASONING,
    mcp_config_path: Optional[Path] = None,
    enabled_mcp_servers: Optional[List[str]] = None,
    hooks_path: Optional[Path] = None,
    locagent_git_url: Optional[str] = None,
    locagent_git_ref: Optional[str] = None,
    locagent_pip_package: Optional[str] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> AgentProfile:
    """Build an agent profile with MCP and hooks configuration."""

    # Load and filter MCP config
    mcp_config_json = None
    if mcp_config_path and mcp_config_path.exists():
        config = load_mcp_config(mcp_config_path)
        filtered = filter_mcp_servers(config, enabled_mcp_servers)
        if filtered.get("mcpServers"):
            mcp_config_json = json.dumps(filtered)

    # Load hooks config
    hooks_config_json = None
    if hooks_path and hooks_path.exists():
        hooks_config_json = hooks_path.read_text()

    return AgentProfile(
        key=key,
        model=model,
        reasoning=reasoning,
        mcp_config_json=mcp_config_json,
        hooks_config_json=hooks_config_json,
        locagent_git_url=locagent_git_url,
        locagent_git_ref=locagent_git_ref,
        locagent_pip_package=locagent_pip_package,
        extra_env=extra_env or {},
    )
