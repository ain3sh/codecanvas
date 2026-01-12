from __future__ import annotations

import json
import sys
from typing import Any, Mapping


def read_stdin_json() -> dict[str, Any]:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return {}
    return data if isinstance(data, dict) else {}


def get_field(d: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in d:
            return d[name]
    return default


def get_mapping(d: Mapping[str, Any], *names: str) -> dict[str, Any]:
    val = get_field(d, *names, default={})
    return val if isinstance(val, dict) else {}


def get_str(d: Mapping[str, Any], *names: str, default: str = "") -> str:
    val = get_field(d, *names, default=default)
    return val if isinstance(val, str) else default


def get_hook_event_name(d: Mapping[str, Any]) -> str:
    return get_str(d, "hook_event_name", "hookEventName")


def get_tool_name(d: Mapping[str, Any]) -> str:
    return get_str(d, "tool_name", "toolName")


def get_tool_input(d: Mapping[str, Any]) -> dict[str, Any]:
    return get_mapping(d, "tool_input", "toolInput")


def get_tool_response(d: Mapping[str, Any]) -> dict[str, Any]:
    return get_mapping(d, "tool_response", "toolResponse")


def extract_file_path(d: Mapping[str, Any]) -> str:
    tool_input = get_tool_input(d)
    tool_resp = get_tool_response(d)
    # Per hooks docs: tool_input uses snake_case; tool_response often uses camelCase.
    p = get_str(tool_input, "file_path", "filePath")
    if p:
        return p
    return get_str(tool_resp, "filePath", "file_path")
