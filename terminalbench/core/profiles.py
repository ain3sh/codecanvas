"""Agent profile configuration for Terminal-Bench harness."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_MODEL = "anthropic/claude-sonnet-4-5-20250929"
DEFAULT_REASONING = "medium"

# Path to Python in the MCP venv created by install-claude-code-utils.sh
MCP_VENV_PYTHON = "/opt/venv/bin/python"

# Aliases for MCP server names -> source directory names (for USAGE.md discovery)
MCP_USAGE_ALIASES = {
    "codegraph": "locagent",
}

# Aliases for MCP server names -> Python extras names (for selective install)
MCP_EXTRAS_ALIASES = {
    "codegraph": "locagent",
}


def mcp_python_extras_for_servers(server_names: List[str]) -> List[str]:
    """Map enabled MCP server names to Python extras to install."""

    extras: list[str] = []
    for name in server_names:
        extras.append(MCP_EXTRAS_ALIASES.get(name, name))
    # Stable + unique
    return sorted(set(extras))


def load_mcp_config(config_path: Path) -> Dict[str, Any]:
    """Load and parse MCP config file."""
    if not config_path.exists():
        return {"mcpServers": {}}
    return json.loads(config_path.read_text())


def merge_mcp_configs(configs: List[Dict[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {"mcpServers": {}}
    for cfg in configs:
        for name, server_cfg in cfg.get("mcpServers", {}).items():
            merged["mcpServers"][name] = server_cfg
    return merged


def filter_mcp_servers(config: Dict[str, Any], enabled_servers: List[str] | None) -> Dict[str, Any]:
    """Filter MCP config to only include enabled servers."""
    if enabled_servers is None:
        return config  # All servers enabled

    return {"mcpServers": {name: cfg for name, cfg in config.get("mcpServers", {}).items() if name in enabled_servers}}


def get_available_servers(config_path: Path) -> List[str]:
    """Get list of available MCP server names from config."""
    config = load_mcp_config(config_path)
    return list(config.get("mcpServers", {}).keys())


def discover_mcp_usage_prompts(server_names: List[str], search_dir: Optional[Path] = None) -> Optional[str]:
    """Discover and combine USAGE.md files for enabled MCP servers.

    Looks for <server_name>/USAGE.md in the search directory (defaults to cwd).
    Returns combined content of all found USAGE.md files, or None if none found.
    """
    if search_dir is None:
        search_dir = Path.cwd()

    prompts = []
    for name in server_names:
        source_name = MCP_USAGE_ALIASES.get(name, name)
        usage_file = search_dir / source_name / "USAGE.md"
        if usage_file.exists():
            prompts.append(usage_file.read_text().strip())

    return "\n\n".join(prompts) if prompts else None


@dataclass(frozen=True)
class AgentProfile:
    """Configuration for a Terminal-Bench agent run."""

    key: str
    agent: str = "claude-code"
    model: str = DEFAULT_MODEL
    reasoning: str = DEFAULT_REASONING
    claude_version: Optional[str] = None
    mcp_config_json: Optional[str] = None  # JSON string of MCP config
    hooks_config_json: Optional[str] = None  # JSON string of hooks config
    mcp_git_source: Optional[str] = None  # Git URL for MCP server installation
    mcp_extras: Optional[str] = None  # Comma-separated extras (e.g. "codecanvas,locagent")
    install_r_languageserver: bool = False
    system_prompt: Optional[str] = None  # System prompt (e.g., from USAGE.md)
    extra_env: Dict[str, str] = field(default_factory=dict)

    def harbor_args(self) -> List[str]:
        """Return CLI arguments for harbor run command."""
        args: List[str] = ["-m", self.model]

        # Use custom agent with MCP support
        args.extend(["--agent-import-path", "terminalbench.harbor.agent:ClaudeCodeMCP"])

        # Pass MCP config as agent kwarg (JSON string)
        if self.mcp_config_json:
            args.extend(["--ak", f"mcp_config={self.mcp_config_json}"])

        # Pass hooks config as agent kwarg
        if self.hooks_config_json:
            args.extend(["--ak", f"hooks_config={self.hooks_config_json}"])

        # Pass reasoning level
        if self.reasoning:
            args.extend(["--ak", f"reasoning={self.reasoning}"])

        # Pass Claude version override (optional)
        if self.claude_version:
            args.extend(["--ak", f"claude_version={self.claude_version}"])

        # Pass MCP git source for installation in container
        if self.mcp_git_source:
            args.extend(["--ak", f"mcp_git_source={self.mcp_git_source}"])

        # Pass MCP extras to the install template (selective pip install)
        if self.mcp_extras:
            args.extend(["--ak", f"mcp_extras={self.mcp_extras}"])

        # Optional: install R languageserver (CodeCanvas-only)
        if self.install_r_languageserver:
            args.extend(["--ak", "install_r_languageserver=true"])

        # Pass system prompt
        if self.system_prompt:
            args.extend(["--ak", f"system_prompt={self.system_prompt}"])

        return args

    def env(self) -> Dict[str, str]:
        """Return environment variables for the run."""
        return dict(self.extra_env)


def adapt_mcp_config_for_harbor(config: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt MCP config for Harbor container environment.

    Local .mcp.json uses 'uv run python -m ...' but Harbor containers
    have packages installed in /opt/venv, so we convert to use that venv's Python.
    """
    adapted = {"mcpServers": {}}
    for name, server_cfg in config.get("mcpServers", {}).items():
        new_cfg = dict(server_cfg)
        # Convert 'uv run python -m X' to '/opt/venv/bin/python -m X'
        if new_cfg.get("command") == "uv" and new_cfg.get("args", [])[:2] == ["run", "python"]:
            new_cfg["command"] = MCP_VENV_PYTHON
            new_cfg["args"] = new_cfg["args"][2:]  # Remove 'run', 'python'
        adapted["mcpServers"][name] = new_cfg
    return adapted


