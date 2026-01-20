from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..views import svg_string_to_png_bytes
from ..views.architecture import ArchitectureView
from .graph_meta import _quality_tuple, compute_graph_meta, load_graph_meta
from .lock import canvas_artifact_lock
from .paths import get_canvas_dir, update_manifest


@dataclass(frozen=True)
class Snapshot:
    digest: str
    meta: dict[str, Any]
    meta_bytes: bytes
    architecture_png: bytes | None


def graph_meta_digest_path(project_dir: Path, digest: str) -> Path:
    return get_canvas_dir(project_dir) / f"graph_meta.{digest}.json"


def architecture_digest_path(project_dir: Path, digest: str) -> Path:
    return get_canvas_dir(project_dir) / f"architecture.{digest}.png"


def call_edges_digest_path(project_dir: Path, digest: str) -> Path:
    return get_canvas_dir(project_dir) / f"call_edges.{digest}.json"


def load_graph_meta_for_digest(project_dir: Path, digest: str | None) -> dict[str, Any] | None:
    if digest:
        path = graph_meta_digest_path(project_dir, digest)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else None
            except Exception:
                return None
    return load_graph_meta(project_dir)


def architecture_png_path_for_digest(project_dir: Path, digest: str | None) -> Path:
    if digest:
        return architecture_digest_path(project_dir, digest)
    return get_canvas_dir(project_dir) / "architecture.png"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_bytes(payload)
    tmp_path.replace(path)


def _architecture_meta(
    existing_meta: dict[str, Any] | None,
    *,
    digest: str,
    rendered_at: float | None,
) -> dict[str, Any]:
    latest_name = "architecture.png"
    digest_name = f"architecture.{digest}.png"
    base: dict[str, Any] = {}
    if isinstance(existing_meta, dict):
        arch = existing_meta.get("architecture")
        if isinstance(arch, dict) and arch.get("digest") == digest:
            base = dict(arch)
    if rendered_at is None and base.get("rendered_at"):
        rendered_at = float(base.get("rendered_at"))
    return {
        "latest_png": latest_name,
        "digest_png": digest_name,
        "digest": digest,
        "rendered_at": rendered_at,
    }


def _prefer_existing_pointer(existing_meta: dict[str, Any] | None, candidate_meta: dict[str, Any]) -> bool:
    if not isinstance(existing_meta, dict):
        return False
    if existing_meta.get("graph", {}).get("digest") == candidate_meta.get("graph", {}).get("digest"):
        return False
    existing_quality = existing_meta.get("graph", {}).get("quality") or {}
    candidate_quality = candidate_meta.get("graph", {}).get("quality") or {}
    return _quality_tuple(existing_quality) > _quality_tuple(candidate_quality)


def build_snapshot(
    *,
    graph,
    project_dir: Path,
    parse_summary: dict[str, Any],
    use_lsp: bool,
    lsp_langs: Iterable[str] | None,
    label_strip_prefix: str | None,
    action: str,
    existing_meta: dict[str, Any] | None = None,
) -> Snapshot:
    meta = compute_graph_meta(
        graph=graph,
        project_dir=project_dir,
        parse_summary=parse_summary,
        use_lsp=use_lsp,
        lsp_langs=lsp_langs,
        label_strip_prefix=label_strip_prefix,
        existing_meta=existing_meta,
    )
    digest = meta.get("graph", {}).get("digest") or ""
    arch_path = architecture_digest_path(project_dir, digest)
    rendered_at: float | None = None
    arch_bytes: bytes | None = None
    if digest and not arch_path.exists():
        svg = ArchitectureView(graph).render(output_path=None)
        arch_bytes = svg_string_to_png_bytes(svg)
        rendered_at = time.time()

    meta = dict(meta)
    meta["updated_by"] = {"pid": os.getpid(), "action": str(action)}
    meta["architecture"] = _architecture_meta(existing_meta, digest=digest, rendered_at=rendered_at)
    meta_bytes = json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")
    return Snapshot(digest=digest, meta=meta, meta_bytes=meta_bytes, architecture_png=arch_bytes)


def write_snapshot_files(project_dir: Path, snapshot: Snapshot) -> None:
    if not snapshot.digest:
        return
    meta_path = graph_meta_digest_path(project_dir, snapshot.digest)
    _write_bytes_atomic(meta_path, snapshot.meta_bytes)
    update_manifest(meta_path.parent, [meta_path.name])

    arch_path = architecture_digest_path(project_dir, snapshot.digest)
    if snapshot.architecture_png is not None:
        _write_bytes_atomic(arch_path, snapshot.architecture_png)
        update_manifest(arch_path.parent, [arch_path.name])


def _resolve_architecture_bytes(project_dir: Path, snapshot: Snapshot) -> bytes | None:
    if snapshot.architecture_png is not None:
        return snapshot.architecture_png
    if not snapshot.digest:
        return None
    arch_path = architecture_digest_path(project_dir, snapshot.digest)
    try:
        return arch_path.read_bytes()
    except Exception:
        return None


def flip_snapshot_pointers(project_dir: Path, snapshot: Snapshot) -> bool:
    if not snapshot.digest:
        return False
    existing_meta = load_graph_meta(project_dir)
    if _prefer_existing_pointer(existing_meta, snapshot.meta):
        return False

    arch_bytes = _resolve_architecture_bytes(project_dir, snapshot)
    if arch_bytes is None:
        return False

    meta_path = get_canvas_dir(project_dir) / "graph_meta.json"
    arch_path = get_canvas_dir(project_dir) / "architecture.png"

    with canvas_artifact_lock(project_dir, timeout_s=2.0) as locked:
        if not locked:
            return False
        _write_bytes_atomic(meta_path, snapshot.meta_bytes)
        _write_bytes_atomic(arch_path, arch_bytes)
        update_manifest(meta_path.parent, [meta_path.name, arch_path.name])
    return True


def write_call_edges_digest(project_dir: Path, digest: str, payload: dict[str, Any]) -> None:
    if not digest:
        return
    path = call_edges_digest_path(project_dir, digest)
    _write_json_atomic(path, payload)
    update_manifest(path.parent, [path.name])


def flip_call_edges_pointer(project_dir: Path, *, digest: str, payload: dict[str, Any]) -> bool:
    if not digest:
        return False
    meta = load_graph_meta(project_dir)
    if not isinstance(meta, dict):
        return False
    meta_digest = meta.get("graph", {}).get("digest")
    if meta_digest != digest:
        return False

    path = get_canvas_dir(project_dir) / "call_edges.json"
    with canvas_artifact_lock(project_dir, timeout_s=2.0) as locked:
        if not locked:
            return False
        _write_json_atomic(path, payload)
        update_manifest(path.parent, [path.name])
    return True
