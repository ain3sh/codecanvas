"""
TerminalBench Analytics v2 - Hybrid SOTA Agent Evaluation Framework

Two-layer architecture:
- Layer 1: Deterministic metrics computed from ATIF trajectories
- Layer 2: LLM-powered semantic analysis (GPT-5.2)
"""

from .parser import TrajectoryParser, ParsedTrajectory
from .deterministic import DeterministicMetrics, compute_metrics
from .comparisons import ProfileComparator, ComparisonResult
from .reports import ReportGenerator

__all__ = [
    "TrajectoryParser",
    "ParsedTrajectory", 
    "DeterministicMetrics",
    "compute_metrics",
    "ProfileComparator",
    "ComparisonResult",
    "ReportGenerator",
]