def adapt_hooks_for_harbor(hooks_json: str) -> str:
    """Adapt hooks config for Harbor container environment.

    Local hooks.json uses 'uv run python' but Harbor containers
    have packages installed in /opt/venv, so we convert to use that venv's Python.
    """
    return hooks_json.replace("uv run python", MCP_VENV_PYTHON)


def build_profile(
    key: str,
    model: str = DEFAULT_MODEL,
    reasoning: str = DEFAULT_REASONING,
    claude_version: Optional[str] = None,
    mcp_config_path: Optional[Path] = None,
    mcp_config: Optional[Dict[str, Any]] = None,
    enabled_mcp_servers: Optional[List[str]] = None,
    hooks_path: Optional[Path] = None,
    mcp_git_source: Optional[str] = None,
    github_token: Optional[str] = None,
    system_prompt: Optional[str] = None,
    extra_env: Optional[Dict[str, str]] = None,
    install_r_languageserver: bool = False,
) -> AgentProfile:
    """Build an agent profile with MCP and hooks configuration."""

    # Load and filter MCP config, adapting for Harbor environment
    mcp_config_json = None
    mcp_extras = None
    if mcp_config is None and mcp_config_path and mcp_config_path.exists():
        mcp_config = load_mcp_config(mcp_config_path)

    if mcp_config is not None:
        filtered = filter_mcp_servers(mcp_config, enabled_mcp_servers)
        adapted = adapt_mcp_config_for_harbor(filtered)
        if adapted.get("mcpServers"):
            mcp_config_json = json.dumps(adapted)
            extras = mcp_python_extras_for_servers(list(adapted.get("mcpServers", {}).keys()))
            mcp_extras = ",".join(extras) if extras else None

    # Load hooks config, adapting for Harbor environment
    hooks_config_json = None
    if hooks_path and hooks_path.exists():
        hooks_config_json = adapt_hooks_for_harbor(hooks_path.read_text())

    # Build environment variables
    env = dict(extra_env or {})
    if github_token:
        env["GITHUB_TOKEN"] = github_token

    # Hooks are only meaningful when MCP is enabled.
    if not mcp_config_json:
        hooks_config_json = None

    # Don't bother installing MCP repo inside Harbor unless we will actually use it.
    if not mcp_config_json and not hooks_config_json:
        mcp_git_source = None

    return AgentProfile(
        key=key,
        model=model,
        reasoning=reasoning,
        claude_version=claude_version,
        mcp_config_json=mcp_config_json,
        hooks_config_json=hooks_config_json,
        mcp_git_source=mcp_git_source,
        mcp_extras=mcp_extras,
        install_r_languageserver=install_r_languageserver,
        system_prompt=system_prompt,
        extra_env=env,
    )
