from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Optional

from codecanvas.parser.utils import find_workspace_root

from ._hookio import get_mapping, get_str

_IGNORED_ROOT_PREFIXES: tuple[str, ...] = ("/usr", "/lib", "/opt")


def _has_project_markers(root: Path) -> bool:
    markers = (
        ".git",
        "pyproject.toml",
        "package.json",
        "go.mod",
        "Cargo.toml",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
    )
    for m in markers:
        try:
            if (root / m).exists():
                return True
        except Exception:
            continue
    return False


def _is_ignored_root(p: Path) -> bool:
    s = str(p)
    return any(s == pref or s.startswith(pref + "/") for pref in _IGNORED_ROOT_PREFIXES)


def _pick_candidate_path(tool_name: str, tool_input: Mapping[str, Any], cwd: str) -> str:
    if tool_name in {"Read", "Edit", "Write"}:
        p = get_str(tool_input, "file_path", "filePath")
        return p or cwd

    if tool_name == "Grep":
        return get_str(tool_input, "path") or cwd
    if tool_name == "Glob":
        return get_str(tool_input, "folder") or cwd
    if tool_name == "LS":
        return get_str(tool_input, "directory_path") or cwd

    # Bash and other tools: fall back to cwd.
    return cwd


def resolve_workspace_root(
    *,
    tool_name: str,
    tool_input: Mapping[str, Any],
    tool_response: Mapping[str, Any],
    cwd: str,
    sticky_root: str = "",
) -> Optional[Path]:
    # Prefer explicit file path when present (including tool_response camelCase).
    fp = get_str(tool_input, "file_path", "filePath") or get_str(tool_response, "filePath", "file_path")
    candidate = fp or _pick_candidate_path(tool_name, tool_input, cwd)
    if not candidate:
        return None

    root = find_workspace_root(candidate, prefer_env=False)
    if _is_ignored_root(root):
        # If we resolved to a system dir (e.g. /usr), try cwd instead.
        root = find_workspace_root(cwd, prefer_env=False)

    # Stickiness: keep prior root unless we find a more specific marker-backed root.
    if sticky_root:
        try:
            sticky = Path(sticky_root).absolute()
            if sticky.exists():
                sticky_marked = _has_project_markers(sticky)
                root_marked = _has_project_markers(root)

                if root.absolute() == sticky.absolute():
                    return sticky

                # Prefer the more specific marker-backed root.
                if root_marked and _path_is_relative_to(root.absolute(), sticky):
                    return root

                # Keep a marker-backed sticky root when the new root is unmarked.
                if sticky_marked and not root_marked and _path_is_relative_to(Path(cwd).absolute(), sticky):
                    return sticky
        except Exception:
            pass

    return root


def _path_is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except Exception:
        return False


def resolve_root_from_hook_input(input_data: Mapping[str, Any]) -> Optional[Path]:
    cwd = get_str(input_data, "cwd", default=os.getcwd())
    tool_name = get_str(input_data, "tool_name", "toolName")
    tool_input = get_mapping(input_data, "tool_input", "toolInput")
    tool_resp = get_mapping(input_data, "tool_response", "toolResponse")
    sticky_root = get_str(input_data, "_autocontext_active_root")
    return resolve_workspace_root(
        tool_name=tool_name,
        tool_input=tool_input,
        tool_response=tool_resp,
        cwd=cwd,
        sticky_root=sticky_root,
    )
