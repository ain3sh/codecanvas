from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import Graph, NodeKind

GRAPH_META_VERSION = 1


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash_leaf(label: str, content_hash: str) -> str:
    try:
        content_bytes = bytes.fromhex(content_hash)
    except Exception:
        content_bytes = content_hash.encode("utf-8")
    payload = b"file\0" + label.encode("utf-8") + b"\0" + content_bytes
    return _sha256_hex(payload)


def _hash_missing(label: str) -> str:
    payload = b"missing\0" + label.encode("utf-8")
    return _sha256_hex(payload)


def _hash_config_leaf(config: dict) -> str:
    payload = b"config\0" + _canonical_json(config)
    return _sha256_hex(payload)


def _merkle_root(items: list[tuple[str, str]]) -> str:
    if not items:
        return _sha256_hex(b"empty")
    nodes = [bytes.fromhex(h) for _, h in items]
    while len(nodes) > 1:
        nxt: list[bytes] = []
        for i in range(0, len(nodes), 2):
            left = nodes[i]
            right = nodes[i + 1] if i + 1 < len(nodes) else nodes[i]
            nxt.append(hashlib.sha256(b"node\0" + left + right).digest())
        nodes = nxt
    return nodes[0].hex()


def _stat_signature(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except Exception:
        return {"missing": True}
    return {
        "missing": False,
        "mtime_ns": int(stat.st_mtime_ns),
        "size": int(stat.st_size),
    }


def _read_file_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _leaf_from_existing(
    *,
    existing: dict[str, Any] | None,
    label: str,
    fs_path: str,
    sig: dict[str, Any],
) -> Optional[dict[str, Any]]:
    if not existing:
        return None
    if str(existing.get("fs_path") or "") != fs_path:
        return None
    if bool(existing.get("missing")) is not bool(sig.get("missing")):
        return None
    if sig.get("missing"):
        leaf = existing.get("leaf")
        if isinstance(leaf, str) and leaf:
            return {**sig, "fs_path": fs_path, "leaf": leaf, "content_sha256": ""}
        return None
    if int(existing.get("mtime_ns") or -1) != int(sig.get("mtime_ns") or -2):
        return None
    if int(existing.get("size") or -1) != int(sig.get("size") or -2):
        return None
    content_sha256 = existing.get("content_sha256")
    leaf = existing.get("leaf")
    if not isinstance(content_sha256, str) or not content_sha256:
        return None
    if not isinstance(leaf, str) or not leaf:
        return None
    return {
        **sig,
        "fs_path": fs_path,
        "content_sha256": content_sha256,
        "leaf": leaf,
    }


def _graph_quality(parse_summary: dict[str, Any]) -> dict[str, int]:
    return {
        "parsed_files": int(parse_summary.get("parsed_files", 0) or 0),
        "skipped_files": int(parse_summary.get("skipped_files", 0) or 0),
        "lsp_files": int(parse_summary.get("lsp_files", 0) or 0),
        "tree_sitter_files": int(parse_summary.get("tree_sitter_files", 0) or 0),
    }


def compute_graph_meta(
    *,
    graph: Graph,
    project_dir: Path,
    parse_summary: dict[str, Any],
    use_lsp: bool,
    lsp_langs: Iterable[str] | None,
    label_strip_prefix: str | None,
    existing_meta: dict | None = None,
) -> dict:
    always_rehash = os.environ.get("CODECANVAS_MERKLE_ALWAYS_REHASH") == "1"
    existing_leaves = {}
    if isinstance(existing_meta, dict):
        existing_leaves = existing_meta.get("merkle", {}).get("leaves") or {}

    leaves: dict[str, dict[str, Any]] = {}
    for node in graph.nodes:
        if node.kind != NodeKind.MODULE:
            continue
        label = node.label
        fs_path = str(node.fsPath)
        sig = _stat_signature(Path(fs_path))
        cached = None if always_rehash else _leaf_from_existing(
            existing=existing_leaves.get(label) if isinstance(existing_leaves, dict) else None,
            label=label,
            fs_path=fs_path,
            sig=sig,
        )
        if cached is not None:
            leaves[label] = cached
            continue
        if sig.get("missing"):
            leaves[label] = {
                **sig,
                "fs_path": fs_path,
                "content_sha256": "",
                "leaf": _hash_missing(label),
            }
            continue
        try:
            content_sha256 = _sha256_hex(_read_file_bytes(Path(fs_path)))
        except Exception:
            leaves[label] = {
                **sig,
                "fs_path": fs_path,
                "content_sha256": "",
                "leaf": _hash_missing(label),
                "missing": True,
            }
            continue
        leaves[label] = {
            **sig,
            "fs_path": fs_path,
            "content_sha256": content_sha256,
            "leaf": _hash_leaf(label, content_sha256),
        }

    config_payload = {
        "version": GRAPH_META_VERSION,
        "use_lsp": bool(use_lsp),
        "lsp_langs": sorted(set(lsp_langs or [])),
        "label_strip_prefix": label_strip_prefix,
    }
    config_leaf = _hash_config_leaf(config_payload)

    items: list[tuple[str, str]] = [("\x00config", config_leaf)]
    for label, entry in leaves.items():
        leaf = entry.get("leaf")
        if isinstance(leaf, str) and leaf:
            items.append((label, leaf))
    items.sort(key=lambda x: x[0])
    root = _merkle_root(items)

    stats = dict(graph.stats())
    symbol_files = {n.id: n.fsPath for n in graph.nodes}

    quality = _graph_quality(parse_summary)

    meta = {
        "version": GRAPH_META_VERSION,
        "project_path": str(project_dir),
        "generated_at": time.time(),
        "parser": {
            "use_lsp": bool(use_lsp),
            "lsp_langs": sorted(set(lsp_langs or [])),
            "label_strip_prefix": label_strip_prefix,
        },
        "merkle": {
            "algo": "sha256",
            "strategy": "content_sha256_with_stat_reuse",
            "root": root,
            "leaf_count": len(leaves),
            "leaves": leaves,
            "config_leaf": config_leaf,
        },
        "graph": {
            "digest": root,
            "stats": stats,
            "parse_summary": dict(parse_summary or {}),
            "quality": quality,
            "symbol_files": symbol_files,
        },
        "architecture": {
            "latest_png": f"architecture.{root}.png",
            "digest_png": f"architecture.{root}.png",
            "digest": root,
            "rendered_at": None,
        },
    }
    return meta


