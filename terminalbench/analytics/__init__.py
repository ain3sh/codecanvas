"""
TerminalBench Analytics - Hybrid evaluation framework for LLM agent trajectories.

Structure:
- core/: Analysis pillars (deterministic + intelligent)
- io/: Input/output (cli, parser, reports)  
- extensions/: Extensions (prompts, codecanvas)
"""

from .io.cli import main
from .io.parser import TrajectoryParser, ParsedTrajectory
from .io.reports import ReportGenerator
from .core.deterministic import DeterministicMetrics, compute_metrics, compute_aggregate_metrics
from .core.intelligent import LLMAnalyzer
from .core.comparisons import ProfileComparator, ComparisonResult
from .extensions.codecanvas import (
    CanvasState,
    CodeCanvasMetrics,
    load_codecanvas_state,
    compute_codecanvas_metrics,
)

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
