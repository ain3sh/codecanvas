from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


DEFAULT_MODEL = "anthropic/claude-haiku-4-5"
DEFAULT_REASONING = "medium"


@dataclass(frozen=True)
class AgentProfile:
    """Configuration for a Terminal-Bench agent run."""

    key: str
    agent: str = "claude-code"
    model: str = DEFAULT_MODEL
    reasoning: str = DEFAULT_REASONING
    mcp_servers: List[str] = field(default_factory=list)
    extra_env: Dict[str, str] = field(default_factory=dict)
    hooks_path: Optional[str] = None

    def env(self) -> Dict[str, str]:
        env = dict(self.extra_env)
        if self.reasoning:
            env.setdefault("CLAUDE_CODE_REASONING", self.reasoning)
        if self.mcp_servers:
            env.setdefault("CLAUDE_CODE_MCP_SERVERS", ",".join(self.mcp_servers))
        if self.hooks_path:
            env.setdefault("CLAUDE_CODE_HOOKS", self.hooks_path)
        return env

    def harbor_args(self) -> List[str]:
        """Return CLI arguments for harbor run command."""
        args: List[str] = ["-a", self.agent, "-m", self.model]
        return args


ALL_AGENT_KEYS = ["text", "locagent", "codecanvas"]


def make_profiles(
    locagent_mcp: str | None,
    canvas_mcp: str | None,
    hooks_path: str | None = None,
    requested: str | List[str] | None = None,
) -> Dict[str, AgentProfile]:
    """Build profiles for evaluation agents.
    
    Args:
        requested: "all", single key, or list of keys. Default is "all".
    """
    if requested is None or requested == "all":
        keys = ALL_AGENT_KEYS
    elif isinstance(requested, str):
        keys = [requested]
    else:
        keys = list(requested)

    profiles: Dict[str, AgentProfile] = {}

    if "text" in keys:
        profiles["text"] = AgentProfile(key="text", hooks_path=hooks_path)

    if "locagent" in keys:
        profiles["locagent"] = AgentProfile(
            key="locagent",
            mcp_servers=[locagent_mcp] if locagent_mcp else [],
            hooks_path=hooks_path,
        )

    if "codecanvas" in keys:
        profiles["codecanvas"] = AgentProfile(
            key="codecanvas",
            mcp_servers=[canvas_mcp] if canvas_mcp else [],
            extra_env={"CODECANVAS_ENABLED": "1"},
            hooks_path=hooks_path,
        )

    return profiles


def resolve_mcp_env(value: str | None, env_var: str) -> Optional[str]:
    """Return the provided value or an environment fallback."""

    if value:
        return value
    return os.getenv(env_var)


def resolve_hooks_path(value: str | None) -> Optional[str]:
    """Resolve hooks config path from arg or CLAUDE_CODE_HOOKS env."""

    if value:
        return value
    return os.getenv("CLAUDE_CODE_HOOKS")
