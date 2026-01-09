"""
TerminalBench Analytics - Hybrid evaluation framework for LLM agent trajectories.

Structure:
- core/: Analysis pillars (deterministic + intelligent)
- io/: Input/output (cli, parser, reports)
- extensions/: Extensions (prompts, codecanvas)
"""

from .core.comparisons import ComparisonResult, ProfileComparator
from .core.deterministic import DeterministicMetrics, compute_aggregate_metrics, compute_metrics
from .core.intelligent import LLMAnalyzer
from .extensions.codecanvas import (
    CanvasState,
    CodeCanvasMetrics,
    compute_codecanvas_metrics,
    load_codecanvas_state,
)
from .io.cli import main
from .io.parser import ParsedTrajectory, TrajectoryParser
from .io.reports import ReportGenerator

__all__ = [
    "main",
    "TrajectoryParser",
    "ParsedTrajectory",
    "ReportGenerator",
    "DeterministicMetrics",
    "compute_metrics",
    "compute_aggregate_metrics",
    "LLMAnalyzer",
    "ProfileComparator",
    "ComparisonResult",
    "CanvasState",
    "CodeCanvasMetrics",
    "load_codecanvas_state",
    "compute_codecanvas_metrics",
]
