"""Configuration management for terminalbench."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


CONFIG_DIR = Path.home() / ".terminalbench"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


@dataclass
class TBConfig:
    """Terminal-Bench configuration."""

    model: str = "anthropic/claude-haiku-4-5"
    reasoning: str = "medium"
    locagent_mcp: Optional[str] = None
    canvas_mcp: Optional[str] = None
    hooks_path: Optional[str] = None
    output_dir: str = "./runs"
    harbor_bin: Optional[str] = None  # None = use uvx (auto-installs)
    container_env: str = "docker"
    env_file: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def load_config() -> TBConfig:
    """Load config from ~/.terminalbench/config.yaml if it exists."""
    if not YAML_AVAILABLE or not CONFIG_FILE.exists():
        return TBConfig()

    try:
        data = yaml.safe_load(CONFIG_FILE.read_text()) or {}
        return TBConfig(**{k: v for k, v in data.items() if k in TBConfig.__dataclass_fields__})
    except Exception:
        return TBConfig()


def save_config(config: TBConfig) -> None:
    """Save config to ~/.terminalbench/config.yaml."""
    if not YAML_AVAILABLE:
        raise RuntimeError("pyyaml is required to save config")

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(yaml.dump(config.to_dict(), default_flow_style=False))


def run_setup() -> None:
    """Interactive setup wizard."""
    print()
    print("TerminalBench Configuration")
    print("-" * 30)

    current = load_config()

    def prompt(name: str, default: str) -> str:
        result = input(f"{name} [{default}]: ").strip()
        return result if result else default

    model = prompt("Model", current.model)
    reasoning = prompt("Reasoning level (low/medium/high)", current.reasoning)
    locagent_mcp = prompt("LocAgent MCP server URL (optional)", current.locagent_mcp or "")
    canvas_mcp = prompt("CodeCanvas MCP server URL (optional)", current.canvas_mcp or "")
    hooks_path = prompt("Hooks file path (optional)", current.hooks_path or "")
    output_dir = prompt("Output directory", current.output_dir)
    harbor_bin = prompt("harbor binary path (empty=use uvx)", current.harbor_bin or "")
    container_env = prompt("Container runtime (docker/daytona/modal/e2b)", current.container_env)
    env_file = prompt("Env file path (optional)", current.env_file or "")

    new_config = TBConfig(
        model=model,
        reasoning=reasoning,
        locagent_mcp=locagent_mcp or None,
        canvas_mcp=canvas_mcp or None,
        hooks_path=hooks_path or None,
        output_dir=output_dir,
        harbor_bin=harbor_bin or None,
        container_env=container_env,
        env_file=env_file or None,
    )

    save_config(new_config)
    print()
    print(f"Saved to {CONFIG_FILE}")
