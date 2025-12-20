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

    model: str = "anthropic/claude-sonnet-4-20250514"
    reasoning: str = "medium"
    mcp_config: Optional[str] = None  # Path to .mcp.json
    hooks: Optional[str] = None  # Path to hooks settings
    output_dir: Path = Path("./results/runs")
    harbor_bin: Optional[str] = None  # None = use uvx (auto-installs)
    container_env: str = "docker"
    env_file: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["output_dir"] = str(d["output_dir"])  # Path -> str for YAML
        return {k: v for k, v in d.items() if v is not None}


def load_config() -> TBConfig:
    """Load config from ~/.terminalbench/config.yaml if it exists."""
    if not YAML_AVAILABLE or not CONFIG_FILE.exists():
        return TBConfig()

    try:
        data = yaml.safe_load(CONFIG_FILE.read_text()) or {}
        filtered = {k: v for k, v in data.items() if k in TBConfig.__dataclass_fields__}
        if "output_dir" in filtered:
            filtered["output_dir"] = Path(filtered["output_dir"])
        return TBConfig(**filtered)
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
    mcp_config = prompt("MCP config file path (optional, e.g., .mcp.json)", current.mcp_config or "")
    hooks = prompt("Hooks settings file path (optional)", current.hooks or "")
    output_dir = prompt("Output directory", str(current.output_dir))
    harbor_bin = prompt("harbor binary path (empty=use uvx)", current.harbor_bin or "")
    container_env = prompt("Container runtime (docker/daytona/modal/e2b)", current.container_env)
    env_file = prompt("Env file path (optional)", current.env_file or "")

    new_config = TBConfig(
        model=model,
        reasoning=reasoning,
        mcp_config=mcp_config or None,
        hooks=hooks or None,
        output_dir=Path(output_dir),
        harbor_bin=harbor_bin or None,
        container_env=container_env,
        env_file=env_file or None,
    )

    save_config(new_config)
    print()
    print(f"Saved to {CONFIG_FILE}")
