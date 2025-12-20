from __future__ import annotations

import re
from typing import List, Optional


def normalize_path(path: str) -> str:
    """Normalize path to posix style."""
    parts = path.replace("\\", "/").split("/")
    out: List[str] = []
    for part in parts:
        if not part or part == ".":
            continue
        if part == "..":
            if out:
                out.pop()
            continue
        out.append(part)
    return "/".join(out)


def strip_strings_and_comments(src: str) -> str:
    """Remove strings and comments for cleaner parsing."""
    s = src
    # Block comments /* */
    s = re.sub(r"/\*[\s\S]*?\*/", "", s)
    # Line comments // (not URLs)
    s = re.sub(r"(^|[^:])//.*$", r"\1", s, flags=re.MULTILINE)
    # Python comments #
    s = re.sub(r"^[ \t]*#.*$", "", s, flags=re.MULTILINE)
    # Triple-quoted strings
    s = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", s)
    # Single/double quoted strings
    s = re.sub(r"\'(?:\\\\.|[^\'\\\\])*\'|\"(?:\\\\.|[^\"\\\\])*\"", "", s)
    return s


def join_py_import(from_spec: str, name: str) -> str:
    if not from_spec:
        return name
    if from_spec == ".":
        return f".{name}"
    if from_spec.startswith("."):
        return f"{from_spec}{name}"
    return f"{from_spec}.{name}"


def resolve_import_label(from_label: str, spec: str, lang: str) -> Optional[str]:
    """Resolve import specifier to module label."""
    try:
        posix_from = from_label.replace("\\", "/")
        base_dir = posix_from.rsplit("/", 1)[0] if "/" in posix_from else ""

        def rel(p: str) -> str:
            return normalize_path((base_dir + "/" if base_dir else "") + p)

        if lang == "py":
            if spec.startswith("."):
                up_match = re.match(r"^\.+", spec)
                dots = len(up_match.group(0)) if up_match else 0
                rest = spec[dots:].lstrip(".")
                pops = max(0, dots - 1)
                parts = base_dir.split("/") if base_dir else []
                parts = parts[: max(0, len(parts) - pops)]
                core = normalize_path("/".join(parts) + ("/" + rest.replace(".", "/") if rest else ""))
                return f"{core}.py"
            core = normalize_path(spec.replace(".", "/"))
            return f"{core}.py"

        if lang == "ts":
            if spec.startswith("."):
                core = rel(spec)
                if re.search(r"\.(ts|tsx|js|jsx)$", core, re.I):
                    return core
                return f"{core}.ts"
            if spec.startswith("/"):
                core = normalize_path(spec.lstrip("/"))
                return f"{core}.ts"
            return None

    except Exception:
        return None
    return None
