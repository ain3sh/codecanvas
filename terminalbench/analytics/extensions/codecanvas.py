"""
CodeCanvas-Specific Analytics - Extensions for both deterministic and intelligent layers.

Provides:
- State parsing (CanvasState, etc.)
- Deterministic metrics (CodeCanvasMetrics)
- Vision analysis (CodeCanvasVisionAnalyzer)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

if TYPE_CHECKING:
    from ..core.intelligent import LLMAnalyzer
    from ..io.parser import ParsedTrajectory


# =============================================================================
# State Parsing (from state.json)
# =============================================================================


@dataclass
class CanvasEvidence:
    """Evidence item from state.json."""

    id: str
    kind: str  # impact | architecture
    png_path: str
    symbol: Optional[str]
    created_at: float
    metrics: Dict[str, Any]

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CanvasEvidence":
        return cls(
            id=str(d.get("id", "")),
            kind=str(d.get("kind", "")),
            png_path=str(d.get("png_path", "")),
            symbol=d.get("symbol"),
            created_at=float(d.get("created_at", 0)),
            metrics=dict(d.get("metrics", {})),
        )


@dataclass
class CanvasClaim:
    """Claim from state.json."""

    id: str
    kind: str  # hypothesis | finding | question
    text: str
    status: str
    evidence_ids: List[str]
    created_at: float

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CanvasClaim":
        return cls(
            id=str(d.get("id", "")),
            kind=str(d.get("kind", "")),
            text=str(d.get("text", "")),
            status=str(d.get("status", "active")),
            evidence_ids=list(d.get("evidence_ids", [])),
            created_at=float(d.get("created_at", 0)),
        )


@dataclass
class CanvasDecision:
    """Decision from state.json."""

    id: str
    kind: str  # mark | skip | plan | test | edit
    text: str
    target: Optional[str]
    evidence_ids: List[str]
    created_at: float

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CanvasDecision":
        return cls(
            id=str(d.get("id", "")),
            kind=str(d.get("kind", "")),
            text=str(d.get("text", "")),
            target=d.get("target"),
            evidence_ids=list(d.get("evidence_ids", [])),
            created_at=float(d.get("created_at", 0)),
        )


@dataclass
class CanvasAnalysisState:
    """Per-symbol analysis state from state.json."""

    target_id: str
    target_label: str
    affected_ids: Set[str]
    addressed_ids: Set[str]
    skipped_ids: Set[str]

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CanvasAnalysisState":
        return cls(
            target_id=str(d.get("target_id", "")),
            target_label=str(d.get("target_label", "")),
            affected_ids=set(d.get("affected_ids", [])),
            addressed_ids=set(d.get("addressed_ids", [])),
            skipped_ids=set(d.get("skipped_ids", [])),
        )

    def progress(self) -> tuple[int, int]:
        done = len(self.addressed_ids) + len(self.skipped_ids)
        total = len(self.affected_ids)
        return done, total


@dataclass
class CanvasState:
    """Parsed CodeCanvas state.json."""

    initialized: bool
    evidence: List[CanvasEvidence]
    claims: List[CanvasClaim]
    decisions: List[CanvasDecision]
    analyses: Dict[str, CanvasAnalysisState]
    symbol_files: Dict[str, str]
    parse_summary: Dict[str, Any]
    call_graph_summary: Dict[str, Any]

    @classmethod
    def from_json(cls, json_str: str) -> "CanvasState":
        d = json.loads(json_str)
        return cls(
            initialized=bool(d.get("initialized", False)),
            evidence=[CanvasEvidence.from_dict(e) for e in d.get("evidence", [])],
            claims=[CanvasClaim.from_dict(c) for c in d.get("claims", [])],
            decisions=[CanvasDecision.from_dict(dc) for dc in d.get("decisions", [])],
            analyses={k: CanvasAnalysisState.from_dict(v) for k, v in d.get("analyses", {}).items()},
            symbol_files=dict(d.get("symbol_files", {})),
            parse_summary=dict(d.get("parse_summary", {})),
            call_graph_summary=dict(d.get("call_graph_summary", {})),
        )

    @classmethod
    def empty(cls) -> "CanvasState":
        return cls(
            initialized=False,
            evidence=[],
            claims=[],
            decisions=[],
            analyses={},
            symbol_files={},
            parse_summary={},
            call_graph_summary={},
        )


def load_codecanvas_state(trial_dir: Path) -> Optional[CanvasState]:
    """Load state.json from agent/sessions/codecanvas/."""
    state_path = trial_dir / "agent" / "sessions" / "codecanvas" / "state.json"
    if not state_path.exists():
        return None
    try:
        return CanvasState.from_json(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def get_codecanvas_images(trial_dir: Path) -> Dict[str, Path]:
    """Get all CodeCanvas PNG images from the run."""
    images_dir = trial_dir / "agent" / "sessions" / "codecanvas"
    if not images_dir.exists():
        return {}
    return {png.stem: png for png in images_dir.glob("*.png")}


# =============================================================================
# Deterministic Metrics (Layer 1)
# =============================================================================


@dataclass
class CodeCanvasMetrics:
    """CodeCanvas-specific deterministic metrics."""

    # Basic counts
    evidence_count: int = 0
    claims_count: int = 0
    decisions_count: int = 0
    impact_analyses_count: int = 0

    # Claim breakdown
    hypotheses_count: int = 0
    findings_count: int = 0
    questions_count: int = 0

    # Decision breakdown
    marks_count: int = 0
    skips_count: int = 0
    plans_count: int = 0
    edits_count: int = 0

    # Core metrics
    blast_radius_edit_rate: float = 0.0
    anticipated_failure_rate: float = 0.0
    deliberation_depth: int = 0
    reasoning_density: float = 0.0
    systematic_progress: float = 0.0

    # Composite
    informed_editing_score: float = 0.0

    # Blast radius details
    total_affected_symbols: int = 0
    total_addressed_symbols: int = 0
    total_skipped_symbols: int = 0
    blast_radius_files: Set[str] = field(default_factory=set)
    edits_in_blast_radius: int = 0
    edits_outside_blast_radius: int = 0

    # Test-failure analysis
    failed_tests_in_blast_radius: int = 0
    failed_tests_outside_blast_radius: int = 0

    # Parse summary
    files_parsed: int = 0
    functions_parsed: int = 0
    classes_parsed: int = 0
    call_edges: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {k: list(v) if isinstance(v, set) else v for k, v in self.__dict__.items()}


def _normalize_path(path: str) -> str:
    """Normalize path for comparison."""
    p = Path(path)
    parts = p.parts[-3:] if len(p.parts) >= 3 else p.parts
    return "/".join(parts)


def _files_overlap(file1: str, file2: str) -> bool:
    """Check if two file paths likely refer to the same file."""
    n1, n2 = _normalize_path(file1), _normalize_path(file2)
    return n1 == n2 or n1.endswith(n2) or n2.endswith(n1)


def _count_matching_files(files1: Set[str], files2: Set[str]) -> int:
    """Count how many files from files1 match files in files2."""
    return sum(1 for f1 in files1 if any(_files_overlap(f1, f2) for f2 in files2))


def compute_codecanvas_metrics(
    trajectory: "ParsedTrajectory",
    state: CanvasState,
) -> CodeCanvasMetrics:
    """Compute CodeCanvas-specific metrics from trajectory and state."""
    m = CodeCanvasMetrics()

    # Basic counts
    m.evidence_count = len(state.evidence)
    m.claims_count = len(state.claims)
    m.decisions_count = len(state.decisions)
    m.impact_analyses_count = sum(1 for e in state.evidence if e.kind == "impact")

    # Claim breakdown
    m.hypotheses_count = sum(1 for c in state.claims if c.kind == "hypothesis")
    m.findings_count = sum(1 for c in state.claims if c.kind == "finding")
    m.questions_count = sum(1 for c in state.claims if c.kind == "question")

    # Decision breakdown
    m.marks_count = sum(1 for d in state.decisions if d.kind == "mark")
    m.skips_count = sum(1 for d in state.decisions if d.kind == "skip")
    m.plans_count = sum(1 for d in state.decisions if d.kind == "plan")
    m.edits_count = sum(1 for d in state.decisions if d.kind == "edit")

    # Aggregate analysis state
    for analysis in state.analyses.values():
        m.total_affected_symbols += len(analysis.affected_ids)
        m.total_addressed_symbols += len(analysis.addressed_ids)
        m.total_skipped_symbols += len(analysis.skipped_ids)

    # Parse summary - correct keys from state.json structure
    ps = state.parse_summary
    m.files_parsed = ps.get("parsed_files", 0)

    # Functions/classes come from architecture evidence metrics, not parse_summary
    arch_evidence = next((e for e in state.evidence if e.kind == "architecture"), None)
    if arch_evidence and arch_evidence.metrics:
        m.functions_parsed = arch_evidence.metrics.get("funcs", 0)
        m.classes_parsed = arch_evidence.metrics.get("classes", 0)

    cgs = state.call_graph_summary or {}
    if cgs.get("status") == "completed":
        m.call_edges = int(cgs.get("edges_total") or 0)
    else:
        m.call_edges = 0

    # Blast radius files
    blast_radius_files: Set[str] = set()
    for analysis in state.analyses.values():
        for symbol_id in analysis.affected_ids:
            if symbol_id in state.symbol_files:
                blast_radius_files.add(state.symbol_files[symbol_id])
    m.blast_radius_files = blast_radius_files

    # Files edited from trajectory
    files_edited: Set[str] = set()
    for step in trajectory.steps:
        for tc in step.tool_calls:
            if tc.function_name in ("Edit", "MultiEdit", "Create"):
                path = tc.arguments.get("file_path") or tc.arguments.get("path")
                if path:
                    files_edited.add(str(path))

    # 1. Blast Radius Edit Rate
    if files_edited:
        m.edits_in_blast_radius = _count_matching_files(files_edited, blast_radius_files)
        m.edits_outside_blast_radius = len(files_edited) - m.edits_in_blast_radius
        m.blast_radius_edit_rate = m.edits_in_blast_radius / len(files_edited)

    # 2. Anticipated Failure Rate
    if trajectory.verifier and trajectory.verifier.test_results:
        failed_tests = [t for t in trajectory.verifier.test_results if t.status == "failed"]
        if failed_tests:
            for test in failed_tests:
                test_file = test.name.split("::")[0] if "::" in test.name else test.name
                if any(_files_overlap(test_file, br) for br in blast_radius_files):
                    m.failed_tests_in_blast_radius += 1
                else:
                    m.failed_tests_outside_blast_radius += 1
            m.anticipated_failure_rate = m.failed_tests_in_blast_radius / len(failed_tests)

    # 3. Deliberation Depth
    m.deliberation_depth = m.claims_count + m.plans_count

    # 4. Reasoning Density
    if m.evidence_count > 0:
        m.reasoning_density = m.claims_count / m.evidence_count

    # 5. Systematic Progress
    if m.total_affected_symbols > 0:
        m.systematic_progress = (m.total_addressed_symbols + m.total_skipped_symbols) / m.total_affected_symbols

    # 6. Informed Editing Score (composite)
    m.informed_editing_score = (
        0.4 * m.blast_radius_edit_rate + 0.3 * m.anticipated_failure_rate + 0.3 * min(1.0, m.deliberation_depth / 3.0)
    )

    return m


def aggregate_codecanvas_metrics(metrics_list: List[CodeCanvasMetrics]) -> Dict[str, Any]:
    """Aggregate CodeCanvas metrics across multiple runs."""
    if not metrics_list:
        return {}
    n = len(metrics_list)
    return {
        "count": n,
        "avg_evidence_count": sum(m.evidence_count for m in metrics_list) / n,
        "avg_claims_count": sum(m.claims_count for m in metrics_list) / n,
        "avg_decisions_count": sum(m.decisions_count for m in metrics_list) / n,
        "avg_impact_analyses": sum(m.impact_analyses_count for m in metrics_list) / n,
        "avg_blast_radius_edit_rate": sum(m.blast_radius_edit_rate for m in metrics_list) / n,
        "avg_anticipated_failure_rate": sum(m.anticipated_failure_rate for m in metrics_list) / n,
        "avg_deliberation_depth": sum(m.deliberation_depth for m in metrics_list) / n,
        "avg_reasoning_density": sum(m.reasoning_density for m in metrics_list) / n,
        "avg_systematic_progress": sum(m.systematic_progress for m in metrics_list) / n,
        "avg_informed_editing_score": sum(m.informed_editing_score for m in metrics_list) / n,
    }


# =============================================================================
# Vision Analysis (Layer 2)
# =============================================================================


@dataclass
class VisualEditAlignment:
    """Result of visual-edit alignment analysis."""

    alignment_score: float
    aligned_edits: List[str]
    outside_edits: List[str]
    missed_dependencies: List[str]
    visual_understanding: str
    observations: List[str]
    recommendation: str
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceBoardQuality:
    """Result of evidence board quality analysis."""

    board_quality_score: float
    reasoning_style: str
    evidence_to_claim_linkage: float
    claim_to_decision_linkage: float
    progress_tracking_quality: str
    strengths: List[str]
    weaknesses: List[str]
    key_insight: str
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ArchitectureUnderstanding:
    """Result of architecture understanding analysis."""

    architecture_understanding: float
    relevant_modules_explored: List[str]
    irrelevant_exploration: List[str]
    missed_modules: List[str]
    edit_appropriateness: float
    observations: List[str]
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CodeCanvasVisualAnalysis:
    """Complete visual analysis for a CodeCanvas run."""

    has_images: bool
    impact_alignment: Optional[VisualEditAlignment] = None
    board_quality: Optional[EvidenceBoardQuality] = None
    architecture_understanding: Optional[ArchitectureUnderstanding] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_images": self.has_images,
            "impact_alignment": self.impact_alignment.raw_response if self.impact_alignment else None,
            "board_quality": self.board_quality.raw_response if self.board_quality else None,
            "architecture_understanding": (
                self.architecture_understanding.raw_response if self.architecture_understanding else None
            ),
        }


class CodeCanvasVisionAnalyzer:
    """Vision-powered analyzer for CodeCanvas artifacts. Uses LLMAnalyzer for API calls."""

    def __init__(self, analyzer: "LLMAnalyzer"):
        self.analyzer = analyzer

    def analyze_impact_alignment(
        self,
        impact_image: Path,
        files_edited: List[str],
        blast_radius_files: List[str],
    ) -> VisualEditAlignment:
        """Analyze alignment between impact visualization and actual edits."""
        from .prompts import VISUAL_EDIT_ALIGNMENT_PROMPT

        prompt = VISUAL_EDIT_ALIGNMENT_PROMPT.format(
            files_edited="\n".join(f"- {f}" for f in files_edited) if files_edited else "(none)",
            blast_radius_files="\n".join(f"- {f}" for f in blast_radius_files) if blast_radius_files else "(none)",
        )
        result = self.analyzer._call_vision(prompt, impact_image)

        return VisualEditAlignment(
            alignment_score=result.get("alignment_score", 0.0),
            aligned_edits=result.get("aligned_edits", []),
            outside_edits=result.get("outside_edits", []),
            missed_dependencies=result.get("missed_dependencies", []),
            visual_understanding=result.get("visual_understanding", "unknown"),
            observations=result.get("observations", []),
            recommendation=result.get("recommendation", ""),
            raw_response=result,
        )

    def analyze_evidence_board(self, board_image: Path) -> EvidenceBoardQuality:
        """Analyze quality of the evidence board reasoning trail."""
        from .prompts import EVIDENCE_BOARD_QUALITY_PROMPT

        result = self.analyzer._call_vision(EVIDENCE_BOARD_QUALITY_PROMPT, board_image)

        return EvidenceBoardQuality(
            board_quality_score=result.get("board_quality_score", 0.0),
            reasoning_style=result.get("reasoning_style", "unknown"),
            evidence_to_claim_linkage=result.get("evidence_to_claim_linkage", 0.0),
            claim_to_decision_linkage=result.get("claim_to_decision_linkage", 0.0),
            progress_tracking_quality=result.get("progress_tracking_quality", "none"),
            strengths=result.get("strengths", []),
            weaknesses=result.get("weaknesses", []),
            key_insight=result.get("key_insight", ""),
            raw_response=result,
        )

    def analyze_architecture_understanding(
        self,
        architecture_image: Path,
        task_description: str,
        files_explored: List[str],
        files_edited: List[str],
    ) -> ArchitectureUnderstanding:
        """Analyze whether agent understood the architecture visualization."""
        from .prompts import ARCHITECTURE_UNDERSTANDING_PROMPT

        prompt = ARCHITECTURE_UNDERSTANDING_PROMPT.format(
            task_description=task_description,
            files_explored="\n".join(f"- {f}" for f in files_explored) if files_explored else "(none)",
            files_edited="\n".join(f"- {f}" for f in files_edited) if files_edited else "(none)",
        )
        result = self.analyzer._call_vision(prompt, architecture_image)

        return ArchitectureUnderstanding(
            architecture_understanding=result.get("architecture_understanding", 0.0),
            relevant_modules_explored=result.get("relevant_modules_explored", []),
            irrelevant_exploration=result.get("irrelevant_exploration", []),
            missed_modules=result.get("missed_modules", []),
            edit_appropriateness=result.get("edit_appropriateness", 0.0),
            observations=result.get("observations", []),
            raw_response=result,
        )

    def analyze_run(
        self,
        trial_dir: Path,
        files_edited: List[str],
        files_read: List[str],
        blast_radius_files: List[str],
        task_description: str = "",
    ) -> CodeCanvasVisualAnalysis:
        """Run full visual analysis on a CodeCanvas run."""
        images = get_codecanvas_images(trial_dir)

        if not images:
            return CodeCanvasVisualAnalysis(has_images=False)

        analysis = CodeCanvasVisualAnalysis(has_images=True)

        # Analyze most recent impact image
        impact_images = sorted(k for k in images if k.startswith("impact"))
        if impact_images:
            analysis.impact_alignment = self.analyze_impact_alignment(
                images[impact_images[-1]], files_edited, blast_radius_files
            )

        if "board" in images:
            analysis.board_quality = self.analyze_evidence_board(images["board"])

        if "architecture" in images:
            analysis.architecture_understanding = self.analyze_architecture_understanding(
                images["architecture"], task_description, files_read, files_edited
            )

        return analysis
