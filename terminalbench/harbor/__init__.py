from .runner import HarborRunner, RunResult

__all__ = ["ClaudeCodeMCP", "HarborRunner", "RunResult"]


def __getattr__(name: str):
    """Lazy import for ClaudeCodeMCP (requires harbor SDK, only available in container)."""
    if name == "ClaudeCodeMCP":
        from .agent import ClaudeCodeMCP

        return ClaudeCodeMCP
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
