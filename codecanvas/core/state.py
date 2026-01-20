"""CodeCanvas state.

V5 introduces an Evidence Board model:
- Evidence: pointers to real, on-disk PNG artifacts (impact/architecture)
- Claims: agent-authored statements linked to Evidence IDs
- Decisions: explicit actions/commitments linked to Evidence IDs
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .paths import get_canvas_dir, update_manifest

STATE_VERSION = 2


_STATE_LOCK = threading.RLock()


def _get_state_path() -> Path:
    """Get path to state file (in .codecanvas with PNG outputs)."""
    project_dir = os.environ.get("CANVAS_PROJECT_DIR", os.getcwd())
    return get_canvas_dir(Path(project_dir)) / "state.json"


@dataclass
class AnalysisState:
    """State for a single impact analysis."""

    target_id: str
    target_label: str
    affected_ids: Set[str] = field(default_factory=set)
    addressed_ids: Set[str] = field(default_factory=set)
    skipped_ids: Set[str] = field(default_factory=set)
    test_ids: Set[str] = field(default_factory=set)

    def progress(self) -> tuple:
        """Return (done, total)."""
        done = len(self.addressed_ids) + len(self.skipped_ids)
        total = len(self.affected_ids)
        return done, total

    def remaining(self) -> Set[str]:
        """Return IDs not yet addressed or skipped."""
        return self.affected_ids - self.addressed_ids - self.skipped_ids

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_id": self.target_id,
            "target_label": self.target_label,
            "affected_ids": list(self.affected_ids),
            "addressed_ids": list(self.addressed_ids),
            "skipped_ids": list(self.skipped_ids),
            "test_ids": list(self.test_ids),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AnalysisState":
        return cls(
            target_id=d["target_id"],
            target_label=d["target_label"],
            affected_ids=set(d.get("affected_ids", [])),
            addressed_ids=set(d.get("addressed_ids", [])),
            skipped_ids=set(d.get("skipped_ids", [])),
            test_ids=set(d.get("test_ids", [])),
        )


def _next_id(prefix: str, existing: List[str]) -> str:
    mx = 0
    for e in existing:
        if not e.startswith(prefix):
            continue
        try:
            n = int(e[len(prefix) :])
            mx = max(mx, n)
        except Exception:
            continue
    return f"{prefix}{mx + 1}"


@dataclass
class Evidence:
    id: str
    kind: str  # impact|architecture
    png_path: str
    symbol: Optional[str] = None
    created_at: float = field(default_factory=lambda: time.time())
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "png_path": self.png_path,
            "symbol": self.symbol,
            "created_at": self.created_at,
            "metrics": dict(self.metrics or {}),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Evidence":
        return cls(
            id=str(d.get("id") or ""),
            kind=str(d.get("kind") or ""),
            png_path=str(d.get("png_path") or ""),
            symbol=d.get("symbol"),
            created_at=float(d.get("created_at") or time.time()),
            metrics=dict(d.get("metrics") or {}),
        )


@dataclass
class Claim:
    id: str
    kind: str  # hypothesis|finding|question
    text: str
    status: str = "active"  # active|retracted|superseded
    evidence_ids: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "status": self.status,
            "evidence_ids": list(self.evidence_ids),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Claim":
        return cls(
            id=str(d.get("id") or ""),
            kind=str(d.get("kind") or ""),
            text=str(d.get("text") or ""),
            status=str(d.get("status") or "active"),
            evidence_ids=list(d.get("evidence_ids") or []),
            created_at=float(d.get("created_at") or time.time()),
        )


@dataclass
class Decision:
    id: str
    kind: str  # mark|skip|plan|test|edit
    text: str
    target: Optional[str] = None
    evidence_ids: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "target": self.target,
            "evidence_ids": list(self.evidence_ids),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Decision":
        return cls(
            id=str(d.get("id") or ""),
            kind=str(d.get("kind") or ""),
            text=str(d.get("text") or ""),
            target=d.get("target"),
            evidence_ids=list(d.get("evidence_ids") or []),
            created_at=float(d.get("created_at") or time.time()),
        )


@dataclass
class CanvasState:
    """Persistent canvas state."""

    state_version: int = STATE_VERSION
    project_path: str = ""
    initialized: bool = False

    # Whether the graph was built with LSP enabled (affects reload behavior)
    use_lsp: bool = True

    # Parse backend breakdown from last init
    parse_summary: Dict[str, Any] = field(default_factory=dict)

    # Current graph digest (from graph_meta)
    graph_digest: Optional[str] = None

    # Current call edge cache digest (from call_edges pointer)
    call_edges_digest: Optional[str] = None

    # Call graph build summary (set after background completes)
    call_graph_summary: Dict[str, Any] = field(default_factory=dict)

    # Incremental refresh summary (latest)
    refresh_summary: Dict[str, Any] = field(default_factory=dict)

    # Incremental refresh metrics (cumulative counters)
    refresh_metrics: Dict[str, Any] = field(default_factory=dict)

    # Multi-target analysis support
    analyses: Dict[str, AnalysisState] = field(default_factory=dict)

    # Current focus symbol (used for auto-linking)
    focus: Optional[str] = None

    # Optional active task id (from tasks.yaml)
    active_task_id: Optional[str] = None

    # Evidence Board
    evidence: List[Evidence] = field(default_factory=list)
    claims: List[Claim] = field(default_factory=list)
    decisions: List[Decision] = field(default_factory=list)

    # Focus -> last evidence id (for default linking)
    last_evidence_id_by_focus: Dict[str, str] = field(default_factory=dict)

    # Symbol -> file mapping for quick lookup
    symbol_files: Dict[str, str] = field(default_factory=dict)

    def add_evidence(
        self,
        *,
        kind: str,
        png_path: str,
        symbol: Optional[str] = None,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> Evidence:
        eid = _next_id("E", [e.id for e in self.evidence if e.id])
        ev = Evidence(id=eid, kind=kind, png_path=png_path, symbol=symbol, metrics=dict(metrics or {}))
        self.evidence.append(ev)
        if self.focus:
            self.last_evidence_id_by_focus[self.focus] = ev.id
        if symbol:
            self.last_evidence_id_by_focus[symbol] = ev.id
        return ev

    def add_claim(self, *, kind: str, text: str, evidence_ids: List[str]) -> Claim:
        cid = _next_id("C", [c.id for c in self.claims if c.id])
        cl = Claim(id=cid, kind=kind, text=text, evidence_ids=list(evidence_ids))
        self.claims.append(cl)
        return cl

    def add_decision(self, *, kind: str, text: str, target: Optional[str], evidence_ids: List[str]) -> Decision:
        did = _next_id("D", [d.id for d in self.decisions if d.id])
        dc = Decision(id=did, kind=kind, text=text, target=target, evidence_ids=list(evidence_ids))
        self.decisions.append(dc)
        return dc

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_version": self.state_version,
            "project_path": self.project_path,
            "initialized": self.initialized,
            "use_lsp": self.use_lsp,
            "parse_summary": dict(self.parse_summary or {}),
            "graph_digest": self.graph_digest,
            "call_edges_digest": self.call_edges_digest,
            "call_graph_summary": dict(self.call_graph_summary or {}),
            "refresh_summary": dict(self.refresh_summary or {}),
            "refresh_metrics": dict(self.refresh_metrics or {}),
            "analyses": {k: v.to_dict() for k, v in self.analyses.items()},
            "focus": self.focus,
            "active_task_id": self.active_task_id,
            "evidence": [e.to_dict() for e in self.evidence],
            "claims": [c.to_dict() for c in self.claims],
            "decisions": [d.to_dict() for d in self.decisions],
            "last_evidence_id_by_focus": dict(self.last_evidence_id_by_focus),
            "symbol_files": self.symbol_files,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CanvasState":
        if int(d.get("state_version") or 0) != STATE_VERSION:
            return cls()
        state = cls(
            project_path=d.get("project_path", ""),
            initialized=d.get("initialized", False),
            use_lsp=bool(d.get("use_lsp", True)),
            parse_summary=dict(d.get("parse_summary") or {}),
            graph_digest=d.get("graph_digest"),
            call_edges_digest=d.get("call_edges_digest"),
            call_graph_summary=dict(d.get("call_graph_summary") or {}),
            refresh_summary=dict(d.get("refresh_summary") or {}),
            refresh_metrics=dict(d.get("refresh_metrics") or {}),
            symbol_files=d.get("symbol_files", {}),
        )
        for k, v in d.get("analyses", {}).items():
            state.analyses[k] = AnalysisState.from_dict(v)
        state.focus = d.get("focus")
        state.active_task_id = d.get("active_task_id")
        state.evidence = [Evidence.from_dict(e) for e in (d.get("evidence") or [])]
        state.claims = [Claim.from_dict(c) for c in (d.get("claims") or [])]
        state.decisions = [Decision.from_dict(dc) for dc in (d.get("decisions") or [])]
        state.last_evidence_id_by_focus = dict(d.get("last_evidence_id_by_focus") or {})
        return state


def load_state() -> CanvasState:
    """Load state from disk."""
    with _STATE_LOCK:
        path = _get_state_path()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return CanvasState.from_dict(json.load(f) or {})
            except Exception:
                try:
                    path.replace(path.with_name(path.name + ".bak"))
                except Exception:
                    pass
        return CanvasState()


def save_state(state: CanvasState):
    """Save state to disk.

    Saves to the primary artifact directory (see CANVAS_ARTIFACT_DIR).
    """
    with _STATE_LOCK:
        path = _get_state_path()
        tmp = path.with_name(path.name + ".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        json_str = json.dumps(state.to_dict(), indent=2)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json_str)
        tmp.replace(path)
        update_manifest(path.parent, [path.name])


def clear_state():
    """Clear state file."""
    path = _get_state_path()
    if path.exists():
        path.unlink()


# --- Task management (from tasks.yaml) ---


@dataclass(frozen=True)
class TaskSpec:
    id: str
    order: Optional[int] = None
    dataset: Optional[str] = None
    tb_url: Optional[str] = None
    gh_url: Optional[str] = None
    raw: Dict[str, Any] | None = None


def load_tasks_yaml(project_dir: str) -> List["TaskSpec"]:
    """Load tasks from tasks.yaml file."""
    import yaml

    path = Path(project_dir) / "tasks.yaml"
    if not path.exists():
        return []

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []

    tasks = data.get("tasks") or []
    out: List[TaskSpec] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or "").strip()
        if not tid:
            continue
        out.append(
            TaskSpec(
                id=tid,
                order=(int(t["order"]) if isinstance(t.get("order"), int) else None),
                dataset=t.get("dataset"),
                tb_url=t.get("tb_url"),
                gh_url=t.get("gh_url"),
                raw=dict(t),
            )
        )

    out.sort(key=lambda x: (x.order if x.order is not None else 10_000, x.id))
    return out


def pick_task(tasks: List["TaskSpec"], task_id: Optional[str]) -> Optional["TaskSpec"]:
    """Find a task by ID from the list."""
    if not task_id:
        return None
    for t in tasks:
        if t.id == task_id:
            return t
    return None
